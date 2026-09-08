"""Extract ZIPs into a new sibling folder, publishing only complete contents."""
import ntpath
from pathlib import Path
import shutil
import stat
import tempfile
import zipfile

from .batch_rename import _rename_no_replace

MAX_ENTRIES = 100_000


def _member_path(info):
    name = info.orig_filename
    parts = name.rstrip('/').split('/')
    if (not name or '\0' in name or '\\' in name or name.startswith('/') or
            ntpath.splitdrive(name)[0] or '..' in parts):
        raise ValueError(f'Unsafe ZIP path: {name!r}')
    parts = [part for part in parts if part and part != '.']
    if not parts:
        if info.is_dir():
            return None
        raise ValueError(f'Invalid ZIP filename: {name!r}')
    mode = info.external_attr >> 16 if info.create_system == 3 else 0
    kind = stat.S_IFMT(mode)
    if kind not in (0, stat.S_IFREG, stat.S_IFDIR):
        raise ValueError(f'ZIP links and special files are not supported: {name}')
    if info.flag_bits & 1:
        raise ValueError('Password-protected ZIP files are not supported.')
    return Path(*parts)


def extract_zip(source: Path) -> Path:
    """Keep the archive and existing destinations intact, including on failure."""
    source = Path(source).absolute()
    stem = source.stem if source.suffix else source.name
    if stem in ('', '.', '..'):
        stem = 'Archive'
    with zipfile.ZipFile(source) as archive:
        members = archive.infolist()
        if len(members) > MAX_ENTRIES:
            raise ValueError(f'This ZIP exceeds the {MAX_ENTRIES:,}-entry limit.')
        planned = [(info, _member_path(info)) for info in members]
        with tempfile.TemporaryDirectory(prefix='.gudfiles-extract-', dir=source.parent) as temp:
            staged = Path(temp) / 'contents'
            staged.mkdir()
            for info, relative in planned:
                if relative is None:
                    continue
                target = staged / relative
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    # Exclusive creation also rejects duplicate/conflicting ZIP
                    # entries. No archive-provided symlinks are ever created.
                    with archive.open(info) as reader, target.open('xb') as writer:
                        shutil.copyfileobj(reader, writer, length=1024 * 1024)
            number = 0
            while True:
                name = stem if number == 0 else f'{stem} ({number})'
                destination = source.with_name(name)
                try:
                    _rename_no_replace(staged, destination)
                    return destination
                except FileExistsError:
                    number += 1
