"""Inline Trash pointer, keyboard, tab, search, and stale-selection regression.

Run on an explicitly isolated Xvfb display with POINTER_QA_ISOLATED=1.
Provider data is synthetic; no desktop Trash or user files are changed.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from unittest.mock import patch

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('GdkX11', '4.0')
from gi.repository import Gio, GLib, Gtk, GdkX11
from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow
from omarchy_file_picker.trash import TrashItem

assert os.environ.get('POINTER_QA_ISOLATED') == '1'
errors = []
def exception(*args):
    errors.append(args)
    sys.__excepthook__(*args)
sys.excepthook = exception


def settle():
    loop = GLib.MainLoop()
    GLib.timeout_add(150, lambda: loop.quit() or False)
    loop.run()
    assert not errors


def until(predicate):
    deadline = time.monotonic() + 8
    while not predicate() and time.monotonic() < deadline:
        settle()
    assert predicate(), 'Timed out'
    settle()


def click(widget, button=1):
    native = widget.get_native()
    valid, bounds = widget.compute_bounds(native)
    assert valid and widget.get_mapped()
    dx, dy = native.get_surface_transform()
    subprocess.run([os.environ['XDOTOOL'], 'mousemove', '--window', str(native.get_surface().get_xid()),
                    str(round(bounds.get_x() + bounds.get_width()/2 + dx)),
                    str(round(bounds.get_y() + bounds.get_height()/2 + dy)), 'click', str(button)], check=True)
    settle()


def key(window, value):
    subprocess.run([os.environ['XDOTOOL'], 'windowfocus', str(window.get_surface().get_xid()),
                    'key', '--clearmodifiers', value], check=True)
    settle()


with tempfile.TemporaryDirectory(prefix='gudfiles-inline-trash-') as temp, \
     patch.object(Path, 'home', return_value=Path(temp)), \
     patch.object(Gio.VolumeMonitor, 'get_mounts', return_value=[]):
    root = Path(temp)
    original = root / 'visible.txt'
    original.write_text('Must not be changed by Trash shortcuts')
    items = [TrashItem(f'trash:///qa-{i}', f'Clip {i}.mov', str(root / f'Clip {i}.mov'), '2026-09-19T12:30:00') for i in range(3)]
    request = PickerRequest(current_folder=root, explorer=True, multiple=True)
    app = PickerApplication(request, None)
    app.register(None)
    with patch('omarchy_file_picker.trash_ui.list_trash', side_effect=lambda _c: items[:]):
        window = PickerWindow(app, request, None)
        window.set_default_size(820, 580)
        window.present()
        settle()
        try:
            window._set_view('list')
            window.flow.select_child(window.children_by_path[original])
            trash = next(b for b in window.location_buttons if b._sidebar_key == 'trash')
            click(trash)
            page = window.trash_page
            until(lambda: not page.busy)
            assert window.browser_stack.get_visible_child() is page
            assert len([w for w in Gtk.Window.list_toplevels() if w.get_visible()]) == 1
            first, second = page.rows.get_child_at_index(0), page.rows.get_child_at_index(1)
            click(first)
            assert page.rows.get_selected_children() == [first]
            assert page.restore_button.get_sensitive()
            assert page.empty_button.get_sensitive()
            assert all(button.get_sensitive() for button in
                       (window.sort_button, window.grid_button, window.list_button, window.columns_button))
            window.grid_button.emit('clicked'); settle()
            assert window.view_mode == 'grid' and page.rows.get_max_children_per_line() == 100
            window.columns_button.emit('clicked'); settle()
            assert window.view_mode == 'columns' and page.rows.get_max_children_per_line() == 1
            window.list_button.emit('clicked'); settle()
            first, second = page.rows.get_child_at_index(0), page.rows.get_child_at_index(1)
            # Empty Trash defaults to Cancel and deletes only the confirmed
            # snapshot. A partial failure remains visible and selected.
            deleted = []
            dialog = page.confirm_empty()
            assert dialog.get_default_widget().get_label() == 'Cancel'
            dialog.response(Gtk.ResponseType.CANCEL)
            settle()
            assert not deleted and len(list(page._children())) == 3
            def delete(item, _cancel):
                if item is items[1]:
                    raise OSError('fixture refusal')
                deleted.append(item)
            with patch('omarchy_file_picker.trash_ui.delete_item', side_effect=delete):
                dialog = page.confirm_empty()
                dialog.response(Gtk.ResponseType.ACCEPT)
                until(lambda: not page.busy)
            assert deleted == [items[0], items[2]]
            assert page.rows.get_child_at_index(0).item is items[1]
            assert page.rows.get_child_at_index(1) is None
            assert 'Permanently deleted 2 of 3 items.' in page.status.get_text()
            assert 'fixture refusal' in page.error_label.get_text()
            page.refresh()
            until(lambda: not page.busy and page.rows.get_child_at_index(2) is not None)
            first, second = page.rows.get_child_at_index(0), page.rows.get_child_at_index(1)
            click(first)
            assert not window.drag_selection.active
            # Hidden ordinary rows cannot receive file actions or preview.
            with patch.object(window, '_confirm_remove') as remove, patch.object(window, '_show_rename_dialog') as rename:
                key(window, 'Delete')
                key(window, 'F2')
                key(window, 'space')
                remove.assert_not_called()
                rename.assert_not_called()
                assert not window.quicklook.get_visible()
                assert original.read_text() == 'Must not be changed by Trash shortcuts'
            # Context menu belongs to this view, closes outside, and preserves multi-select.
            key(window, 'ctrl+a')
            assert len(page.rows.get_selected_children()) == 3
            click(second, 3)
            assert window.context_popover and window.context_popover.get_visible()
            assert len(page.rows.get_selected_children()) == 3
            click(window.search_button)
            until(lambda: window.context_popover is None)
            key(window, 'Escape')
            page.rows.unselect_all()
            click(first)
            assert page.capture()['selected'] == [items[0].uri], page.capture()
            trash_tab = window.tabs.current
            normal = window.tabs.new(root)
            settle()
            assert window.special_mode is None and window.sort_button.get_sensitive()
            click(trash_tab.button)
            until(lambda: not page.busy)
            assert page.capture()['selected'] == [items[0].uri], (page.capture(), trash_tab.state)
            # Background Trash tab remains independent and normal history restores.
            click(trash, 2)
            other = window.tabs.items[-1]
            assert other is not trash_tab and window.tabs.current is trash_tab
            click(other.button)
            until(lambda: not page.busy)
            assert not page.capture()['selected']
            click(trash_tab.button)
            until(lambda: not page.busy)
            assert page.capture()['selected'] == [items[0].uri], (page.capture(), trash_tab.state)
            key(window, 'alt+Left')
            assert window.special_mode is None
            key(window, 'alt+Right')
            until(lambda: not page.busy)
            assert window.special_mode == 'trash'
            # Search filters Trash and retains input focus after asynchronous reads.
            key(window, 'ctrl+f')
            window.search.set_text('Clip 1')
            until(lambda: not page.busy and page.rows.get_child_at_index(1) is None)
            assert page.rows.get_child_at_index(0).item.name == 'Clip 1.mov'
            assert isinstance(window.get_focus(), Gtk.Editable)
            key(window, 'Return')
            assert not window.search_popover.get_visible()
            key(window, 'Escape')
            until(lambda: not page.busy and page.rows.get_child_at_index(2) is not None)
            # Navigating away while restoring cannot navigate the user back.
            click(page.rows.get_child_at_index(0))
            started, release = threading.Event(), threading.Event()
            def restore(item, _cancel):
                started.set()
                release.wait(5)
                items.remove(item)
                return Path(item.original)
            with patch('omarchy_file_picker.trash_ui.restore_item', side_effect=restore):
                click(page.restore_button)
                until(started.is_set)
                assert window.file_job_active
                click(normal.button)
                release.set()
                until(lambda: not window.file_job_active)
                assert window.tabs.current is normal and window.special_mode is None
            click(trash_tab.button)
            until(lambda: not page.busy)
            assert page.rows.get_child_at_index(2) is None
            assert 'Restored 1 item.' in page.status.get_text()
            # A different Trash tab/query chosen mid-restore wins after completion.
            click(page.rows.get_child_at_index(0))
            started.clear()
            release.clear()
            with patch('omarchy_file_picker.trash_ui.restore_item', side_effect=restore):
                click(page.restore_button)
                until(started.is_set)
                click(other.button)
                window.search.set_text('Clip 2')
                settle()
                settle()
                release.set()
                until(lambda: not page.busy)
                assert window.tabs.current is other
                assert page.rows.get_child_at_index(0).item.name == 'Clip 2.mov'
                assert page.rows.get_child_at_index(1) is None
        finally:
            window.destroy()
            settle()
        # Save/folder acceptance must never target the hidden previous folder.
        for request in (PickerRequest(current_folder=root, mode='save', current_name='new.txt'),
                        PickerRequest(current_folder=root, directory=True)):
            window = PickerWindow(app, request, None, on_result=lambda *_: None)
            window.present()
            settle()
            try:
                window._open_trash()
                until(lambda: not window.trash_page.busy)
                assert not window.accept_button.get_sensitive()
                with patch.object(window, '_finish') as finish:
                    window._accept()
                    finish.assert_not_called()
                window._go_back(None)
                settle()
                assert window.accept_button.get_sensitive()
            finally:
                window.destroy()
                settle()
print('PASS: inline Trash real pointer/keyboard, context dismissal, tabs/history, search focus, restore navigation, and save/folder safety', flush=True)
