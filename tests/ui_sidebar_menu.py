"""Native splitter, preference persistence and pointer/keyboard menu anchors."""
import json
import os
import subprocess
import tempfile
import traceback
from pathlib import Path
from unittest.mock import patch

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gdk, GLib, Gtk
from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow


def settle(delay=150):
    loop = GLib.MainLoop()
    GLib.timeout_add(delay, lambda: loop.quit() or False)
    loop.run()


class Gesture:
    def set_state(self, state):
        assert state == Gtk.EventSequenceState.CLAIMED


with tempfile.TemporaryDirectory(prefix='picker-sidebar-') as temp, patch.object(Path, 'home', return_value=Path(temp)):
    root = Path(temp)
    path = root / 'file.txt'
    path.write_text('fixture')
    request = PickerRequest(current_folder=root, multiple=True)
    app = PickerApplication(request, None)
    app.register(None)
    window = PickerWindow(app, request, None)
    window.present()
    settle()
    try:
        clients = json.loads(subprocess.check_output(['hyprctl', 'clients', '-j']))
        client = next(c for c in clients if c['pid'] == os.getpid() and c['class'] == 'org.omarchy.FilePicker')
        selector = json.dumps('address:' + client['address'])
        if not client['floating']:
            subprocess.run(['hyprctl', 'dispatch', 'hl.dsp.window.float({action="toggle",window=' + selector + '})'], check=True)
            settle(350)
        subprocess.run(['hyprctl', 'dispatch', 'hl.dsp.window.resize({x=1200,y=800,relative=false,window=' + selector + '})'], check=True)
        settle(550)
        assert isinstance(window.sidebar_split, Gtk.Paned)
        size = window.get_width(), window.get_height()
        window.flow.select_child(window.children_by_path[path])
        tiles = dict(window.children_by_path)
        for width in (180, 310, 240):
            window.sidebar_split.set_position(width)
            settle(550)
            assert abs(window.sidebar_split.get_position() - width) <= 1, (width, window.sidebar_split.get_position(), window.sidebar.measure(Gtk.Orientation.HORIZONTAL, -1))
            assert (window.get_width(), window.get_height()) == size
            assert window._selected_paths() == [path]
            assert window.children_by_path == tiles, 'Resizing must not reload files'
            assert json.loads(window.preferences_path.read_text())['sidebar_width'] == width
        print('PASS: native splitter widths and persistence', flush=True)
        for mode in ('grid', 'list'):
            window._set_view(mode)
            settle()
            child = window.children_by_path[path]
            valid, bounds = child.compute_bounds(window.browser_stack)
            assert valid
            x, y = bounds.get_x() + 12, bounds.get_y() + 12
            window._on_context_pressed(Gesture(), 1, x, y)
            valid, rect = window.context_popover.get_pointing_to()
            assert valid and (rect.x, rect.y) == (int(x), int(y))
            assert window.context_popover.get_parent() is window.browser_stack
            window._close_context_menu()
            settle()
            window.flow.grab_focus()
            window._on_key_pressed(None, Gdk.KEY_F10, 0, Gdk.ModifierType.SHIFT_MASK)
            valid, rect = window.context_popover.get_pointing_to()
            assert valid and (rect.x, rect.y) == (
                int(bounds.get_x() + bounds.get_width() / 2),
                int(bounds.get_y() + bounds.get_height() / 2))
            window._close_context_menu()
            settle()
            # Background keeps its coordinates too.
            window._show_context_menu(7, 9)
            valid, rect = window.context_popover.get_pointing_to()
            assert valid and (rect.x, rect.y) == (7, 9)
            window._close_context_menu()
            settle()
        restored = PickerWindow(app, request, None)
        assert restored.sidebar_split.get_position() == 240
        restored.present()
        settle()
        restored.destroy()
        print('PASS: sidebar resize, persisted width, stable window/selection, pointer anchors and keyboard row anchor')
    except Exception:
        traceback.print_exc()
        raise
    finally:
        window._close_context_menu()
        window.set_focus(None)
        window.set_visible(False)
        settle()
        window.destroy()
