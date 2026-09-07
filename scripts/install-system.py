#!/usr/bin/python
"""Stage package-owned files only. Never edit a user's home or restart services."""
import argparse
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]


def install(destdir):
    destdir = Path(destdir).resolve()
    if destdir == Path('/'):
        raise ValueError('A staging directory is required; install the built package with pacman.')

    def copy(source, target, executable=False, replacements=()):
        source = ROOT / source
        target = destdir / target
        target.parent.mkdir(parents=True, exist_ok=True)
        if replacements:
            content = source.read_text()
            for old, new in replacements:
                content = content.replace(old, new)
            target.write_text(content)
        else:
            shutil.copyfile(source, target)
        target.chmod(0o755 if executable else 0o644)

    for path in sorted((ROOT / 'omarchy_file_picker').rglob('*')):
        if path.is_file() and path.suffix in ('.py', '.json', '.wav') and '__pycache__' not in path.parts:
            if path.is_symlink():
                raise ValueError(f'Refusing symlink: {path}')
            copy(path.relative_to(ROOT), f'usr/lib/gudfiles/{path.relative_to(ROOT)}')
    copy('LICENSE', 'usr/lib/gudfiles/LICENSE')
    copy('LICENSE', 'usr/share/licenses/gudfiles/LICENSE')
    copy('docs/INSTALL.md', 'usr/share/doc/gudfiles/INSTALL.md')
    for name in ('gudfiles', 'omarchy-file-picker', 'omarchy-file-picker-portal'):
        copy(f'bin/{name}', f'usr/bin/{name}', executable=True,
             replacements=(('@APP_DIR@', '/usr/lib/gudfiles'),))
    for source, target in (
        ('org.omarchy.FilePicker.desktop', 'applications/org.omarchy.FilePicker.desktop'),
        ('omarchy-file-picker.portal', 'xdg-desktop-portal/portals/omarchy-file-picker.portal'),
        ('org.freedesktop.impl.portal.desktop.omarchy.FilePicker.service',
         'dbus-1/services/org.freedesktop.impl.portal.desktop.omarchy.FilePicker.service'),
    ):
        copy(f'data/{source}', f'usr/share/{target}', replacements=(('@BIN_DIR@', '/usr/bin'),))
    copy('data/omarchy-file-picker-portal.service', 'usr/lib/systemd/user/omarchy-file-picker-portal.service',
         replacements=(('@BIN_DIR@', '/usr/bin'),))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destdir', type=Path)
    install(parser.parse_args().destdir)
