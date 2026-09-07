#!/usr/bin/python
"""Verify checksums and package boundaries without installing the package."""
import argparse
import hashlib
from pathlib import Path
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from omarchy_file_picker import __version__


def verify(directory):
    directory = Path(directory)
    expected = {f'gudfiles-{__version__}.tar.gz', f'gudfiles-{__version__}-1-any.pkg.tar.zst'}
    records = {}
    for line in (directory / 'SHA256SUMS').read_text().splitlines():
        digest, name = line.split('  ', 1)
        if name not in expected or name in records:
            raise ValueError(f'Unexpected or repeated asset: {name}')
        records[name] = digest
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f'Checksum mismatch: {name}')
    if records.keys() != expected:
        raise ValueError('Build both archive and package before release verification.')
    with tarfile.open(directory / f'gudfiles-{__version__}.tar.gz') as tar:
        paths = []
        for entry in tar:
            path = Path(entry.name)
            if not entry.isfile() or '..' in path.parts or path.parts[0] != f'gudfiles-{__version__}':
                raise ValueError(f'Unsafe archive entry: {path}')
            if path.suffix in ('.sqlite3', '.pyc') or path.name in ('PROJECT.md', 'preferences.json') or any(part in path.parts for part in ('.git', 'tests')):
                raise ValueError(f'Private/generated file in archive: {path}')
            paths.append(path)
        if not any(path.name == 'LICENSE' for path in paths):
            raise ValueError('Missing archive license')
    package = directory / f'gudfiles-{__version__}-1-any.pkg.tar.zst'
    listing = subprocess.check_output(['bsdtar', '-tf', str(package)], text=True).splitlines()
    for name in listing:
        path = Path(name)
        if path.is_absolute() or '..' in path.parts or not (name.startswith('usr/') or name in ('.PKGINFO', '.BUILDINFO', '.MTREE')):
            raise ValueError(f'Unexpected package path: {name}')
        if path.suffix in ('.sqlite3', '.pyc') or path.name in ('PROJECT.md', '.git', 'preferences.json'):
            raise ValueError(f'Private/generated file in package: {name}')
    for path in ('usr/bin/gudfiles', 'usr/lib/gudfiles/LICENSE', 'usr/share/licenses/gudfiles/LICENSE',
                 'usr/lib/gudfiles/omarchy_file_picker/release.json',
                 'usr/share/applications/org.omarchy.FilePicker.desktop'):
        if path not in listing:
            raise ValueError(f'Missing package file: {path}')
    info = subprocess.check_output(['bsdtar', '-xOf', str(package), '.PKGINFO'], text=True)
    for field in ('pkgname = gudfiles', f'pkgver = {__version__}-1', 'arch = any', 'license = LicenseRef-Gudfiles-Free-Use'):
        if field not in info.splitlines():
            raise ValueError(f'Missing package metadata: {field}')
    print('Verified release checksums, package metadata, license and user-data boundaries.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    verify(parser.parse_args().directory)
