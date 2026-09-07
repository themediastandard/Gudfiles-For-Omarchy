"""Explicit per-user FileChooser opt-in, preserving other portal preferences."""
import configparser
import io
import json
import os
from pathlib import Path
import tempfile

BACKEND = 'omarchy-file-picker;gtk'


def atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=f'.{path.name}.')
    try:
        with os.fdopen(descriptor, 'w') as stream:
            stream.write(content)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def configure(*, enable, home=None):
    if home is None and os.geteuid() == 0:
        raise RuntimeError('Run Gudfiles portal setup as your normal user, without sudo.')
    # Existing Gudfiles storage deliberately uses these compatibility paths.
    home = Path.home() if home is None else Path(home)
    path = home / '.config/xdg-desktop-portal/hyprland-portals.conf'
    state = home / '.config/omarchy-file-picker/portal-backup.json'
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    original = path.read_text() if path.exists() else ''
    try:
        parser.read_string(original)
    except configparser.Error as error:
        raise RuntimeError('Portal configuration could not be read; no settings were changed.') from error
    if not parser.has_section('preferred'):
        parser.add_section('preferred')
    key = 'org.freedesktop.impl.portal.FileChooser'
    current = parser.get('preferred', key, fallback=None)
    if enable:
        if current == BACKEND:
            return 'Gudfiles is already the FileChooser. Log out and back in if needed.'
        if state.exists():
            raise RuntimeError('A previous portal backup exists. Disable Gudfiles portal routing before enabling it again.')
        atomic_write(state, json.dumps({'previous': current, 'original': original, 'existed': path.exists()}))
        parser.set('preferred', key, BACKEND)
    else:
        if current != BACKEND:
            # Keep another app/user\'s edits, and retain any backup for inspection.
            return 'Gudfiles is not the selected FileChooser. Portal settings were left as they are.'
        if not state.exists():
            raise RuntimeError('No setup backup was found. Use the original user installer\'s uninstall.sh to restore legacy routing.')
        try:
            backup = json.loads(state.read_text())
            previous = backup['previous']
            if previous is not None and not isinstance(previous, str):
                raise ValueError('Invalid backup')
        except (ValueError, KeyError, TypeError) as error:
            raise RuntimeError('Portal backup could not be read; no settings were changed.') from error
        if previous is None:
            parser.remove_option('preferred', key)
        else:
            parser.set('preferred', key, previous)
        # Only change the FileChooser preference; keep later edits to other keys.
    output = io.StringIO()
    parser.write(output, space_around_delimiters=False)
    atomic_write(path, output.getvalue())
    if not enable:
        state.unlink()
    return ('Gudfiles FileChooser enabled.' if enable else 'Previous FileChooser restored.') + ' Log out and back in after finishing your work to apply the change.'
