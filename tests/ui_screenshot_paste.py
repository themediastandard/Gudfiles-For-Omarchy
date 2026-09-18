"""Native PNG clipboard/menu/paste regression for Gudfiles.

GDK_BACKEND=wayland G_DEBUG=fatal-warnings PYTHONPATH=. python tests/ui_screenshot_paste.py
"""
from pathlib import Path
import tempfile
import traceback
from unittest.mock import patch

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gdk, GLib, Gtk

from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow


PNG = (b'\x89PNG\r\n\x1a\n'
       b'\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89'
       b'\x00\x00\x00\rIDAT\x08\xd7c\xf8\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff\x89\x99=\x1d'
       b'\x00\x00\x00\x00IEND\xaeB`\x82')


def descendants(widget):
    result = [widget]
    child = widget.get_first_child()
    while child:
        result.extend(descendants(child))
        child = child.get_next_sibling()
    return result


def labels(widget):
    return [item.get_text() for item in descendants(widget) if isinstance(item, Gtk.Label)]


def button(widget, title):
    return next(item for item in descendants(widget)
                if isinstance(item, Gtk.Button) and title in labels(item))


def png_provider():
    return Gdk.ContentProvider.new_for_bytes('image/png', GLib.Bytes.new(PNG))


class Gesture:
    def set_state(self, state):
        assert state == Gtk.EventSequenceState.CLAIMED


with tempfile.TemporaryDirectory(prefix='gudfiles-screenshot-paste-') as temp:
    root = Path(temp)
    current, child, files = root / 'current', root / 'current/child', root / 'files'
    current.mkdir()
    child.mkdir()
    files.mkdir()
    source = files / 'copied.txt'
    source.write_text('file-list wins')
    ordinary = current / 'ordinary.txt'
    ordinary.write_text('ordinary')

    request = PickerRequest(current_folder=current, multiple=True)
    app = PickerApplication(request, None)
    app.register(None)
    window = PickerWindow(app, request, None)
    window.preferences_path = root / 'preferences.json'
    window.bookmarks_path = root / 'bookmarks'
    errors = []
    window._show_error = lambda *args: errors.append(args)
    window.present()
    loop = GLib.MainLoop()
    passed = False
    clipboard = window.get_clipboard()

    def guarded(callback):
        def run():
            try:
                return callback()
            except Exception:
                traceback.print_exc()
                loop.quit()
                return False
        return run

    def show(path=None):
        window._show_context_menu(30, 30, path)
        return labels(window.context_popover)

    def begin():
        clipboard.set('plain text')
        assert 'Put Screenshot Here' not in show()
        window._close_context_menu()
        assert 'Put Screenshot Here' not in show(child)
        window._close_context_menu()

        image = png_provider()
        clipboard.set_content(image)
        assert 'Put Screenshot Here' in show()
        window._close_context_menu()
        assert 'Put Screenshot Here' in show(child)
        window._close_context_menu()
        assert 'Put Screenshot Here' not in show(ordinary)
        window._close_context_menu()

        window.special_mode = 'recent'
        assert 'Put Screenshot Here' not in show()
        window._close_context_menu()
        window.special_mode = None
        with patch.object(window, '_computer_search_active', return_value=True):
            assert 'Put Screenshot Here' not in show(child)
            window._close_context_menu()
        with patch('omarchy_file_picker.file_management.os.access', return_value=False):
            assert 'Put Screenshot Here' not in show()
            window._close_context_menu()

        # The explicit folder action writes inside that clicked folder and leaves
        # the exact provider/bytes on the clipboard.
        provider = clipboard.get_content()
        show(child)
        button(window.context_popover, 'Put Screenshot Here').emit('clicked')
        GLib.timeout_add(25, guarded(lambda: wait_folder(provider)))
        return False

    def wait_folder(provider):
        outputs = list(child.glob('screenshot-*.png'))
        if window.file_job_active or not outputs:
            return True
        assert outputs[0].read_bytes() == PNG
        assert clipboard.get_content() == provider

        # A clipboard that advertises both formats keeps file-list paste
        # authoritative: Ctrl+V/paste copies the file and creates no screenshot.
        window._copy_files([source])
        file_provider = clipboard.get_content()
        combined = Gdk.ContentProvider.new_union([file_provider, png_provider()])
        clipboard.set_content(combined)
        before = set(current.glob('screenshot-*.png'))
        window._paste_files()
        GLib.timeout_add(25, guarded(lambda: wait_file_precedence(before, combined)))
        return False

    def wait_file_precedence(before, provider):
        if window.transfer_queue.active or not (current / source.name).exists():
            return True
        assert (current / source.name).read_text() == 'file-list wins'
        assert set(current.glob('screenshot-*.png')) == before
        assert clipboard.get_content() == provider

        # PNG-only Ctrl+V saves to the current folder, refreshes and selects it.
        image = png_provider()
        clipboard.set_content(image)
        window._paste_files()
        GLib.timeout_add(25, guarded(lambda: wait_current(image)))
        return False

    def wait_current(provider):
        outputs = list(current.glob('screenshot-*.png'))
        if window.file_job_active or not outputs:
            return True
        created = outputs[0]
        assert created.read_bytes() == PNG
        assert window._selected_paths() == [created], window._selected_paths()
        assert clipboard.get_content() == provider

        # A bounded read failure publishes nothing, reports failure, and keeps
        # clipboard ownership/content. Lower the cap only for this fixture.
        before = set(current.iterdir())
        errors.clear()
        with patch('omarchy_file_picker.file_management.MAX_SCREENSHOT_BYTES', len(PNG) - 1):
            window._put_screenshot(current)
            until = GLib.get_monotonic_time() + 1_000_000
            while not errors and GLib.get_monotonic_time() < until:
                GLib.MainContext.default().iteration(True)
        assert errors and errors[-1][0] == 'Could not put screenshot here', errors
        assert set(current.iterdir()) == before
        assert clipboard.get_content() == provider

        # A worker-side write failure is also non-success and leaves no artifact.
        errors.clear()
        patcher = patch('omarchy_file_picker.file_management.save_screenshot_png',
                        side_effect=OSError('fixture write failure'))
        patcher.start()
        window._put_screenshot(current)
        GLib.timeout_add(25, guarded(lambda: wait_write_failure(before, provider, patcher)))
        return False

    def wait_write_failure(before, provider, patcher):
        global passed
        if window.file_job_active or not errors:
            return True
        patcher.stop()
        assert errors[-1][0] == 'Put screenshot here failed', errors
        assert 'fixture write failure' in errors[-1][1]
        assert set(current.iterdir()) == before
        assert clipboard.get_content() == provider
        passed = True
        print('PASS: screenshot menu scope, folder/current destinations, Ctrl+V precedence, bytes, bounds, failures and clipboard preservation')
        loop.quit()
        return False

    GLib.timeout_add(350, guarded(begin))
    GLib.timeout_add_seconds(15, lambda: loop.quit() or False)
    loop.run()
    window.destroy()
    assert passed, errors
