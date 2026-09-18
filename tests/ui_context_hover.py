"""Real cascading-menu pointer/keyboard checks on an isolated Xvfb display.

Use POINTER_QA_ISOLATED=1, GDK_BACKEND=x11 and optionally XDOTOOL.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('GdkX11', '4.0')
from gi.repository import Gio, GLib, Gtk, GdkX11
from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow
from omarchy_file_picker.theme import load_colors
from tests.test_theme import LIGHT_PALETTES

assert os.environ.get('POINTER_QA_ISOLATED') == '1', 'Use a disposable Xvfb display.'
errors = []
original_hook = sys.excepthook
def callback_error(kind, value, traceback):
    errors.append(value)
    original_hook(kind, value, traceback)
sys.excepthook = callback_error


def settle(ms=350):
    loop = GLib.MainLoop()
    GLib.timeout_add(ms, lambda: loop.quit() or False)
    loop.run()


def send(*args, delay=60):
    subprocess.run([os.environ.get('XDOTOOL', 'xdotool'), *map(str, args)], check=True)
    settle(delay)


def move(widget, delay=350):
    native = widget.get_native()
    valid, bounds = widget.compute_bounds(native)
    assert valid and bounds.get_width() > 0
    dx, dy = native.get_surface_transform()
    send('mousemove', '--window', native.get_surface().get_xid(),
         round(bounds.get_x() + bounds.get_width() / 2 + dx),
         round(bounds.get_y() + bounds.get_height() / 2 + dy), delay=delay)


def children(widget):
    result = []
    child = widget.get_first_child()
    while child:
        result.append(child)
        child = child.get_next_sibling()
    return result


def point(widget):
    native = widget.get_native()
    geometry = subprocess.check_output([
        os.environ.get('XDOTOOL', 'xdotool'), 'getwindowgeometry', '--shell',
        str(native.get_surface().get_xid())], text=True)
    origin = dict(line.split('=', 1) for line in geometry.splitlines())
    valid, bounds = widget.compute_bounds(native)
    assert valid
    dx, dy = native.get_surface_transform()
    return (int(origin['X']) + dx + bounds.get_x() + bounds.get_width() / 2,
            int(origin['Y']) + dy + bounds.get_y() + bounds.get_height() / 2)


def cross_into(parent, item):
    start, end = point(parent), point(item)
    for step in range(1, 7):
        send('mousemove', *(round(a + (b - a) * step / 6) for a, b in zip(start, end)), delay=25)
    settle(400)


with tempfile.TemporaryDirectory(prefix='gudfiles-context-hover-') as temp:
    root = Path(temp)
    fixture = root / 'file.txt'
    fixture.write_text('fixture')
    request = PickerRequest(current_folder=root, explorer=True)
    app = PickerApplication(request, None)
    app.register(None)
    for theme, palette in [('active', load_colors()), ('light', next(iter(LIGHT_PALETTES.values())))]:
        with patch.object(Path, 'home', return_value=root), \
             patch.object(Gio.VolumeMonitor, 'get_mounts', return_value=[]), \
             patch('omarchy_file_picker.picker.load_colors', return_value=palette):
            window = PickerWindow(app, request, None)
            window.present()
            settle()
            try:
                send('windowfocus', window.get_surface().get_xid())
                for width in (820, 1200):
                    window.set_default_size(width, 720)
                    settle()
                    for edge in ('left', 'right'):
                        move(window.search_button)
                        x = 15 if edge == 'left' else window.browser_stack.get_width() - 15
                        window._show_context_menu(x, 70)
                        settle()
                        popover = window.context_popover
                        rows = children(popover.get_child())
                        menus = [row for row in rows if isinstance(row, Gtk.MenuButton)]
                        first, second = menus[-2:]
                        # Entering a submenu row opens without any click.
                        move(first)
                        assert first.get_popover().get_mapped(), (theme, width, edge, 'hover open')
                        assert first.get_popover().get_position() == (
                            Gtk.PositionType.LEFT if edge == 'right' else Gtk.PositionType.RIGHT)
                        assert window.context_popover is popover
                        # Crossing the native popup boundary keeps it available.
                        item = first.get_popover().get_child().get_first_child()
                        cross_into(first, item)
                        assert first.get_popover().get_mapped(), 'Crossing into submenu closed it'
                        move(first, delay=400)
                        assert first.get_popover().get_mapped(), 'Returning to parent closed it'
                        # Sibling hover switches the single visible submenu.
                        move(second)
                        assert second.get_popover().get_mapped()
                        assert not first.get_popover().get_mapped()
                        # A plain action closes the old submenu, keeping the root.
                        plain = next(row for row in rows if isinstance(row, Gtk.Button))
                        move(plain, delay=450)
                        assert not second.get_popover().get_mapped()
                        assert popover.get_mapped()
                        # Sweeping past a row must not flash open behind us.
                        move(first, delay=35)
                        move(plain, delay=450)
                        assert not first.get_popover().get_mapped()
                        first.set_sensitive(False)
                        move(first)
                        assert not first.get_popover().get_mapped()
                        first.set_sensitive(True)
                        move(plain)
                        # Click and keyboard activation are still native.
                        move(first, delay=25)
                        send('click', 1, delay=300)
                        assert first.get_popover().get_mapped()
                        send('key', 'Escape', delay=350)
                        assert not first.get_popover().get_mapped()
                        if window.context_popover is popover:
                            move(plain)
                            first.grab_focus()
                            send('key', 'space', delay=350)
                            assert first.get_popover().get_mapped()
                            move(first)
                            move(plain, delay=450)
                            assert not first.get_popover().get_mapped(), 'Pointer did not resume after keyboard use'
                            move(first)
                            assert first.get_popover().get_mapped()
                            send('click', 1, delay=350)
                            assert not first.get_popover().get_mapped(), 'Click closed then reopened under stationary pointer'
                        window._close_context_menu()
                        settle()
                        assert not popover.get_mapped()
                        print(f'PASS: {theme} {width} {edge} hover, handoff, siblings, disabled, click and Escape', flush=True)
                # Actual right-click followed by hover and action activation.
                move(window.children_by_path[fixture])
                send('click', 3, delay=350)
                assert window.context_popover and window.context_popover.get_mapped()
                popover = window.context_popover
                menus = [row for row in children(popover.get_child()) if isinstance(row, Gtk.MenuButton)]
                view = menus[-2]
                move(view)
                item = view.get_popover().get_child().get_first_child()
                move(item)
                send('click', 1, delay=350)
                assert window.context_popover is None
                assert window.view_mode == 'grid'
                # Dismiss/reopen and destruction cancel delayed opens.
                window._show_context_menu(20, 70)
                settle()
                old = window.context_popover
                pending = next(row for row in children(old.get_child()) if isinstance(row, Gtk.MenuButton))
                move(pending, delay=30)
                window._show_context_menu(100, 100)
                settle(500)
                assert not old.get_mapped()
                assert not any(sub.get_mapped() for sub in window.context_submenus)
                pending = next(row for row in children(window.context_popover.get_child()) if isinstance(row, Gtk.MenuButton))
                move(pending, delay=30)
            finally:
                window.destroy()
                settle(500)
            assert not errors, errors
            print(f'PASS: {theme} real right-click/action and pending-open teardown', flush=True)
