"""Native popup ordering, including Wayland's exclusive popup-grab hierarchy.

GDK_BACKEND=wayland G_DEBUG=fatal-warnings PYTHONPATH=. python tests/ui_context_switching.py
No physical pointer/keyboard injection. ui_context_hover.py owns isolated X11 input.
"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gdk, Gio, GLib, Gtk

from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow
from omarchy_file_picker.theme import DEFAULT_COLORS, load_colors


errors = []
original_hook = sys.excepthook
def callback_error(kind, value, traceback):
    errors.append(value)
    original_hook(kind, value, traceback)
sys.excepthook = callback_error


def settle(ms=80):
    loop = GLib.MainLoop()
    GLib.timeout_add(ms, lambda: loop.quit() or False)
    loop.run()
    assert not errors, errors


def children(widget):
    child = widget.get_first_child()
    while child:
        yield child
        child = child.get_next_sibling()


with tempfile.TemporaryDirectory(prefix='gudfiles-popup-order-') as temporary:
    root = Path(temporary)
    text_file = root / 'Example.txt'
    text_file.write_text('fixture')
    image_file = root / 'Example.png'
    # Only the filename is needed to construct the media-action menu.
    image_file.touch()
    request = PickerRequest(current_folder=root, explorer=True, multiple=True)
    app = PickerApplication(request, None)
    app.register(None)
    for palette, colors in [('active', load_colors()), ('light', DEFAULT_COLORS)]:
        with patch.object(Path, 'home', return_value=root), \
             patch.object(Gio.VolumeMonitor, 'get_mounts', return_value=[]), \
             patch('omarchy_file_picker.picker.thumbnail_file', return_value=None), \
             patch('omarchy_file_picker.picker.load_colors', return_value=colors):
            window = PickerWindow(app, request, None)
            window.present()
            settle(400)
            try:
                for target in (None, text_file, image_file):
                    window._show_context_menu(35, 35, target)
                    settle()
                    popover = window.context_popover
                    buttons = [row for row in children(popover.get_child()) if isinstance(row, Gtk.MenuButton)]
                    assert len(buttons) >= 2
                    events = []
                    for index, button in enumerate(buttons):
                        button.get_popover().connect('map', lambda _, i=index: events.append(('map', i)))
                        button.get_popover().connect('unmap', lambda _, i=index: events.append(('unmap', i)))

                    previous = None
                    # popup() is the native activation used by the hover timer.
                    # Actual crossing/hover events need ui_context_hover's real
                    # isolated pointer; synthetic enter events cannot move it.
                    for mode in ('popup', 'activate', 'popup'):
                        for index in list(range(len(buttons))) + list(reversed(range(len(buttons)))):
                            if index == previous:
                                continue
                            before = len(events)
                            button = buttons[index]
                            if mode == 'activate':
                                button.emit('activate')
                            else:
                                button.popup()
                            # Gtk.Button's action activation includes a delayed
                            # pressed animation before it emits clicked.
                            settle(350 if mode == 'activate' else 80)
                            assert popover.get_mapped(), 'Switching dismissed the root menu'
                            assert [b.get_popover().get_mapped() for b in buttons] == [
                                i == index for i in range(len(buttons))], (palette, target, mode, index, events)
                            if previous is not None:
                                transition = events[before:]
                                assert transition.index(('unmap', previous)) < transition.index(('map', index))
                            previous = index

                    # Dismiss normally, then ensure the root can be opened again.
                    window._close_context_menu()
                    settle()
                    assert not popover.get_mapped()
                    assert not any(button.get_popover().get_mapped() for button in buttons)
                window._show_context_menu(35, 35, text_file)
                settle()
                buttons = [row for row in children(window.context_popover.get_child()) if isinstance(row, Gtk.MenuButton)]
                buttons[0].popup()
                buttons[-1].popup()
                settle()
                assert buttons[-1].get_popover().get_mapped()
                # Native submenu button activation still executes and dismisses.
                buttons[-1].get_popover().get_child().get_first_child().emit('clicked')
                settle()
                assert window.context_popover is None
                assert window.get_visible()
            finally:
                window.destroy()
                settle()
            print(f'PASS: {palette} {type(Gdk.Display.get_default()).__name__} popup/activation ordering, repeated switches, dismissal and action', flush=True)
