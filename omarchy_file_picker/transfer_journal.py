"""Private, bounded transfer receipts, claimed by one window until it closes.

A lock has a stable inode separate from the atomically replaced receipt. Never
unlink lock files: another process may already hold or be waiting on that inode.
"""
from __future__ import annotations

import dataclasses
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import threading
import types
import typing
import uuid

MAX_BYTES = 64 * 1024 * 1024
MAX_JOBS = 100
ID = re.compile(r'^[0-9a-f]{32}$')
EXCLUDED = {'stop', 'persist', 'on_completed', 'on_checkpoint', 'undo_receipt'}


def default_directory():
    return Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'omarchy-file-picker/transfers'


def _encode(value):
    if isinstance(value, Path):
        return {'@path': str(value)}
    if isinstance(value, bytes):
        return {'@bytes': value.hex()}
    if isinstance(value, tuple):
        return {'@tuple': [_encode(v) for v in value]}
    if isinstance(value, dict):
        return {'@dict': [[_encode(k), _encode(v)] for k, v in value.items()]}
    if isinstance(value, list):
        return [_encode(v) for v in value]
    if dataclasses.is_dataclass(value):
        return {'@type': type(value).__name__, 'fields': {
            field.name: _encode(getattr(value, field.name))
            for field in dataclasses.fields(value) if field.name not in EXCLUDED}}
    if value is None or type(value) in {str, int, float, bool}:
        return value
    raise ValueError('Unsupported transfer recovery value.')


def _decode(value, types, depth=0):
    if depth > 40:
        raise ValueError('Transfer recovery data is nested too deeply.')
    decode = lambda v: _decode(v, types, depth + 1)
    if isinstance(value, list):
        return [decode(v) for v in value]
    if not isinstance(value, dict):
        return value
    if set(value) == {'@path'}:
        if not isinstance(value['@path'], str) or '\0' in value['@path']:
            raise ValueError('Invalid recovery path.')
        return Path(value['@path'])
    if set(value) == {'@bytes'}:
        result = bytes.fromhex(value['@bytes'])
        if len(result) != 32:
            raise ValueError('Invalid recovery digest.')
        return result
    if set(value) == {'@tuple'}:
        return tuple(decode(v) for v in value['@tuple'])
    if set(value) == {'@dict'}:
        pairs = [(decode(k), decode(v)) for k, v in value['@dict']]
        result = dict(pairs)
        if len(result) != len(pairs):
            raise ValueError('Duplicate recovery mapping.')
        return result
    if set(value) == {'@type', 'fields'} and value['@type'] in types:
        cls = types[value['@type']]
        allowed = {f.name for f in dataclasses.fields(cls)} - EXCLUDED
        if not isinstance(value['fields'], dict) or not set(value['fields']) <= allowed:
            raise ValueError('Unknown transfer recovery fields.')
        return cls(**{k: decode(v) for k, v in value['fields'].items()})
    raise ValueError('Invalid transfer recovery structure.')


def _matches(value, hint):
    origin = typing.get_origin(hint)
    args = typing.get_args(hint)
    if origin in {typing.Union, types.UnionType}:
        return any(_matches(value, choice) for choice in args)
    if origin is list:
        return isinstance(value, list) and all(_matches(v, args[0]) for v in value)
    if origin is dict:
        return isinstance(value, dict) and all(_matches(k, args[0]) and _matches(v, args[1]) for k, v in value.items())
    if hint in {bool, int, str, bytes}:
        return type(value) is hint
    if hint is float:
        return type(value) in {float, int}
    return isinstance(value, hint)


def _validate_types(value):
    for name, hint in typing.get_type_hints(type(value)).items():
        if name in EXCLUDED:
            continue
        current = getattr(value, name)
        if not _matches(current, hint):
            raise ValueError(f'Invalid recovery field: {name}.')


def _validate(job, expected_id):
    from .transfers import Entry, Item, TransferJob, MAX_ENTRIES
    if not isinstance(job, TransferJob) or job.id != expected_id:
        raise ValueError('Transfer recovery identity does not match.')
    _validate_types(job)
    absolute = lambda p: isinstance(p, Path) and p.is_absolute() and '..' not in p.parts
    relative = lambda p: isinstance(p, Path) and bool(p.parts) and not p.is_absolute() and '..' not in p.parts
    ident = lambda p: isinstance(p, tuple) and len(p) == 3 and all(type(v) is int for v in p)
    if not absolute(job.destination) or not isinstance(job.sources, list) or not all(absolute(p) for p in job.sources):
        raise ValueError('Invalid transfer recovery source or destination.')
    if len(job.sources) > MAX_ENTRIES or len(job.items) > MAX_ENTRIES or len(job.owned) > MAX_ENTRIES:
        raise ValueError('Transfer recovery manifest is too large.')
    if job.stage_name not in {'', '.omarchy-transfer-' + job.id}:
        raise ValueError('Invalid partial transfer folder.')
    if (job.destination_id is not None and not ident(job.destination_id)) or (job.stage_id is not None and not ident(job.stage_id)):
        raise ValueError('Invalid recovery folder identity.')
    if bool(job.stage_name) != bool(job.stage_id):
        raise ValueError('Incomplete recovery folder identity.')
    removing = getattr(job, 'cleanup_removing', None)
    if removing is not None and (not relative(removing) or removing not in job.owned):
        raise ValueError('Invalid partial cleanup receipt.')
    if not all(relative(p) and ident(stamp) for p, stamp in job.owned.items()):
        raise ValueError('Invalid partial transfer entry.')
    if not all(absolute(source) and absolute(target) and target.parent == job.destination for source, target in job.completed.items()):
        raise ValueError('Invalid transfer completion receipt.')
    if not all(source in job.completed and value >= 0 for source, value in job.completion_times.items()):
        raise ValueError('Invalid transfer completion order.')
    count = 0
    for index, item in enumerate(job.items):
        _validate_types(item)
        if getattr(item, 'restore_name', '') and (Path(item.restore_name).name != item.restore_name or item.restore_name in {'.', '..'}):
            raise ValueError('Invalid retained original name.')
        if getattr(item, 'retained_source', None) is not None and (not absolute(item.retained_source) or item.retained_source.parent != item.source.parent):
            raise ValueError('Invalid retained original path.')
        if item.quarantine_name not in {'', f'.omarchy-move-{job.id}-{index}'}:
            raise ValueError('Invalid held original name.')
        for stamp in (item.published_id, item.quarantine_id):
            if stamp is not None and not ident(stamp):
                raise ValueError('Invalid moved item identity.')
        manifest_paths = {entry.relative for entry in item.entries}
        if not set(item.removed) <= manifest_paths or (item.removing is not None and item.removing not in manifest_paths):
            raise ValueError('Invalid source removal receipt.')
        if not isinstance(item, Item) or not absolute(item.source) or not ident(item.parent_id):
            raise ValueError('Invalid transfer item.')
        if item.source not in job.sources and item.source not in job.completed:
            raise ValueError('Unknown transfer source.')
        if not item.target_name or Path(item.target_name).name != item.target_name or item.target_name in {'.', '..'}:
            raise ValueError('Invalid recovery target name.')
        for entry in item.entries:
            _validate_types(entry)
            count += 1
            if not isinstance(entry, Entry) or not relative(entry.relative) or entry.relative.parts[0] != item.source.name:
                raise ValueError('Invalid recovery manifest entry.')
            if not isinstance(entry.stamp, tuple) or len(entry.stamp) != 6 or not all(type(v) is int for v in entry.stamp):
                raise ValueError('Invalid source signature.')
        if not item.entries:
            raise ValueError('Empty recovery manifest.')
    if count > MAX_ENTRIES:
        raise ValueError('Transfer recovery manifest is too large.')
    if getattr(job, 'recovery_operation', 'run') not in {'run', 'restart', 'cancel', 'keep'}:
        raise ValueError('Unknown transfer recovery operation.')
    if job.state not in {'queued', 'waiting', 'running', 'pausing', 'paused', 'failed', 'cancelling', 'cancelled', 'completed'}:
        raise ValueError('Unknown transfer recovery state.')


class TransferJournal:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise OSError('Transfer recovery folder must be private and owned by your user.')
        self.fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        self.claims = {}
        self.lock = threading.RLock()
        self.errors = []

    def _claim(self, job_id):
        if not ID.fullmatch(job_id):
            raise ValueError('Invalid transfer identity.')
        if job_id in self.claims:
            return True
        fd = os.open(job_id + '.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=self.fd)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
                raise OSError('Unsafe transfer recovery lock.')
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                os.close(fd)
                return False
            self.claims[job_id] = fd
            return True
        except BaseException:
            os.close(fd)
            raise

    def recover(self):
        from .transfers import Entry, Item, TransferJob
        recovered = []
        candidates = sorted(name for name in os.listdir(self.fd) if name.endswith('.json'))
        if len(candidates) > MAX_JOBS:
            self.errors.append('Too many saved transfers; recovery is limited to 100 jobs.')
        for name in candidates[:MAX_JOBS]:
            job_id = name[:-5]
            try:
                if not self._claim(job_id):
                    continue
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self.fd)
                try:
                    info = os.fstat(fd)
                    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or info.st_size > MAX_BYTES:
                        raise ValueError('Unsafe or oversized transfer recovery file.')
                    with os.fdopen(fd, 'rb', closefd=False) as stream:
                        raw = stream.read(MAX_BYTES + 1)
                    if len(raw) > MAX_BYTES:
                        raise ValueError('Transfer recovery file is too large.')
                finally:
                    os.close(fd)
                data = json.loads(raw)
                if not isinstance(data, dict) or data.get('version') != 1:
                    raise ValueError('Unsupported transfer recovery version.')
                job = _decode(data['job'], {c.__name__: c for c in (Entry, Item, TransferJob)})
                _validate(job, job_id)
                recovered.append(job)
            except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError) as error:
                self.errors.append(f'Saved transfer {job_id[:8]} could not be recovered: {error} Files were left untouched.')
        return recovered

    def save(self, job):
        with self.lock:
            if self.fd is None or not self._claim(job.id):
                raise OSError('This transfer is already owned by another Gudfiles window.')
            raw = json.dumps({'version': 1, 'job': _encode(job)}, separators=(',', ':'), allow_nan=False).encode()
            if len(raw) > MAX_BYTES:
                raise ValueError('Transfer recovery data is too large. Split this transfer.')
            temporary = '.' + job.id + '-' + uuid.uuid4().hex + '.tmp'
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=self.fd)
            try:
                with os.fdopen(fd, 'wb', closefd=False) as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(fd)
                os.rename(temporary, job.id + '.json', src_dir_fd=self.fd, dst_dir_fd=self.fd)
                os.fsync(self.fd)
            finally:
                os.close(fd)
                try:
                    os.unlink(temporary, dir_fd=self.fd)
                except FileNotFoundError:
                    pass

    def remove(self, job_id):
        with self.lock:
            if job_id not in self.claims:
                raise OSError('Transfer recovery receipt is not owned by this window.')
            try:
                os.unlink(job_id + '.json', dir_fd=self.fd)
            except FileNotFoundError:
                pass
            os.fsync(self.fd)

    def close(self):
        with self.lock:
            for fd in self.claims.values():
                os.close(fd)
            self.claims.clear()
            if self.fd is not None:
                os.close(self.fd)
                self.fd = None
