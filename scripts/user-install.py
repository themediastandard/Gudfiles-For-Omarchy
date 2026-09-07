#!/usr/bin/python
"""Development-only user install/removal; public installs use the Arch package."""
import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from omarchy_file_picker.launcher import doctor
from omarchy_file_picker.portal_setup import atomic_write, configure


def managed_files(home):
    return [home / f'.local/bin/{name}' for name in
            ('gudfiles', 'omarchy-file-picker', 'omarchy-file-picker-portal')] + [
        home / '.local/share/applications/org.omarchy.FilePicker.desktop',
        home / '.local/share/dbus-1/services/org.freedesktop.impl.portal.desktop.omarchy.FilePicker.service',
        home / '.local/share/xdg-desktop-portal/portals/omarchy-file-picker.portal',
        home / '.config/systemd/user/omarchy-file-picker-portal.service',
    ]


def change_install(home, *, remove=False):
    home = Path(home)
    app = home / '.local/share/omarchy-file-picker'
    code = app / 'omarchy_file_picker'
    files = managed_files(home) + [app / 'LICENSE']
    for path in [app, code, *files]:
        if path.is_symlink():
            raise RuntimeError(f'Refusing to replace a symbolic link: {path}')
    backup = home / '.local/state/gudfiles/install-backups'
    backup.mkdir(parents=True, exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix=datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-'), dir=backup))
    for path in files:
        if path.is_file():
            target = backup / path.relative_to(home)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    if code.exists():
        shutil.copytree(code, backup / 'omarchy_file_picker')
    routing = home / '.config/xdg-desktop-portal/hyprland-portals.conf'
    if remove:
        if (home / '.config/omarchy-file-picker/portal-backup.json').exists():
            configure(enable=False, home=home)
        elif routing.exists() and routing.read_text() == (ROOT / 'data/hyprland-portals.conf').read_text():
            legacy = home / '.config/omarchy/backups/omarchy-file-picker'
            choices = sorted(legacy.glob('hyprland-portals.conf.*'), key=lambda p: p.stat().st_mtime, reverse=True)
            if choices:
                atomic_write(routing, choices[0].read_text())
            else:
                routing.unlink()
        elif routing.exists() and 'omarchy-file-picker' in routing.read_text():
            raise RuntimeError('Portal routing has changed since installation. Restore its FileChooser preference before removing Gudfiles; your app and backup are intact.')
        if code.exists():
            shutil.rmtree(code)
        for path in files:
            path.unlink(missing_ok=True)
        # APP_DIR contains ratings.sqlite3 (and possibly WAL/SHM files). Keep it.
    else:
        app.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.install-', dir=app) as stage:
            staged = Path(stage) / 'omarchy_file_picker'
            shutil.copytree(ROOT / 'omarchy_file_picker', staged,
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'))
            if code.exists():
                code.rename(Path(stage) / 'previous')
            staged.rename(code)
        atomic_write(app / 'LICENSE', (ROOT / 'LICENSE').read_text())
        for name in ('gudfiles', 'omarchy-file-picker', 'omarchy-file-picker-portal'):
            target = home / f'.local/bin/{name}'
            replacement = str(app).replace('\\', '\\\\').replace('"', '\\"').replace('$', '\\$').replace('`', '\\`')
            atomic_write(target, (ROOT / f'bin/{name}').read_text().replace('@APP_DIR@', replacement))
            target.chmod(0o755)
        for name, target in (
            ('org.omarchy.FilePicker.desktop', files[3]),
            ('org.freedesktop.impl.portal.desktop.omarchy.FilePicker.service', files[4]),
            ('omarchy-file-picker.portal', files[5]),
            ('omarchy-file-picker-portal.service', files[6]),
        ):
            binary = str(home / '.local/bin').replace('\\', '\\\\').replace('"', '\\"')
            content = (ROOT / f'data/{name}').read_text()
            content = content.replace('@BIN_DIR@/omarchy-file-picker-portal', f'"{binary}/omarchy-file-picker-portal"')
            atomic_write(target, content)
    return backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--remove', action='store_true')
    args = parser.parse_args()
    if os.geteuid() == 0:
        parser.error('Run as your normal user, without sudo.')
    if not args.remove and Path('/usr/lib/gudfiles').exists():
        parser.error('A system package is installed. Update it with Omarchy Update instead.')
    for process in Path('/proc').glob('[0-9]*'):
        try:
            if process.stat().st_uid != os.getuid():
                continue
            command = (process / 'cmdline').read_bytes().split(b'\0')
            if b'-m' in command and any(value in command for value in
                                       (b'omarchy_file_picker.picker', b'omarchy_file_picker.launcher')):
                parser.error('Finish transfers and close Gudfiles before installing or removing it.')
        except (OSError, ProcessLookupError):
            continue
    if not args.remove and doctor():
        return 1
    backup = change_install(Path.home(), remove=args.remove)
    print(f'{"Removed" if args.remove else "Installed"} user-local Gudfiles. Ratings, preferences and bookmarks are preserved.\nBackup: {backup}')
    print('Finish your work, then log out and back in to refresh the launcher and portal services.')
    if not args.remove:
        print('Optional Open/Save integration: ~/.local/bin/gudfiles --enable-portal')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
