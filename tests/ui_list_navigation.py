"""Real list arrow-key regression on a disposable Xvfb display + xdotool.

Set POINTER_QA_ISOLATED=1, GDK_BACKEND=x11 and XDOTOOL as in ui_pointer_drag.py.
The fixture isolates preferences, devices and files; no desktop input is sent.
"""
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

import gi
gi.require_version('GdkX11', '4.0')
from omarchy_file_picker.picker import PickerApplication, PickerWindow
from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.list_navigation import navigate_files
from gi.repository import Gdk, Gio, GLib, Gtk, GdkX11


def settle():
    loop = GLib.MainLoop()
    GLib.timeout_add(120, lambda: loop.quit() or False)
    loop.run()


assert os.environ.get('POINTER_QA_ISOLATED') == '1', 'Use a disposable Xvfb display.'
with tempfile.TemporaryDirectory(prefix='list-keys-') as temp, \
        patch.object(Path, 'home', return_value=Path(temp)), \
        patch.object(Gio.VolumeMonitor, 'get_mounts', return_value=[]):
    root = Path(temp)
    folders = [root / f'Folder {i:02}' for i in range(70)]
    for path in folders:
        path.mkdir()
    note = root / 'Note.txt'
    note.write_text('Read-only keyboard fixture')
    app = PickerApplication(PickerRequest(current_folder=root), None)
    app.register(None)
    for multiple, directory, mode in [(True, False, 'open'), (False, True, 'open'), (False, False, 'save')]:
        window = PickerWindow(app, PickerRequest(current_folder=root, multiple=multiple,
                              directory=directory, explorer=multiple, mode=mode), None)
        window.present()
        settle()
        xid = window.get_surface().get_xid()
        def send(*args):
            subprocess.run([os.environ.get('XDOTOOL', 'xdotool'), *map(str, args)], check=True)
            settle()
        def click(widget):
            ok, bounds = widget.compute_bounds(window)
            assert ok
            dx, dy = window.get_surface_transform()
            send('mousemove', '--window', xid, round(bounds.get_x() + bounds.get_width()/2 + dx),
                 round(bounds.get_y() + bounds.get_height()/2 + dy))
            send('click', 1)
        def selected(*indices):
            assert window._selected_paths() == [folders[i] for i in indices], window._selected_paths()
        try:
            send('windowfocus', xid)
            window._set_view('grid', persist=False)
            settle()
            click(window.list_button)
            send('key', 'Down'); selected(0)
            send('key', 'Up'); selected(0)
            assert isinstance(window.get_focus(), Gtk.FlowBoxChild)
            click(window.children_by_path[folders[4]])
            send('key', 'Down'); selected(5)
            send('key', 'Up'); selected(4)
            if multiple:
                send('key', 'shift+Down'); selected(4, 5)
                send('key', 'shift+Up'); selected(4)
                send('key', 'ctrl+Down'); selected(4)
                assert window.get_focus()._picker_path == folders[5]
                send('key', 'Up'); selected(4)
            # The old behavior spends this first arrow entering the list and
            # leaves row 8 selected. Direct child focus can also leave GTK's
            # private cursor invalid after these rows have been rebuilt.
            for key, expected in [('Down', 9), ('Up', 7)]:
                click(window.children_by_path[folders[8]])
                click(window.grid_button)
                click(window.list_button)
                selected(8)
                send('key', key); selected(expected)
            click(window.children_by_path[folders[8]])
            send('key', '--repeat', 60, '--delay', 12, 'Down')
            settle()  # allow GTK's focus-scroll animation to finish
            selected(68)
            assert window.file_scroller.get_vadjustment().get_value() > 0
            ok, bounds = window.children_by_path[folders[68]].compute_bounds(window.file_scroller)
            assert ok and bounds.get_y() >= 0
            assert bounds.get_y() + bounds.get_height() <= window.file_scroller.get_height() + 1, (bounds.get_y(), bounds.get_height(), window.file_scroller.get_height())
            assert window.current_dir == root  # arrows select; they do not open folders
            send('key', '--repeat', 5, 'Down')
            last = folders[-1] if directory else note
            assert window._selected_paths() == [last]
            assert window.get_focus()._picker_path == last
            window._open_search()
            before = window._selected_paths()
            assert not navigate_files(window, Gdk.KEY_Up, Gdk.ModifierType(0))
            send('key', 'Up')
            assert window._selected_paths() == before
            send('key', 'Escape')
            window.list_button.grab_focus()
            assert not navigate_files(window, Gdk.KEY_Up, Gdk.ModifierType.ALT_MASK)
            sidebar = window.location_buttons[0]
            sidebar.grab_focus()
            assert not navigate_files(window, Gdk.KEY_Down, Gdk.ModifierType(0))
            window.navigate(root)
            settle()
            click(window.list_button)
            send('key', 'Down')
            selected(0)
            send('key', 'Return')
            assert window.current_dir == folders[0]
            send('key', 'Up', 'Down')
            assert not window._selected_paths()
            print('PASS', multiple, directory, mode, 'real arrows, view handoff, range/cursor, edges, scrolling, entry safety, Enter and empty folder', flush=True)
        finally:
            window.destroy()
            settle()
