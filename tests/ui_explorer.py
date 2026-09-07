"""Explorer chrome stays distinct from app-requested picker controls."""
import tempfile
from pathlib import Path
from unittest.mock import patch

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gdk, GLib
from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow, parse_args


def settle():
    loop = GLib.MainLoop()
    GLib.timeout_add(150, lambda: loop.quit() or False)
    loop.run()


with tempfile.TemporaryDirectory(prefix='picker-explorer-') as temp, patch.object(Path, 'home', return_value=Path(temp)):
    root = Path(temp)
    path = root / 'notes.txt'
    path.write_text('fixture')
    folder = root / 'folder'
    folder.mkdir()
    request, _ = parse_args(['--demo', str(root)])
    app = PickerApplication(request, None)
    app.register(None)
    window = PickerWindow(app, request, None)
    window.present()
    settle()
    try:
        assert request.explorer
        assert not window.footer.get_visible() and not window.footer.get_mapped()
        assert window.metadata_viewport.get_mapped()
        window.flow.select_child(window.children_by_path[path])
        with patch('gi.repository.Gio.AppInfo.launch_default_for_uri', return_value=True) as launch, \
             patch.object(window, '_finish') as finish:
            window._on_child_activated(window.flow, window.children_by_path[path])
            launch.assert_called_once_with(path.as_uri(), None)
            finish.assert_not_called()
            assert window.get_visible()
            window._on_key_pressed(None, Gdk.KEY_Escape, 0, Gdk.ModifierType(0))
            assert not window._selected_paths()
            finish.assert_not_called()
        window._on_child_activated(window.flow, window.children_by_path[folder])
        assert window.current_dir == folder
        window._go_back(None)
        assert window.current_dir == root
        print('PASS: explorer hides action bar, keeps preview, opens via default app, stays open, navigates folders')
    finally:
        window.destroy()
    for mode in ('open', 'save', 'save_files'):
        request = PickerRequest(mode=mode, current_folder=root, current_name='saved.txt', directory=mode == 'save_files')
        window = PickerWindow(app, request, None)
        window.present()
        settle()
        try:
            assert window.footer.get_visible() and window.footer.get_mapped()
            if mode == 'open':
                window.flow.select_child(window.children_by_path[path])
                with patch.object(window, '_finish') as finish, \
                     patch('gi.repository.Gio.AppInfo.launch_default_for_uri') as launch:
                    window._accept()
                    finish.assert_called_once_with(paths=[path])
                    launch.assert_not_called()
            print('PASS:', mode, 'picker retains footer controls')
        finally:
            window.destroy()
