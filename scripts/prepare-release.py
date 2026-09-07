#!/usr/bin/python
"""Build a deterministic, allowlisted release archive and pinned AUR recipe."""
import argparse
import gzip
import hashlib
import io
from pathlib import Path
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from omarchy_file_picker import __version__
from omarchy_file_picker.updates import repository, version_tuple


def prepare(output, *, build_package=False):
    version_tuple(__version__)
    repo = repository()
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    name = f'gudfiles-{__version__}'
    files = [ROOT / value for value in ('LICENSE', 'docs/INSTALL.md', 'scripts/install-system.py')]
    files += sorted((ROOT / 'bin').glob('*'))
    files += sorted((ROOT / 'data').glob('*'))
    files += sorted(path for path in (ROOT / 'omarchy_file_picker').rglob('*')
                    if path.is_file() and path.suffix in ('.py', '.json', '.wav')
                    and '__pycache__' not in path.parts)
    archive = output / f'{name}.tar.gz'
    # Normalized ordering, modes, timestamps and ownership make the archive
    # independent of local file metadata. Never include Git history or user data.
    with archive.open('wb') as stream, gzip.GzipFile(filename='', mode='wb', fileobj=stream, mtime=0) as zipped:
        with tarfile.open(fileobj=zipped, mode='w', format=tarfile.PAX_FORMAT) as tar:
            for source in sorted(files):
                if source.is_symlink() or not source.is_file():
                    raise ValueError(f'Expected a regular release file: {source}')
                relative = source.relative_to(ROOT)
                info = tarfile.TarInfo(f'{name}/{relative}')
                data = source.read_bytes()
                info.size = len(data)
                info.mode = 0o755 if relative.parts[0] == 'bin' else 0o644
                tar.addfile(info, io.BytesIO(data))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    recipe = (ROOT / 'packaging/PKGBUILD.in').read_text()
    for token, value in (('@VERSION@', __version__), ('@REPOSITORY@', repo), ('@SHA256@', digest)):
        recipe = recipe.replace(token, value)
    (output / 'PKGBUILD').write_text(recipe)
    result = subprocess.run(['makepkg', '--printsrcinfo'], cwd=output, check=True, text=True, capture_output=True)
    (output / '.SRCINFO').write_text(result.stdout)
    (output / 'RELEASE-NOTES.md').write_text((ROOT / f'releases/{__version__}.md').read_text())
    artifacts = [archive]
    if build_package:
        subprocess.run(['makepkg', '--cleanbuild', '--force', '--noconfirm'], cwd=output, check=True)
        package = output / f'{name}-1-any.pkg.tar.zst'
        if not package.is_file():
            raise RuntimeError('Expected a .pkg.tar.zst package; check PKGEXT in makepkg.conf.')
        artifacts.append(package)
    (output / 'SHA256SUMS').write_text(''.join(
        f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n' for path in artifacts))
    print(f'Prepared {archive}\nSHA-256: {digest}\nRelease repository: {repo}\nNothing has been published.')
    return archive


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist' / __version__)
    parser.add_argument('--build-package', action='store_true', help='Also run makepkg without installing anything')
    args = parser.parse_args()
    prepare(args.output, build_package=args.build_package)
