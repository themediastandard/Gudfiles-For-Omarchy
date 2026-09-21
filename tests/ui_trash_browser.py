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


def rows(page):
    result = []
    row = page.rows.get_first_child()
    while row:
        if isinstance(row, Gtk.FlowBoxChild):
            result.append(row)
        row = row.get_next_sibling()
    return result


def select(page, name):
    page.rows.unselect_all()
    page.rows.select_child(next(row for row in rows(page) if row.item.name == name))


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
                    page = window.trash_page
                    until(lambda: not page.busy)
                    assert len(rows(page)) == 2
                    if directory := os.environ.get('TRASH_QA_SCREENSHOTS'):
                        target = Path(directory)
                        target.mkdir(parents=True, exist_ok=True)
                        window.queue_draw()
                        settle()
                        snapshot = Gtk.Snapshot.new()
                        Gtk.WidgetPaintable.new(window).snapshot(snapshot, window.get_width(), window.get_height())
                        node = snapshot.to_node()
                        assert node is not None
                        window.get_renderer().render_texture(node, None).save_to_png(str(target / (theme + '.png')))

                    assert not page.restore_button.get_sensitive()
                    assert page.empty_button.get_sensitive()
                    assert all(button.get_sensitive() for button in
                               (window.sort_button, window.grid_button, window.list_button, window.columns_button))
                    window._set_view('list')
                    assert page.list_header.get_visible() and page.rows.get_max_children_per_line() == 1
                    window._set_view('grid')
                    assert not page.list_header.get_visible() and page.rows.get_max_children_per_line() == 100
                    window._set_view('columns')
                    assert page.rows.get_max_children_per_line() == 1
                    window._set_view('list')
                    # Empty Trash defaults to Cancel. The operation uses only
                    # its confirmed snapshot and leaves partial failures visible.
                    deleted = []
                    dialog = page.confirm_empty()
                    assert dialog.get_default_widget().get_label() == 'Cancel'
                    dialog.response(Gtk.ResponseType.CANCEL)
                    settle()
                    def delete(item, _cancel):
                        if item.name == document.name:
                            raise OSError('fixture refusal')
                        deleted.append(item)
                    with patch('omarchy_file_picker.trash_ui.delete_item', side_effect=delete), \
                         patch.object(window, '_play_sound') as sound:
                        dialog = page.confirm_empty()
                        dialog.response(Gtk.ResponseType.ACCEPT)
                        until(lambda: not page.busy)
                        sound.assert_called_once_with('delete')
                    assert len(deleted) == 1 and len(rows(page)) == 1
                    assert rows(page)[0].item.name == document.name
                    assert page.status.get_text() == 'Permanently deleted 1 of 2 items.'
                    assert 'fixture refusal' in page.error_label.get_text()
                    page.refresh()
                    until(lambda: not page.busy)
                    assert len(rows(page)) == 2
                    window._open_trash()
                    assert window.trash_page is page, 'Duplicate browser'
                    until(lambda: not page.busy)
                    # A replacement must survive; the original stays in Trash.
                    document.write_text('Replacement bytes')
                    select(page, document.name)
                    page.restore_button.emit('clicked')
                    until(lambda: not page.busy)
                    assert page.error_label.get_visible()
                    assert 'already exists' in page.error_label.get_text()
                    assert document.read_text() == 'Replacement bytes'
                    assert len(fixtures()) == 2
                    # Mixed success keeps failures selected and reports both.
                    page.rows.select_all()
                    page.restore_button.emit('clicked')
                    until(lambda: not page.busy)
                    assert page.status.get_text() == 'Restored 1 of 2 items.'
                    assert (folder / 'clip.txt').read_text() == 'nested bytes'
                    assert len(rows(page)) == 1
                    document.unlink()
                    page.restore_button.emit('clicked')
                    until(lambda: not page.busy)
                    assert document.read_text() == 'Original bytes: café'
                    assert not page.error_label.get_visible()
                    assert not rows(page)
                    assert not window.file_job_active
                    # Unavailable is not rendered as an empty successful read.
                    with patch('omarchy_file_picker.trash_ui.list_trash', side_effect=OSError('Trash service unavailable')):
                        page.refresh()
                        until(lambda: not page.busy)
                        assert page.error_label.get_visible()
                        assert 'could not' in page.status.get_text()
                    page.refresh()
                    until(lambda: not page.busy)
                    assert page.status.get_text().endswith('Trash is empty.')
                    assert not page.error_label.get_visible()
                    # Trash is a location in the same window and navigation history.
                    assert window.browser_stack.get_visible_child_name() == 'trash'
                    assert window.tabs.current.label.get_text() == 'Trash'
                    assert button.has_css_class('active')
                    assert not window._selected_paths()
                    assert not window.list_details.widget.get_visible()
                    assert not window.metadata_viewport.get_visible()
                    window._go_back(None)
                    assert window.special_mode is None and window.current_dir == root
                    assert window.browser_stack.get_visible_child_name() != 'trash'
                    window._go_forward(None)
                    until(lambda: not page.busy)
                    assert window.special_mode == 'trash'
                    assert window.browser_stack.get_visible_child() is page
                    # Switching tabs preserves each location.
                    trash_tab = window.tabs.current
                    normal_tab = window.tabs.new(root)
                    settle()
                    assert window.special_mode is None
                    window.tabs.select(trash_tab)
                    until(lambda: not page.busy)
                    assert window.special_mode == 'trash'
                    assert window.tabs.current.label.get_text() == 'Trash'
                    window.tabs.close(normal_tab)
                    # Leaving a pending read must not affect a later read.
                    release = threading.Event()
                    started = threading.Event()
                    def pending(_cancel):
                        started.set()
                        release.wait(5)
                        raise OSError('stale error must not be shown')
                    with patch('omarchy_file_picker.trash_ui.list_trash', side_effect=pending):
                        page.refresh()
                        until(started.is_set)
                        assert page.busy
                        window.navigate(root)
                        assert not page.active and not page.busy
                    button.emit('clicked')
                    until(lambda: not page.busy)
                    release.set()
                    settle()
                    assert not page.error_label.get_visible()
                    assert window.browser_stack.get_visible_child() is page
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
