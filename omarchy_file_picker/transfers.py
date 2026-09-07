"""Session-scoped transfer scheduling and verified, resumable copies.

Only the worker touches the filesystem. Copies live in a private destination
staging directory until verified, then renameat2 publishes without overwriting.
Moves are atomic renames only: never fall back to copy-and-delete across mounts.
"""
from __future__ import annotations

import ctypes
import errno
import hashlib
import os
from queue import Empty, SimpleQueue
import stat
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

CHUNK_SIZE = 1024 * 1024
MAX_ENTRIES = 100_000
TERMINAL = {'completed', 'cancelled'}
BUSY = {'running', 'pausing', 'cancelling'}


class RestartRequired(ValueError):
    """Saved bytes or the original source changed; never silently restart."""


class Interrupted(Exception):
    pass


def identity(info):
    # Filesystems can reuse an unlinked inode immediately for a different kind
    # of entry. A replacement symlink must never count as our partial file.
    return info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode)


def signature(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def rename_noreplace(source_fd, source, target_fd, target):
    library = ctypes.CDLL(None, use_errno=True)
    rename = getattr(library, 'renameat2', None)
    if rename is None:
        raise OSError(errno.ENOTSUP, 'This system cannot publish without overwriting.')
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(source_fd, os.fsencode(source), target_fd, os.fsencode(target), 1):
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(target))


@contextmanager
def directory_fd(path, expected=None):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        if expected is not None and identity(os.fstat(fd)) != expected:
            raise RestartRequired('A source or destination folder was replaced. Add a new transfer.')
        yield fd
    finally:
        os.close(fd)


@contextmanager
def relative_parent(root_fd, relative, owned=None):
    """Walk every intermediate directory without following replacement symlinks."""
    fd = os.dup(root_fd)
    try:
        trail = Path()
        for part in Path(relative).parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
            trail /= part
            if owned is not None and identity(os.fstat(fd)) != owned.get(trail):
                raise RestartRequired('A partial folder was replaced. It has been left untouched.')
        yield fd, Path(relative).name
    finally:
        os.close(fd)


def entry_stat(fd, name):
    return os.stat(name, dir_fd=fd, follow_symlinks=False)


@dataclass
class Entry:
    relative: Path
    stamp: tuple
    link: str | None = None
    digest: bytes | None = None

    @property
    def identity(self):
        return self.stamp[0], self.stamp[1], stat.S_IFMT(self.stamp[2])

    @property
    def size(self):
        return self.stamp[3] if stat.S_ISREG(self.stamp[2]) else 0


@dataclass
class Item:
    source: Path
    parent_id: tuple
    entries: list[Entry]
    completed: bool = False
    publishing: bool = False
    target_name: str = ''


@dataclass(eq=False)
class TransferJob:
    sources: list[Path]
    destination: Path
    cut: bool = False
    duplicate: bool = field(default=False, kw_only=True)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    state: str = 'queued'
    phase: str = 'Ready when you are'
    error: str = ''
    restart_required: bool = False
    total_bytes: int = 0
    done_bytes: int = 0
    verified_bytes: int = 0
    written_bytes: int = 0
    current_name: str = ''
    started: float = 0
    elapsed_seconds: float = 0
    active_since: float = 0
    items: list[Item] = field(default_factory=list)
    destination_id: tuple | None = None
    stage_name: str = ''
    stage_id: tuple | None = None
    owned: dict[Path, tuple] = field(default_factory=dict)
    completed: dict[Path, Path] = field(default_factory=dict)
    on_completed: object = None
    stop: threading.Event = field(default_factory=threading.Event)
    cancel_requested: bool = False

    def checkpoint(self):
        if self.stop.is_set():
            raise Interrupted()


class TransferEngine:
    def _copy_name(self, job, dest_fd, source, is_directory, reserved):
        """Choose on the worker; publication still atomically refuses races."""
        suffix = '' if is_directory else source.suffix
        stem = source.name[:-len(suffix)] if suffix else source.name
        name_limit = os.fpathconf(dest_fd, 'PC_NAME_MAX')
        if name_limit < 1:
            name_limit = 255
        for number in range(MAX_ENTRIES):
            job.checkpoint()
            if number:
                ending = (' copy' if number == 1 else f' copy {number}') + suffix
                short_stem = stem
                while short_stem and len(os.fsencode(short_stem + ending)) > name_limit:
                    short_stem = short_stem[:-1]
                name = short_stem + ending
            else:
                name = source.name
            if name in reserved:
                continue
            try:
                entry_stat(dest_fd, name)
            except FileNotFoundError:
                return name
        raise ValueError('Too many copies with this name. Rename the source before duplicating it.')

    def _scan(self, job, root_fd, name):
        entries = []

        def walk(fd, child, relative):
            job.checkpoint()
            info = entry_stat(fd, child)
            if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)):
                raise ValueError(f'{relative.name}: only files, folders and symbolic links can be copied.')
            entry = Entry(relative, signature(info),
                          os.readlink(child, dir_fd=fd) if stat.S_ISLNK(info.st_mode) else None)
            entries.append(entry)
            if len(entries) > MAX_ENTRIES:
                raise ValueError(f'A transfer item is limited to {MAX_ENTRIES:,} entries. Split this folder.')
            if stat.S_ISDIR(info.st_mode):
                sub = os.open(child, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                try:
                    if signature(os.fstat(sub)) != entry.stamp:
                        raise RestartRequired('The source changed while scanning. Restart unfinished items.')
                    for nested in sorted(os.listdir(sub)):
                        walk(sub, nested, relative / nested)
                    if signature(os.fstat(sub)) != entry.stamp:
                        raise RestartRequired('The source changed while scanning. Restart unfinished items.')
                finally:
                    os.close(sub)

        walk(root_fd, name, Path(name))
        return entries

    def _prepare(self, job, dest_fd):
        if job.items:
            return
        job.phase = 'Scanning files'
        if job.cut and job.duplicate:
            raise ValueError('Duplication only supports copies.')
        sources = job.sources
        resolved = [source.parent.resolve(strict=True) / source.name for source in sources]
        targets = [p.name for p in sources]
        if len(set(resolved)) != len(resolved) or (not job.duplicate and len(set(targets)) != len(targets)):
            raise ValueError('Duplicate source or destination names. Split these into separate batches.')
        for source in resolved:
            if not source.name or any(parent in resolved for parent in source.parents):
                raise ValueError('Transfer a folder and its selected contents in separate batches.')
            if not job.duplicate:
                try:
                    entry_stat(dest_fd, source.name)
                except FileNotFoundError:
                    pass
                else:
                    raise FileExistsError(f'{source.name} already exists in the destination. Nothing was overwritten.')
            if source == job.destination or source in job.destination.parents:
                raise ValueError('A folder cannot be transferred into itself.')
        items = []
        reserved = set()
        entry_count = 0
        for source in sources:
            job.checkpoint()
            with directory_fd(source.parent.resolve(strict=True)) as fd:
                if job.cut:
                    entries = [Entry(Path(source.name), signature(entry_stat(fd, source.name)))]
                else:
                    entries = self._scan(job, fd, source.name)
                entry_count += len(entries)
                if entry_count > MAX_ENTRIES:
                    raise ValueError(f'A batch is limited to {MAX_ENTRIES:,} entries. Split this transfer.')
                target = (self._copy_name(job, dest_fd, source, stat.S_ISDIR(entries[0].stamp[2]), reserved)
                          if job.duplicate else source.name)
                reserved.add(target)
                items.append(Item(source, identity(os.fstat(fd)), entries, target_name=target))
        job.sources = sources
        job.items = items
        job.total_bytes = sum(entry.size for item in items for entry in item.entries)

    def _stage(self, job, dest_fd):
        if not job.stage_name:
            name = '.omarchy-transfer-' + job.id
            os.mkdir(name, 0o700, dir_fd=dest_fd)
            job.stage_name = name
            job.stage_id = identity(entry_stat(dest_fd, name))
        fd = os.open(job.stage_name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dest_fd)
        if identity(os.fstat(fd)) != job.stage_id:
            os.close(fd)
            raise RestartRequired('The partial transfer folder was replaced. It has been left untouched.')
        return fd

    def _check_owned(self, job, fd, relative):
        with relative_parent(fd, relative, job.owned) as (parent, name):
            info = entry_stat(parent, name)
        if identity(info) != job.owned.get(relative):
            raise RestartRequired('A partial file was replaced. It has been left untouched.')
        if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
            raise RestartRequired('A partial file has unexpected hard links. It has been left untouched.')
        return info

    def _copy_file(self, job, source_fd, entry, stage_fd, relative):
        with relative_parent(source_fd, entry.relative) as (parent, name):
            src = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            if signature(os.fstat(src)) != entry.stamp:
                raise RestartRequired('The source changed. Restart unfinished items to copy the new version.')
            with relative_parent(stage_fd, relative, job.owned) as (parent, name):
                if relative in job.owned:
                    self._check_owned(job, stage_fd, relative)
                    dst = os.open(name, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
                else:
                    dst = os.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
                    job.owned[relative] = identity(os.fstat(dst))
            try:
                info = os.fstat(dst)
                if identity(info) != job.owned[relative] or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise RestartRequired('The partial file changed. It has been left untouched.')
                retained = info.st_size
                if retained > entry.size:
                    raise RestartRequired('The partial file is larger than its source. Restart unfinished items.')
                digest = hashlib.sha256()
                job.phase = 'Checking saved bytes' if retained else 'Copying'
                checked = 0
                while checked < retained:
                    job.checkpoint()
                    amount = min(CHUNK_SIZE, retained - checked)
                    data = self._read(src, amount)
                    if len(data) != amount or data != self._read(dst, amount):
                        raise RestartRequired('Saved bytes do not match the source. Restart unfinished items; resume was refused.')
                    digest.update(data)
                    checked += amount
                    job.verified_bytes += amount
                    job.done_bytes += amount
                job.phase = 'Copying'
                while checked < entry.size:
                    job.checkpoint()
                    data = self._read(src, min(CHUNK_SIZE, entry.size - checked))
                    if not data:
                        raise RestartRequired('The source became shorter. Restart unfinished items.')
                    self._write(dst, data)
                    digest.update(data)
                    checked += len(data)
                    job.written_bytes += len(data)
                    job.done_bytes += len(data)
                if signature(os.fstat(src)) != entry.stamp:
                    raise RestartRequired('The source changed during the copy. Restart unfinished items.')
                os.fsync(dst)
                # Retain owner write access while resumable; restore basic file
                # mode/timestamps only after verification, immediately before publish.
                entry.digest = digest.digest()
            finally:
                os.close(dst)
        finally:
            os.close(src)

    @staticmethod
    def _read(fd, amount):
        chunks = bytearray()
        while len(chunks) < amount:
            chunk = os.read(fd, amount - len(chunks))
            if not chunk:
                break
            chunks.extend(chunk)
        return bytes(chunks)

    @staticmethod
    def _write(fd, data):
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError('Could not write transfer data.')
            view = view[written:]

    def _verify(self, job, stage_fd, item, index):
        job.phase = 'Verifying copied files'
        for entry in item.entries:
            job.checkpoint()
            relative = Path(str(index)).joinpath(*entry.relative.parts[1:])
            info = self._check_owned(job, stage_fd, relative)
            with relative_parent(stage_fd, relative, job.owned) as (parent, name):
                if stat.S_ISREG(entry.stamp[2]):
                    if not stat.S_ISREG(info.st_mode) or info.st_size != entry.size:
                        raise RestartRequired('The partial file changed. Restart unfinished items.')
                    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
                    try:
                        if identity(os.fstat(fd)) != job.owned[relative]:
                            raise RestartRequired('The partial file was replaced.')
                        digest = hashlib.sha256()
                        while True:
                            job.checkpoint()
                            data = os.read(fd, CHUNK_SIZE)
                            if not data:
                                break
                            digest.update(data)
                        if digest.digest() != entry.digest:
                            raise RestartRequired('Copy verification failed. Restart unfinished items.')
                    finally:
                        os.close(fd)
                elif entry.link is not None:
                    if not stat.S_ISLNK(info.st_mode) or os.readlink(name, dir_fd=parent) != entry.link:
                        raise RestartRequired('A partial symbolic link changed.')
                else:
                    sub = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                    try:
                        expected = {p.name for p in job.owned if p.parent == relative}
                        if set(os.listdir(sub)) != expected:
                            raise RestartRequired('Unexpected files appeared in the partial folder. It has been left untouched.')
                    finally:
                        os.close(sub)

    def _copy_item(self, job, dest_fd, stage_fd, item, index):
        with directory_fd(item.source.parent.resolve(strict=True), item.parent_id) as source_fd:
            for entry in item.entries:
                job.checkpoint()
                job.current_name = str(entry.relative)
                relative = Path(str(index)).joinpath(*entry.relative.parts[1:])
                if stat.S_ISREG(entry.stamp[2]):
                    self._copy_file(job, source_fd, entry, stage_fd, relative)
                elif relative in job.owned:
                    self._check_owned(job, stage_fd, relative)
                else:
                    with relative_parent(stage_fd, relative, job.owned) as (parent, name):
                        if entry.link is not None:
                            os.symlink(entry.link, name, dir_fd=parent)
                        else:
                            os.mkdir(name, 0o700, dir_fd=parent)
                        job.owned[relative] = identity(entry_stat(parent, name))
            self._verify(job, stage_fd, item, index)
            current = self._scan(job, source_fd, item.source.name)
            if [(e.relative, e.stamp, e.link) for e in current] != [(e.relative, e.stamp, e.link) for e in item.entries]:
                raise RestartRequired('The source folder changed during the copy. Restart unfinished items.')
        job.checkpoint()
        self._check_destination(job)
        job.phase = 'Finishing item'
        # Metadata uses descriptor operations, never follows copied symlinks.
        for entry in reversed(item.entries):
            job.checkpoint()
            relative = Path(str(index)).joinpath(*entry.relative.parts[1:])
            if entry.link is not None:
                continue
            with relative_parent(stage_fd, relative, job.owned) as (parent, name):
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
                try:
                    if identity(os.fstat(fd)) != job.owned[relative]:
                        raise RestartRequired('A partial entry was replaced before completion.')
                    # Keep owner read/write/traverse on folders for recovery if
                    # publication fails. This is a data copy, not an ACL archive.
                    mode = stat.S_IMODE(entry.stamp[2]) & 0o777
                    os.fchmod(fd, mode | (0o700 if stat.S_ISDIR(entry.stamp[2]) else 0o600))
                    os.utime(fd, ns=(entry.stamp[4], entry.stamp[4]))
                finally:
                    os.close(fd)
        job.checkpoint()
        self._check_destination(job)
        self._publish(job, dest_fd, stage_fd, str(index), item, job.owned[Path(str(index))])
        for relative in list(job.owned):
            if relative.parts[0] == str(index):
                del job.owned[relative]

    @staticmethod
    def _check_destination(job):
        with directory_fd(job.destination, job.destination_id):
            pass

    def _publish(self, job, dest_fd, source_fd, name, item, expected_id):
        while True:
            try:
                return self._publish_named(job, dest_fd, source_fd, name, item, expected_id)
            except OSError as error:
                if (not job.duplicate or error.errno != errno.EEXIST or
                        identity(entry_stat(source_fd, name)) != expected_id):
                    raise
                # EEXIST left our staged inode in place. Keep the raced-in file
                # and choose another name; other errors retain the exact receipt.
                item.publishing = False
                reserved = {other.target_name for other in job.items if other is not item}
                item.target_name = self._copy_name(job, dest_fd, item.source,
                    stat.S_ISDIR(item.entries[0].stamp[2]), reserved)

    def _publish_named(self, job, dest_fd, source_fd, name, item, expected_id):
        item.publishing = True
        try:
            rename_noreplace(source_fd, name, dest_fd, item.target_name)
        except OSError:
            # A network filesystem can report an error after the rename committed.
            # Recognize only the exact owned inode, with the old name absent.
            try:
                done = identity(entry_stat(dest_fd, item.target_name)) == expected_id
                try:
                    entry_stat(source_fd, name)
                    done = False
                except FileNotFoundError:
                    pass
            except OSError:
                done = False
            if not done:
                raise
        if identity(entry_stat(dest_fd, item.target_name)) != expected_id:
            # A source-name race must not migrate annotations for the wrong
            # item. Restore without overwriting if possible; never delete it.
            try:
                rename_noreplace(dest_fd, item.target_name, source_fd, name)
            except OSError:
                raise RestartRequired(f'The item changed during publication. Inspect {job.destination / item.target_name}; nothing was deleted.')
            raise RestartRequired('The item changed during publication. Its replacement was restored; nothing was deleted.')
        self._record_completed(job, item)

    @staticmethod
    def _record_completed(job, item):
        item.completed, item.publishing = True, False
        job.completed[item.source] = job.destination / item.target_name
        if job.on_completed:
            job.on_completed(item.source, job.destination / item.target_name)

    def _reconcile(self, job, dest_fd, old_fd, name, item, expected_id):
        if not item.publishing:
            return False
        try:
            old_id = identity(entry_stat(old_fd, name))
        except FileNotFoundError:
            old_id = None
        try:
            target_id = identity(entry_stat(dest_fd, item.target_name))
        except FileNotFoundError:
            target_id = None
        if old_id != expected_id and target_id == expected_id:
            self._record_completed(job, item)
            return True
        if old_id != expected_id:
            raise RestartRequired(f'Completion could not be confirmed. Inspect {job.destination / item.target_name}; nothing else was changed.')
        item.publishing = False
        return False

    def run(self, job):
        job.error = ''
        job.restart_required = False
        job.done_bytes = sum(e.size for item in job.items if item.completed for e in item.entries)
        job.written_bytes = job.verified_bytes = 0
        job.started = time.monotonic()
        job.destination = job.destination.resolve(strict=True)
        with directory_fd(job.destination, job.destination_id) as dest_fd:
            job.destination_id = identity(os.fstat(dest_fd))
            self._prepare(job, dest_fd)
            stage_fd = self._stage(job, dest_fd) if not job.cut else None
            try:
                for index, item in enumerate(job.items):
                    if item.completed:
                        continue
                    job.checkpoint()
                    if job.cut:
                        job.phase, job.current_name = 'Moving item', item.source.name
                        self._check_destination(job)
                        with directory_fd(item.source.parent.resolve(strict=True), item.parent_id) as fd:
                            if self._reconcile(job, dest_fd, fd, item.source.name, item, item.entries[0].identity):
                                job.done_bytes += item.entries[0].size
                                continue
                            if signature(entry_stat(fd, item.source.name)) != item.entries[0].stamp:
                                raise RestartRequired('The source changed. Restart unfinished items to review its current version.')
                            try:
                                job.checkpoint()
                                self._publish(job, dest_fd, fd, item.source.name, item, item.entries[0].identity)
                            except OSError as error:
                                if error.errno == errno.EXDEV:
                                    raise ValueError('Moving between volumes is not supported. Use Copy, verify the result, then remove the original yourself.') from error
                                raise
                        job.done_bytes += item.entries[0].size
                    else:
                        if item.publishing and self._reconcile(job, dest_fd, stage_fd, str(index), item, job.owned[Path(str(index))]):
                            job.done_bytes += sum(e.size for e in item.entries)
                            for relative in list(job.owned):
                                if relative.parts[0] == str(index):
                                    del job.owned[relative]
                            continue
                        self._copy_item(job, dest_fd, stage_fd, item, index)
            finally:
                if stage_fd is not None:
                    os.close(stage_fd)
        self.cleanup(job)

    def cleanup(self, job):
        """Remove only our private, identity-checked partials; never final outputs."""
        if job.cut and any(item.publishing for item in job.items):
            with directory_fd(job.destination, job.destination_id) as dest_fd:
                for item in job.items:
                    if item.publishing:
                        with directory_fd(item.source.parent.resolve(strict=True), item.parent_id) as source_fd:
                            self._reconcile(job, dest_fd, source_fd, item.source.name, item, item.entries[0].identity)
        if not job.stage_name:
            return
        with directory_fd(job.destination, job.destination_id) as dest_fd:
            fd = self._stage(job, dest_fd)
            try:
                for index, item in enumerate(job.items):
                    if item.publishing and self._reconcile(job, dest_fd, fd, str(index), item, job.owned[Path(str(index))]):
                        for relative in list(job.owned):
                            if relative.parts[0] == str(index):
                                del job.owned[relative]
                # Validate the entire tree before deleting any of it.
                expected_top = {p.name for p in job.owned if len(p.parts) == 1}
                if set(os.listdir(fd)) != expected_top:
                    raise RestartRequired('The partial folder contains unexpected entries; cleanup left it untouched.')
                for relative in job.owned:
                    info = self._check_owned(job, fd, relative)
                    if stat.S_ISDIR(info.st_mode):
                        with relative_parent(fd, relative / '_', job.owned) as (sub, _):
                            if set(os.listdir(sub)) != {p.name for p in job.owned if p.parent == relative}:
                                raise RestartRequired('The partial folder contains unexpected entries; cleanup left it untouched.')
                for relative in sorted(job.owned, key=lambda p: len(p.parts), reverse=True):
                    info = self._check_owned(job, fd, relative)
                    with relative_parent(fd, relative, job.owned) as (parent, name):
                        (os.rmdir if stat.S_ISDIR(info.st_mode) else os.unlink)(name, dir_fd=parent)
                    del job.owned[relative]
                if identity(entry_stat(dest_fd, job.stage_name)) != job.stage_id:
                    raise RestartRequired('The partial folder was replaced; cleanup left it untouched.')
                os.rmdir(job.stage_name, dir_fd=dest_fd)
                job.stage_name, job.stage_id = '', None
            finally:
                os.close(fd)

    def restart(self, job):
        self.cleanup(job)
        # Completed items and move notifications must never run twice.
        remaining = [source for source in job.sources if source not in job.completed]
        job.items = []
        job.sources = remaining
        job.destination_id = None
        job.restart_required = False
        job.done_bytes = job.total_bytes = 0
        # Completed mappings retain history; only unfinished sources are replanned.


class TransferQueue:
    """Queue runs one job; All runs up to three independent jobs per window."""
    ALL_LIMIT = 3

    def __init__(self, engine=None, *, mode='queue'):
        self.engine = engine or TransferEngine()
        self.jobs = []
        self.pending = []
        self.pending_cleanup = []
        self.operations = {}
        self.active_jobs = []
        self.held = False
        self.lock = threading.RLock()
        self.events = SimpleQueue()
        self.mode = mode if mode in {'queue', 'all'} else 'queue'
        self.footprints = {}

    @property
    def active(self):
        # Compatibility for callers that only ask whether any work is active.
        with self.lock:
            return next(iter(self.active_jobs), None)

    @property
    def limit(self):
        return self.ALL_LIMIT if self.mode == 'all' else 1

    def set_mode(self, mode):
        if mode not in {'queue', 'all'}:
            raise ValueError('Choose Queue or All.')
        with self.lock:
            self.mode = mode
            # A mode change never starts staged jobs or resumes a held queue.
            # When narrowing to Queue, current workers finish before new starts.
            self._pump()

    @staticmethod
    def _footprint(job):
        # Pure path operations keep mount access out of GTK's scheduling calls.
        # Atomic publication/source verification remain the authority for alias
        # paths, external filesystem changes and other Files processes.
        normalize = lambda path: Path(os.path.normpath(path))
        reads = {normalize(path) for path in job.sources}
        writes = {normalize(job.destination / path.name) for path in job.sources}
        if job.duplicate:
            # Copy names are chosen offthread and can change after a collision.
            # Reserve their containing folder until this batch has settled.
            writes = {normalize(job.destination)}
        if job.cut:
            writes.update(reads)
        ancestors = lambda paths: set().union(*(set(path.parents) | {path} for path in paths))
        return reads | writes, writes, ancestors(reads | writes), ancestors(writes)

    def _conflicts(self, first, second):
        a, aw, ancestors_a, ancestors_aw = self.footprints[first]
        b, bw, ancestors_b, ancestors_bw = self.footprints[second]
        return bool(aw & ancestors_b or ancestors_aw & b or bw & ancestors_a or ancestors_bw & a)

    def add(self, sources, destination, cut=False, *, start=False, duplicate=False):
        with self.lock:
            if len(self.jobs) >= 100:
                raise ValueError('The queue is full. Clear finished transfers before adding more.')
            if cut and duplicate:
                raise ValueError('Duplication only supports copies.')
            job = TransferJob([Path(p).absolute() for p in sources], Path(destination).absolute(), cut,
                              duplicate=duplicate)
            if not job.sources:
                raise ValueError('Select at least one item.')
            self.jobs.append(job)
            self.footprints[job] = self._footprint(job)
            job.on_completed = lambda source, target: self.events.put((job, source, target))
            if start:
                self.pending.append(job)
                job.state, job.phase = 'waiting', 'Waiting for its turn'
                self._pump()
            return job

    def completed_events(self):
        events = []
        while True:
            try:
                events.append(self.events.get_nowait())
            except Empty:
                return events

    def start(self, job=None):
        with self.lock:
            if job is not None and (job.state not in {'queued', 'waiting', 'paused', 'failed'} or job.restart_required):
                return
            selected = [job] if job else [j for j in self.jobs if j.state in {'queued', 'waiting'}]
            if not selected:
                return
            self.held = False
            if job is not None and not self.active_jobs:
                if job in self.pending:
                    self.pending.remove(job)
                self.pending.insert(0, job)
            for current in selected:
                if current not in self.pending:
                    self.pending.append(current)
                current.state, current.phase = 'waiting', 'Waiting for its turn'
            self._pump()

    def _pump(self):
        # Requested cleanup can proceed while scheduling is held, but occupies
        # the same bounded worker slots as a normal transfer.
        while self.pending_cleanup and len(self.active_jobs) < self.limit:
            self._launch(self.pending_cleanup.pop(0), 'cancel')
        if self.held:
            return
        for job in list(self.pending):
            if len(self.active_jobs) >= self.limit:
                break
            # Keep dependent pending jobs in submission order. Paused/failed
            # transfers with saved state reserve their paths until resolved.
            reserved = self.active_jobs + self.pending[:self.pending.index(job)] + [
                other for other in self.jobs if other is not job and
                other.state in {'paused', 'failed', 'cancelling'} and
                (other.items or other.stage_name)]
            if any(self._conflicts(job, other) for other in reserved):
                job.phase = 'Waiting for a related transfer'
                continue
            self.pending.remove(job)
            self._launch(job, self.operations.pop(job, 'run'))

    def _launch(self, job, operation):
        self.active_jobs.append(job)
        job.active_since = time.monotonic()
        job.stop.clear()
        job.cancel_requested = operation == 'cancel'
        job.state = 'cancelling' if operation == 'cancel' else 'running'

        def worker():
            try:
                if operation == 'cancel':
                    self.engine.cleanup(job)
                else:
                    if operation == 'restart':
                        self.engine.restart(job)
                    self.engine.run(job)
                job.state = 'cancelled' if operation == 'cancel' else 'completed'
                job.phase = 'Cancelled · completed items kept' if operation == 'cancel' else 'Complete'
            except Interrupted:
                if job.cancel_requested:
                    try:
                        self.engine.cleanup(job)
                        job.state, job.phase = 'cancelled', 'Cancelled · completed items kept'
                    except Exception as error:
                        job.state, job.error = 'failed', f'Cleanup stopped: {error}'
                else:
                    job.state, job.phase = 'paused', 'Paused · saved bytes retained'
            except Exception as error:
                job.state, job.error = 'failed', str(error)
                job.restart_required = isinstance(error, RestartRequired)
            finally:
                with self.lock:
                    job.elapsed_seconds += time.monotonic() - job.active_since
                    job.active_since = 0
                    self.active_jobs.remove(job)
                    if job.state == 'failed' and self.mode == 'queue':
                        self.held = True
                    self._pump()

        threading.Thread(target=worker, name='file-transfer', daemon=True).start()

    def pause(self, job=None):
        with self.lock:
            if job is None or self.mode == 'queue':
                self.held = True
            for current in self.active_jobs:
                if (job is None or current is job) and current.state == 'running':
                    current.state = 'pausing'
                    current.stop.set()

    def cancel(self, job):
        with self.lock:
            if job.state in TERMINAL:
                return True
            if job in self.pending:
                self.pending.remove(job)
            self.operations.pop(job, None)
            if job in self.active_jobs:
                job.cancel_requested = True
                job.state = 'cancelling'
                job.stop.set()
            elif job.state not in TERMINAL and job not in self.pending_cleanup:
                if not job.stage_name and not any(item.publishing for item in job.items):
                    job.state, job.phase = 'cancelled', 'Cancelled · completed items kept'
                else:
                    job.state, job.phase = 'cancelling', 'Waiting to remove partial copies'
                    self.pending_cleanup.append(job)
                self._pump()
            return True

    def restart(self, job):
        with self.lock:
            if job in self.active_jobs or job.state not in {'failed', 'paused'}:
                return
            if job in self.pending:
                self.pending.remove(job)
            self.pending.insert(0, job)
            self.operations[job] = 'restart'
            job.state, job.phase = 'waiting', 'Waiting to restart unfinished items'
            self.held = False
            self._pump()

    def clear_finished(self):
        with self.lock:
            self.jobs[:] = [job for job in self.jobs if job.state not in TERMINAL or job in self.active_jobs]
            self.footprints = {job: paths for job, paths in self.footprints.items() if job in self.jobs}

    @property
    def unfinished(self):
        with self.lock:
            return bool(self.active_jobs or self.pending_cleanup) or any(job.state not in TERMINAL for job in self.jobs)
