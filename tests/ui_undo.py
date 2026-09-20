"""Native async rename/Undo, keyboard routing and truthful failures with disposable data."""
import sys
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gdk, GLib, Gtk
from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow


def settle(predicate=lambda: True, seconds=4):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        while GLib.MainContext.default().pending():
            GLib.MainContext.default().iteration(False)
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError('native operation timed out')


def descendants(widget):
    yield widget
    child = widget.get_first_child()
    while child:
        yield from descendants(child)
        child = child.get_next_sibling()


def entry(dialog):
    return next(widget for widget in descendants(dialog) if isinstance(widget, Gtk.Entry))


failures = []
def report_exception(*args):
    failures.append(args)
    sys.__excepthook__(*args)
sys.excepthook = report_exception
with tempfile.TemporaryDirectory() as temporary:
    home = Path(temporary)
    folder, elsewhere = home / 'files', home / 'elsewhere'
    folder.mkdir(); elsewhere.mkdir()
    original = folder / 'clip.txt'
    original.write_text('footage')
    request = PickerRequest(current_folder=folder, mode='explorer')
    app = PickerApplication(request, None)
    app.register(None)
    with patch.object(Path, 'home', return_value=home), patch.dict(os.environ, {'XDG_STATE_HOME': str(home / 'state')}):
        window = PickerWindow(app, request, None)
        errors, annotations = [], []
        window._show_error = lambda *args: errors.append(args)
        window._creative_paths_renamed = lambda mapping, **kwargs: annotations.append(mapping)
        window._play_sound = lambda *args: None
        window.present()
        settle(lambda: original in window.children_by_path)
        assert not window._can_undo()
        dialog = window._show_rename_dialog(original)
        entry(dialog).set_text('renamed.txt')
        dialog.response(Gtk.ResponseType.ACCEPT)
        assert window.file_job_active
        assert not entry(dialog).get_sensitive()
        settle(lambda: not window.file_job_active)
        renamed = folder / 'renamed.txt'
        assert renamed.read_text() == 'footage' and not original.exists()
        assert annotations == [{original: renamed}]
        assert window._can_undo() and window._undo_label() == 'Undo Rename'
        window._show_context_menu(24, 24, renamed)
        controls = [widget for widget in descendants(window.context_popover)
                    if isinstance(widget, Gtk.Button)]
        assert any('Undo Rename' in ' '.join(child.get_text() for child in descendants(button)
                                            if isinstance(child, Gtk.Label)) and button.get_sensitive()
                   for button in controls)
        window._close_context_menu()
        window.search_button.popup()
        window.search.grab_focus()
        settle()
        assert window._on_key_pressed(None, Gdk.KEY_z, 0, Gdk.ModifierType.CONTROL_MASK) == Gdk.EVENT_PROPAGATE
        assert renamed.exists()
        window.search_button.popdown()
        window.quicklook.show_file(renamed)
        settle(lambda: window.quicklook.get_visible())
        assert window._on_key_pressed(None, Gdk.KEY_z, 0, Gdk.ModifierType.CONTROL_MASK) == Gdk.EVENT_PROPAGATE
        assert renamed.exists()
        window.quicklook.close()
        settle(lambda: not window.quicklook.get_visible())
        window.flow.grab_focus()
        assert window._on_key_pressed(None, Gdk.KEY_z, 0, Gdk.ModifierType.CONTROL_MASK) == Gdk.EVENT_STOP
        settle(lambda: not window.file_job_active)
        assert original.read_text() == 'footage' and not renamed.exists()
        assert annotations[-1] == {renamed: original}
        assert not window._can_undo()

        # A failure cannot announce or annotate an inverse that did not happen.
        dialog = window._show_rename_dialog(original)
        entry(dialog).set_text('renamed.txt')
        dialog.response(Gtk.ResponseType.ACCEPT)
        settle(lambda: not window.file_job_active)
        original.write_text('collision')
        before = len(annotations)
        window._undo_file_action()
        settle(lambda: not window.file_job_active)
        assert errors and len(annotations) == before
        assert original.read_text() == 'collision' and renamed.read_text() == 'footage'
        original.unlink()
        # Navigation during the operation never redirects the active folder.
        window.navigate(elsewhere)
        window._undo_file_action()
        settle(lambda: not window.file_job_active)
        assert window.current_dir == elsewhere
        assert original.read_text() == 'footage'
        # The real queue captures its receipt on the worker before UI polling.
        job = window.transfer_queue.add([original], elsewhere, True, start=True)
        settle(lambda: job.state in {'completed', 'failed', 'paused'})
        window._poll_transfers()
        assert job.state == 'completed', job.error
        assert window._can_undo() and window._undo_label() == 'Undo Move'
        window._undo_file_action()
        settle(lambda: not window.file_job_active)
        assert original.read_text() == 'footage' and not (elsewhere / original.name).exists()
        window.destroy()
        settle()
assert not failures, failures
print('PASS: native async rename, visible Undo, Ctrl+Z, exact inverse annotations, collision/retry and navigation')
