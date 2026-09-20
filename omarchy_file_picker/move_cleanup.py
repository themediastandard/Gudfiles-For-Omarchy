"""Complete a verified cross-volume move without deleting changed sources."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat

from .transfers import (CHUNK_SIZE, RestartRequired, directory_fd, entry_stat,
                        identity, relative_parent, rename_noreplace, signature)


def _relative(entry, name):
    return Path(name).joinpath(*entry.relative.parts[1:])


def _verify_destination(job, dest_fd, item):
    """Re-read published bytes before any original is removed, including resume."""
    if identity(entry_stat(dest_fd, item.target_name)) != item.published_id:
        raise RestartRequired('The verified destination was replaced. The remaining originals were kept.')
    stamps = {}
    children = {}
    for entry in item.entries[1:]:
        children.setdefault(entry.relative.parent, set()).add(entry.relative.name)
    for entry in item.entries:
        job.checkpoint()
        relative = _relative(entry, item.target_name)
        with relative_parent(dest_fd, relative) as (parent, name):
            info = entry_stat(parent, name)
            if stat.S_IFMT(info.st_mode) != stat.S_IFMT(entry.stamp[2]):
                raise RestartRequired('The destination changed. The remaining originals were kept.')
            if stat.S_ISREG(info.st_mode):
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
                try:
                    before = signature(os.fstat(fd))
                    if before != signature(info) or info.st_size != entry.size:
                        raise RestartRequired('The destination changed. The remaining originals were kept.')
                    digest = hashlib.sha256()
                    while data := os.read(fd, CHUNK_SIZE):
                        job.checkpoint()
                        digest.update(data)
                    if digest.digest() != entry.digest or signature(os.fstat(fd)) != before:
                        raise RestartRequired('The destination no longer matches its verified copy. Originals were kept.')
                finally:
                    os.close(fd)
            elif entry.link is not None:
                if os.readlink(name, dir_fd=parent) != entry.link:
                    raise RestartRequired('The destination link changed. Originals were kept.')
            else:
                fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                try:
                    expected = children.get(entry.relative, set())
                    if set(os.listdir(fd)) != expected:
                        raise RestartRequired('The destination folder changed. Originals were kept.')
                finally:
                    os.close(fd)
            stamps[entry.relative] = signature(info)
    return stamps


def _same_source(info, entry, *, root=False, directory_changed=False):
    current = signature(info)
    if root or directory_changed:
        # Renaming the root changes ctime; removing known children changes the
        # containing directory's times/size. Its identity and permissions remain.
        if directory_changed:
            return current[:3] == entry.stamp[:3]
        return current[:5] == entry.stamp[:5]
    return current == entry.stamp


def finish_move(engine, job, dest_fd, item, index):
    job.phase, job.current_name = 'Verifying move before removing original', item.source.name
    engine._check_destination(job)
    destination_stamps = _verify_destination(job, dest_fd, item)
    root_entry = item.entries[0]
    with directory_fd(item.source.parent.resolve(strict=True), item.parent_id) as source_fd:
        if not item.quarantine_name:
            # Validate the complete source while it is still at its visible name.
            current = engine._scan(job, source_fd, item.source.name)
            if [(e.relative, e.stamp, e.link) for e in current] != [
                    (e.relative, e.stamp, e.link) for e in item.entries]:
                raise RestartRequired('The source changed after copying. Its verified copy and original were kept.')
            item.quarantine_name = f'.omarchy-move-{job.id}-{index}'
            item.quarantining = True
            job.persist()

        if item.quarantining:
            try:
                held = entry_stat(source_fd, item.quarantine_name)
            except FileNotFoundError:
                held = None
            if held is None:
                if signature(entry_stat(source_fd, item.source.name)) != root_entry.stamp:
                    raise RestartRequired('The source changed before removal. Its original was kept.')
                job.checkpoint()
                rename_noreplace(source_fd, item.source.name, source_fd, item.quarantine_name)
                held = entry_stat(source_fd, item.quarantine_name)
            if identity(held) != root_entry.identity:
                raise RestartRequired('The original changed during the move. Inspect its source folder; nothing else was deleted.')
            try:
                visible = entry_stat(source_fd, item.source.name)
            except FileNotFoundError:
                visible = None
            if visible is not None and identity(visible) == root_entry.identity:
                raise RestartRequired('Both original names still exist. The held entry cannot be confirmed as our rename; both were kept.')
            item.quarantine_id = identity(held)
            item.quarantining = False
            engine._sync_directory(source_fd)
            job.persist()

        removed = set(item.removed)
        # Reconcile only an explicitly journaled in-flight unlink. Other missing
        # entries remain a failure, never evidence that our cleanup succeeded.
        if item.removing is not None:
            relative = Path(item.quarantine_name).joinpath(*item.removing.parts[1:])
            try:
                with relative_parent(source_fd, relative) as (parent, name):
                    entry_stat(parent, name)
            except FileNotFoundError:
                removed.add(item.removing)
                item.removed.append(item.removing)
            item.removing = None
            job.persist()

        if root_entry.relative in removed:
            return
        if identity(entry_stat(source_fd, item.quarantine_name)) != item.quarantine_id:
            raise RestartRequired('The held original was replaced. It was left untouched.')

        # Validate every remaining node and directory membership before deletion.
        # No recursive rmtree: it could erase newly added or replaced files.
        source_owned = {_relative(entry, item.quarantine_name): entry.identity for entry in item.entries}
        children = {}
        changed_directories = {relative.parent for relative in removed}
        for entry in item.entries[1:]:
            if entry.relative not in removed:
                children.setdefault(entry.relative.parent, set()).add(entry.relative.name)
        for entry in item.entries:
            if entry.relative in removed:
                continue
            relative = _relative(entry, item.quarantine_name)
            with relative_parent(source_fd, relative, source_owned) as (parent, name):
                info = entry_stat(parent, name)
                changed_directory = stat.S_ISDIR(entry.stamp[2]) and entry.relative in changed_directories
                if not _same_source(info, entry, root=entry is root_entry,
                                    directory_changed=changed_directory):
                    raise RestartRequired(f'The held original changed. It remains at {item.source.parent / item.quarantine_name}.')
                if stat.S_ISDIR(info.st_mode):
                    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                    try:
                        expected = children.get(entry.relative, set())
                        if set(os.listdir(fd)) != expected:
                            raise RestartRequired('New files appeared in the held original. They were kept.')
                    finally:
                        os.close(fd)

        job.phase = 'Removing verified original'
        for entry in reversed(item.entries):
            if entry.relative in removed:
                continue
            job.checkpoint()
            engine._check_destination(job)
            with relative_parent(dest_fd, _relative(entry, item.target_name)) as (parent, name):
                if signature(entry_stat(parent, name)) != destination_stamps[entry.relative]:
                    raise RestartRequired('The destination changed during the move. Remaining originals were kept.')
            relative = _relative(entry, item.quarantine_name)
            with relative_parent(source_fd, relative, source_owned) as (parent, name):
                info = entry_stat(parent, name)
                if not _same_source(info, entry, root=entry is root_entry,
                                    directory_changed=stat.S_ISDIR(entry.stamp[2])):
                    raise RestartRequired('The original changed during removal. Remaining originals were kept.')
                item.removing = entry.relative
                job.persist()
                # Recheck after the journal write; never unlink a replaced node.
                if signature(entry_stat(parent, name)) != signature(info):
                    raise RestartRequired('The original changed during removal. It was kept.')
                (os.rmdir if stat.S_ISDIR(info.st_mode) else os.unlink)(name, dir_fd=parent)
                engine._sync_directory(parent)
            removed.add(entry.relative)
            item.removed.append(entry.relative)
            item.removing = None
            job.persist()


def retain_original(engine, job, item, index):
    """Abandon destructive cleanup and reveal any exact held original, deleting nothing.

    Persist the chosen visible name before renaming so a crash or lost rename
    acknowledgement can be reconciled without publishing a second copy.
    """
    if item.abandoned:
        return item.retained_source
    root = item.entries[0]
    with directory_fd(item.source.parent.resolve(strict=True), item.parent_id) as source_fd:
        def info_at(name):
            try:
                return entry_stat(source_fd, name)
            except FileNotFoundError:
                return None

        def finish(path):
            item.retained_source = path
            item.abandoned = True
            item.restoring = False
            job.persist()
            return path

        if root.relative in item.removed:
            return finish(None)
        if not item.quarantine_name:
            # The user can choose this after modifying/replacing the visible
            # original. Leave that data exactly as it is and stop cleanup.
            return finish(item.source if info_at(item.source.name) is not None else None)

        expected = item.quarantine_id or root.identity
        held = info_at(item.quarantine_name)
        if item.restoring:
            visible = info_at(item.restore_name)
            if held is None and visible is not None and identity(visible) == expected:
                engine._sync_directory(source_fd)
                return finish(item.source.with_name(item.restore_name))
        if held is None:
            if item.quarantining:
                visible = info_at(item.source.name)
                if visible is not None and identity(visible) == root.identity:
                    return finish(item.source)
            if item.removing == root.relative:
                # This is the explicitly journaled, interrupted final unlink.
                item.removed.append(root.relative)
                item.removing = None
                return finish(None)
            raise RestartRequired('The held original cannot be located. Its recovery record was kept.')
        if identity(held) != expected:
            raise RestartRequired('The held original was replaced. It and the recovery record were left untouched.')

        is_directory = stat.S_ISDIR(root.stamp[2])
        suffix = '' if is_directory else item.source.suffix
        stem = item.source.name[:-len(suffix)] if suffix else item.source.name
        number = 0
        name_limit = os.fpathconf(source_fd, 'PC_NAME_MAX')
        if name_limit < 1:
            name_limit = 255
        while True:
            if item.restoring:
                name = item.restore_name
            elif number == 0:
                name = item.source.name
            else:
                ending = f' (remaining {number}){suffix}'
                short_stem = stem
                while short_stem and len(os.fsencode(short_stem + ending)) > name_limit:
                    short_stem = short_stem[:-1]
                if not short_stem:
                    raise ValueError('Choose a shorter original name before keeping the remaining copy.')
                name = short_stem + ending
            if info_at(name) is not None:
                item.restoring = False
                number += 1
                continue
            item.restore_name, item.restoring = name, True
            job.persist()
            if identity(entry_stat(source_fd, item.quarantine_name)) != expected:
                raise RestartRequired('The held original changed. It was left untouched.')
            try:
                rename_noreplace(source_fd, item.quarantine_name, source_fd, name)
            except FileExistsError:
                # A racing visible entry is never overwritten.
                item.restoring = False
                number += 1
                continue
            except OSError:
                # A remote rename can commit while its acknowledgement is lost.
                visible = info_at(name)
                if (info_at(item.quarantine_name) is not None or visible is None or
                        identity(visible) != expected):
                    raise
            visible = info_at(name)
            if visible is None or identity(visible) != expected:
                raise RestartRequired('The retained original changed during restoration. Inspect its source folder; nothing was deleted.')
            engine._sync_directory(source_fd)
            return finish(item.source.with_name(name))
