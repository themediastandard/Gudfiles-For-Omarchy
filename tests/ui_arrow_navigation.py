"""Real spatial arrows and Quick Look keys on a disposable Xvfb + xdotool display.

Use POINTER_QA_ISOLATED=1 and GDK_BACKEND=x11, as in ui_list_navigation.py.
"""
import os
import subprocess
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import gi
gi.require_version('GdkX11', '4.0')
from omarchy_file_picker.picker import PickerApplication, PickerWindow
from omarchy_file_picker.model import PickerRequest
from gi.repository import Gio, GLib, Gtk, GdkX11


def settle(ms=120):
    loop = GLib.MainLoop()
    GLib.timeout_add(ms, lambda: loop.quit() or False)
    loop.run()


def until(predicate):
    deadline = time.monotonic() + 5
    while not predicate() and time.monotonic() < deadline:
        settle()
    assert predicate(), 'GTK condition timed out'


assert os.environ.get('POINTER_QA_ISOLATED') == '1', 'Use a disposable Xvfb display.'
with tempfile.TemporaryDirectory(prefix='gudfiles-arrows-') as temp, \
        patch.object(Path, 'home', return_value=Path(temp)), \
        patch.object(Gio.VolumeMonitor, 'get_mounts', return_value=[]):
    root = Path(temp)
    folder = root / 'Folder'
    folder.mkdir()
    for name in ('a.txt', 'b.txt', 'c.txt'):
        (folder / name).write_text(name)
    files = [root / f'{i:02}-notes.txt' for i in range(60)]
    for index, path in enumerate(files):
        path.write_text('Keyboard preview fixture\n' * 50)
        os.utime(path, (100 + index, 100 + index))
    entries = [folder, *files]
    request = PickerRequest(current_folder=root, explorer=True, multiple=True)
    app = PickerApplication(request, None)
    app.register(None)
    window = PickerWindow(app, request, None)
    window.present()
    settle()
    xid = window.get_surface().get_xid()

    def send(*args):
        subprocess.run([os.environ.get('XDOTOOL', 'xdotool'), *map(str, args)], check=True)
        settle()

    def click(widget):
        if isinstance(widget, Gtk.FlowBoxChild):
            valid, bounds = widget.compute_bounds(window.file_scroller)
            assert valid
            adjustment = window.file_scroller.get_vadjustment()
            top = adjustment.get_value() + bounds.get_y()
            adjustment.clamp_page(top, top + bounds.get_height())
            settle(300)  # finish GTK's scroll animation before physical input
        valid, bounds = widget.compute_bounds(window)
        assert valid
        dx, dy = window.get_surface_transform()
        send('mousemove', '--window', xid, round(bounds.get_x() + bounds.get_width() / 2 + dx),
             round(bounds.get_y() + bounds.get_height() / 2 + dy))
        send('click', 1)

    def selected(*paths):
        assert window._selected_paths() == list(paths), window._selected_paths()

    try:
        send('windowfocus', xid)
        for mode in ('grid', 'list', 'columns'):
            window.navigate(root)
            window._set_view('list' if mode == 'grid' else 'grid')
            settle()
            click(window.children_by_path[entries[8]])
            click(getattr(window, mode + '_button'))
            width = sum(child.get_allocation().y == window.flow.get_first_child().get_allocation().y
                        for child in window.children_by_path.values()) if mode == 'grid' else 1
            send('key', 'Down'); selected(entries[8 + width])
            send('key', 'Up'); selected(entries[8])
            if mode == 'grid':
                assert width > 1
                send('key', 'Right'); selected(entries[9])
                send('key', 'Left'); selected(entries[8])
            send('key', 'shift+Down')
            selected(*entries[8:9 + width])
            send('key', 'shift+Up'); selected(entries[8])
            send('key', 'ctrl+Down'); selected(entries[8])
            assert window.get_focus()._picker_path == entries[8 + width]
            send('key', 'Up'); selected(entries[8])
            # Sorting returns focus to its button. The next arrow still moves
            # immediately, while arrows inside the open menu only navigate it.
            click(window.sort_button)
            before = window._selected_paths()
            send('key', 'Down')
            assert window._selected_paths() == before and window.sort_popover.get_visible()
            send('key', 'Escape')
            selected(entries[8])
            send('key', 'Down'); selected(entries[8 + width])
            # Full-row scrolling and lower boundaries remain in the files.
            send('key', '--repeat', 65, '--delay', 8, 'Down')
            settle(250)
            child = window.get_focus()
            valid, bounds = child.compute_bounds(window.file_scroller)
            assert valid and bounds.get_y() >= 0
            assert bounds.get_y() + bounds.get_height() <= window.file_scroller.get_height() + 1
            before = window._selected_paths()
            send('key', 'Down')
            assert window._selected_paths() == before
            window._open_search()
            send('key', 'Up', 'Down')
            assert window._selected_paths() == before
            send('key', 'Escape')
            # File previews accept vertical and horizontal next/previous keys
            # in the current sorted order, including after closing the overlay.
            window._set_sort('modified', True)
            window.file_scroller.get_vadjustment().set_value(0)
            settle()
            click(window.children_by_path[files[-1]])
            send('key', 'space')
            until(lambda: window.quicklook.kind == 'text' and window.quicklook.progress == 1)
            for key, expected in (('Down', files[-2]), ('Up', files[-1]),
                                  ('Right', files[-2]), ('Left', files[-1]),
                                  ('Up', files[-1])):
                send('key', key)
                assert window.quicklook.path == expected, (mode, key, window.quicklook.path)
                selected(expected)
            send('key', 'Down')
            send('key', 'Escape')
            until(lambda: not window.quicklook.get_visible())
            selected(files[-2])
            send('key', 'Down')
            selected(files[-2 - width])
            window._set_sort('name', False)
            print('PASS', mode, 'real spatial arrows, handoff, Shift/Ctrl, menu/search safety, '
                  'scroll/edges, sorted preview Up/Down/Left/Right and close handoff', flush=True)
        # Right enters a folder; vertical arrows stay in that column; Left
        # returns to the parent with its original folder selected.
        window.navigate(root)
        window._set_view('columns')
        window.file_scroller.get_vadjustment().set_value(0)
        settle()
        click(window.children_by_path[folder])
        send('key', 'Right')
        until(lambda: window.current_dir == folder)
        selected(folder / 'a.txt')
        send('key', 'Down'); selected(folder / 'b.txt')
        send('key', 'Up'); selected(folder / 'a.txt')
        send('key', 'space')
        until(lambda: window.quicklook.kind == 'text' and window.quicklook.progress == 1)
        send('key', 'Down')
        assert window.quicklook.path == folder / 'b.txt'
        send('key', 'Escape')
        until(lambda: not window.quicklook.get_visible())
        assert window.current_dir == folder
        selected(folder / 'b.txt')
        send('key', 'Down'); selected(folder / 'c.txt')
        send('key', 'Left')
        until(lambda: window.current_dir == root)
        selected(folder)
        send('key', 'Down'); selected(files[0])
        print('PASS column parent/child transitions and immediate vertical navigation', flush=True)
    finally:
        window.destroy()
        settle()
