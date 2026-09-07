"""Filesystem operations used by explicit chooser actions."""
from pathlib import Path
import os
import shutil
from urllib.parse import unquote, urlparse

from gi.repository import Gio


def create_untitled_text(directory: Path) -> Path:
    """Atomically create an empty file without replacing any existing entry."""
    number = 0
    while True:
        name = 'untitled.txt' if number == 0 else f'untitled ({number}).txt'
        target = directory / name
        try:
            with target.open('x'):
                pass
            return target
        except FileExistsError:
            number += 1


def validate_name(name: str) -> str:
    name = name.strip()
    if not name or name in {'.', '..'} or '/' in name or '\0' in name:
        raise ValueError('Enter a name without slashes.')
    return name


def rename_item(source: Path, name: str) -> Path:
    target = source.with_name(validate_name(name))
    if source == target:
        return source
    Gio.File.new_for_path(str(source)).move(
        Gio.File.new_for_path(str(target)), Gio.FileCopyFlags.NOFOLLOW_SYMLINKS,
        None, None, None,
    )
    return target


def transfer_items(sources: list[Path], directory: Path, cut: bool = False, *, moved=None) -> list[Path]:
    """Refuse overwrites and self/descendant copies; retain source on copy failure."""
    targets = [directory / source.name for source in sources]
    if len(set(targets)) != len(targets):
        raise ValueError('Two selected files have the same name. Paste them separately.')
    for source, target in zip(sources, targets):
        if os.path.lexists(target):
            raise FileExistsError(f'{target.name} already exists in the destination.')
        if source.is_dir() and not source.is_symlink():
            if source.resolve() == directory.resolve() or source.resolve() in directory.resolve().parents:
                raise ValueError('A folder cannot be pasted inside itself.')
    completed = []
    for source, target in zip(sources, targets):
        if cut:
            Gio.File.new_for_path(str(source)).move(
                Gio.File.new_for_path(str(target)), Gio.FileCopyFlags.NOFOLLOW_SYMLINKS,
                None, None, None,
            )
        elif source.is_dir() and not source.is_symlink():
            shutil.copytree(source, target, symlinks=True)
        else:
            Gio.File.new_for_path(str(source)).copy(
                Gio.File.new_for_path(str(target)), Gio.FileCopyFlags.NOFOLLOW_SYMLINKS,
                None, None, None,
            )
        completed.append(target)
        if cut and moved is not None:
            moved(source, target)
    return completed


def remove_items(paths: list[Path], permanent: bool = False) -> list[Path]:
    for path in paths:
        if not path.name or path == Path.home():
            raise ValueError('This location cannot be removed from the picker.')
        if not permanent:
            Gio.File.new_for_path(str(path)).trash(None)
        elif path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
    return []


def parse_file_clipboard(text: str, mime: str) -> tuple[list[Path], bool]:
    lines = text.splitlines()
    cut = mime == 'x-special/gnome-copied-files' and bool(lines) and lines[0] == 'cut'
    paths = []
    for line in lines:
        uri = urlparse(line)
        if uri.scheme == 'file' and uri.netloc in {'', 'localhost'}:
            path = Path(unquote(uri.path))
            if path not in paths:
                paths.append(path)
    return paths, cut


def sort_entries(entries: list[Path], key: str, descending: bool, folders_first: bool) -> list[Path]:
    def value(path):
        try:
            if key == 'modified': return path.stat().st_mtime
            if key == 'size': return path.stat().st_size
            if key == 'type': return path.suffix.casefold()
        except OSError:
            return 0 if key in {'modified', 'size'} else ''
        return path.name.casefold()
    ordered = sorted(entries, key=lambda p: p.name.casefold())
    ordered.sort(key=value, reverse=descending)
    if folders_first:
        ordered.sort(key=lambda p: not p.is_dir())
    return ordered
