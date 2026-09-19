"""Native Trash sidebar/browser, real GIO restoration, and failure recovery.

TRASH_QA_LIVE=1 PYTHONPATH=. python tests/ui_trash_browser.py
Only uniquely named disposable fixtures are trashed/restored. No user items
are displayed, restored or deleted by this test.
"""
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from unittest.mock import patch

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gio, GLib, Gtk
from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow
from omarchy_file_picker.theme import DEFAULT_COLORS, load_colors
from omarchy_file_picker.trash import list_trash, restore_item

assert os.environ.get('TRASH_QA_LIVE') == '1'
errors = []
def callback_error(*args):
    errors.append(args)
    sys.__excepthook__(*args)
sys.excepthook = callback_error


def settle():
    loop = GLib.MainLoop()
    GLib.timeout_add(80, lambda: loop.quit() or False)
    loop.run()
    assert not errors


def until(predicate):
    deadline = time.monotonic() + 10
    while not predicate() and time.monotonic() < deadline:
        settle()
    assert predicate(), 'Timed out'
    settle()


def rows(dialog):
    result = []
    row = dialog.rows.get_first_child()
    while row:
        result.append(row)
        row = row.get_next_sibling()
    return result


def select(dialog, name):
    dialog.rows.unselect_all()
    dialog.rows.select_row(next(row for row in rows(dialog) if row.item.name == name))


with tempfile.TemporaryDirectory(prefix='gudfiles-trash-qa-', dir=Path.home() / '.cache') as temp:
    root = Path(temp)
    request = PickerRequest(current_folder=root, explorer=True)
    app = PickerApplication(request, None)
    app.register(None)
    active = load_colors()
    dark = {**active, 'mode': 'dark', 'background': '#17191f', 'foreground': '#d7dce4',
            'light_foreground': '#b3bdcf', 'dark_foreground': '#9ba5b5',
            'bright_foreground': '#ffffff', 'accent': '#86a6f4', 'selection': '#343f5b',
            'dark_background': '#1f222b', 'darker_background': '#353b49',
            'lighter_background': '#282d39'}
    def fixtures(_cancel=None):
        return [item for item in list_trash(_cancel) if item.original.startswith(str(root) + '/')]
    try:
        for theme, colors in [('active', active), ('light', DEFAULT_COLORS), ('dark', dark)]:
            parent = root / theme
            parent.mkdir()
            document = parent / 'Footage résumé.txt'
            document.write_text('Original bytes: café')
            folder = parent / 'Scene 01'
            folder.mkdir()
            (folder / 'clip.txt').write_text('nested bytes')
            for path in (document, folder):
                assert Gio.File.new_for_path(str(path)).trash(None)
                assert not path.exists()
            until(lambda: len(fixtures()) == 2)
            with patch.object(Path, 'home', return_value=root / 'home'), \
                 patch.object(Gio.VolumeMonitor, 'get_mounts', return_value=[]), \
                 patch('omarchy_file_picker.picker.load_colors', return_value=colors), \
                 patch('omarchy_file_picker.trash_ui.list_trash', side_effect=fixtures):
                window = PickerWindow(app, request, None)
                window.present()
                settle()
                try:
                    button = next(b for b in window.location_buttons if b._sidebar_key == 'trash')
                    button.emit('clicked')
                    dialog = window.trash_dialog
                    until(lambda: not dialog.busy)
                    assert len(rows(dialog)) == 2
                    if directory := os.environ.get('TRASH_QA_SCREENSHOTS'):
                        target = Path(directory)
                        target.mkdir(parents=True, exist_ok=True)
                        dialog.queue_draw()
                        settle()
                        snapshot = Gtk.Snapshot.new()
                        Gtk.WidgetPaintable.new(dialog).snapshot(snapshot, dialog.get_width(), dialog.get_height())
                        node = snapshot.to_node()
                        assert node is not None
                        dialog.get_renderer().render_texture(node, None).save_to_png(str(target / (theme + '.png')))

                    assert not dialog.restore_button.get_sensitive()
                    window._open_trash()
                    assert window.trash_dialog is dialog, 'Duplicate browser'
                    # A replacement must survive; the original stays in Trash.
                    document.write_text('Replacement bytes')
                    select(dialog, document.name)
                    dialog.restore_button.emit('clicked')
                    until(lambda: not dialog.busy)
                    assert dialog.error_label.get_visible()
                    assert 'already exists' in dialog.error_label.get_text()
                    assert document.read_text() == 'Replacement bytes'
                    assert len(fixtures()) == 2
                    # Mixed success keeps failures selected and reports both.
                    dialog.rows.select_all()
                    dialog.restore_button.emit('clicked')
                    until(lambda: not dialog.busy)
                    assert dialog.status.get_text() == 'Restored 1 of 2 items.'
                    assert (folder / 'clip.txt').read_text() == 'nested bytes'
                    assert len(rows(dialog)) == 1
                    document.unlink()
                    dialog.restore_button.emit('clicked')
                    until(lambda: not dialog.busy)
                    assert document.read_text() == 'Original bytes: café'
                    assert not dialog.error_label.get_visible()
                    assert not rows(dialog)
                    assert not window.file_job_active
                    # Unavailable is not rendered as an empty successful read.
                    with patch('omarchy_file_picker.trash_ui.list_trash', side_effect=OSError('Trash service unavailable')):
                        dialog.refresh_button.emit('clicked')
                        until(lambda: not dialog.busy)
                        assert dialog.error_label.get_visible()
                        assert 'could not' in dialog.status.get_text()
                    dialog.refresh_button.emit('clicked')
                    until(lambda: not dialog.busy)
                    assert dialog.status.get_text() == 'Trash is empty.'
                    assert not dialog.error_label.get_visible()
                    dialog.done_button.emit('clicked')
                    until(lambda: window.trash_dialog is None)
                    button.emit('clicked')
                    dialog = window.trash_dialog
                    until(lambda: not dialog.busy)
                    assert not rows(dialog)
                    dialog.done_button.emit('clicked')
                    until(lambda: window.trash_dialog is None)
                    # Closing a pending read must not affect a newer browser.
                    release = threading.Event()
                    def pending(_cancel):
                        release.wait(2)
                        return []
                    with patch('omarchy_file_picker.trash_ui.list_trash', side_effect=pending):
                        button.emit('clicked')
                        old = window.trash_dialog
                        assert old.busy
                        old.done_button.emit('clicked')
                        until(lambda: window.trash_dialog is None)
                    button.emit('clicked')
                    new = window.trash_dialog
                    release.set()
                    until(lambda: not old.busy and not new.busy)
                    assert window.trash_dialog is new
                    new.done_button.emit('clicked')
                    until(lambda: window.trash_dialog is None)
                    # Shortcut visibility follows the existing sidebar controls.
                    window._remove_sidebar_item(button)
                    assert not any(b._sidebar_key == 'trash' for b in window.location_buttons)
                    window._restore_sidebar_locations()
                    assert any(b._sidebar_key == 'trash' for b in window.location_buttons)
                finally:
                    window.destroy()
                    settle()
            print('PASS:', theme, 'Trash sidebar, original paths, collision preservation, partial restore, bytes, unavailable/retry, empty/reopen and shortcut persistence', flush=True)
    finally:
        # Restore only this test's remaining fixtures, preserving user Trash.
        for item in fixtures():
            path = Path(item.original)
            if path.exists():
                path.rename(path.with_name(path.name + '.qa-replacement'))
            path.parent.mkdir(parents=True, exist_ok=True)
            restore_item(item)
