"""Mounted-location navigation; optional read-only live NAS check, no mounting."""
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import GLib
from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow


def settle():
    loop = GLib.MainLoop()
    GLib.timeout_add(100, lambda: loop.quit() or False)
    loop.run()


def until(condition):
    deadline = time.monotonic() + 8
    while not condition() and time.monotonic() < deadline:
        settle()
    assert condition(), 'Timed out waiting for mounted navigation'


with tempfile.TemporaryDirectory(prefix='picker-mount-') as temp:
    root = Path(temp)
    share = root / 'share'
    nested = share / 'folder'
    nested.mkdir(parents=True)
    request = PickerRequest(current_folder=root)
    app = PickerApplication(request, None)
    app.register(None)
    window = PickerWindow(app, request, None)
    errors = []
    window._show_error = lambda *args: errors.append(args)
    window.present()
    window._set_view('list')
    settle()
    try:
        with patch('omarchy_file_picker.picker.mounted_local_path', return_value=share):
            window._open_mounted_location('smb://example.local/share')
            until(lambda: window.current_dir == share)
        window.flow.emit('child-activated', window.children_by_path[nested])
        assert window.current_dir == nested
        with patch('omarchy_file_picker.picker.mounted_local_path', side_effect=RuntimeError('Unavailable')):
            window._open_mounted_location('smb://example.local/share')
            until(lambda: bool(errors))
        assert errors.pop() == ('Could not open mounted folder', 'Unavailable')
        assert window.current_dir == nested
        print('PASS: mounted navigation, folder activation and visible failure')
        if os.environ.get('PICKER_QA_LIVE_MOUNT') == '1':
            mount = next(m for m in window.volume_monitor.get_mounts()
                         if m.get_root().get_uri().startswith(('smb://', 'nfs://')))
            mounted = Path(mount.get_root().get_path())
            button = next(b for b in window.location_buttons if getattr(b, '_picker_path', None) == mounted)
            button.emit('clicked')
            until(lambda: window.current_dir == mounted)
            folder = next((p for p in window.entries if p.is_dir()), None)
            assert folder, 'No subfolder available to verify activation'
            window.flow.emit('child-activated', window.children_by_path[folder])
            settle()
            assert window.current_dir == folder
            window._go_back(None)
            assert window.current_dir == mounted
            assert not errors, errors
            print('PASS: live NAS sidebar activation, subfolder activation and Back (read-only)')
    finally:
        window.destroy()
