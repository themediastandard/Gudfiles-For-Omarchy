"""Native unavailable-Trash confirmation; optional disposable live NAS fixtures."""
import os
from pathlib import Path
import tempfile
import time
from unittest.mock import patch

from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow
from gi.repository import Gio, GLib, Gtk


def settle(ms=120):
    loop = GLib.MainLoop()
    GLib.timeout_add(ms, lambda: loop.quit() or False)
    loop.run()


def until(predicate):
    deadline = time.monotonic() + 10
    while not predicate() and time.monotonic() < deadline:
        settle(30)
    assert predicate(), 'GTK operation timed out'


def unavailable():
    return next((dialog for dialog in Gtk.Window.get_toplevels()
                 if dialog.get_visible() and dialog.get_title() == 'Trash is not available'), None)


def descendants(widget):
    yield widget
    child = widget.get_first_child()
    while child:
        yield from descendants(child)
        child = child.get_next_sibling()


with tempfile.TemporaryDirectory(prefix='gudfiles-trash-ui-') as temp, \
        patch.object(Path, 'home', return_value=Path(temp)), \
        patch.object(Gio.VolumeMonitor, 'get_mounts', return_value=[]), \
        patch.object(PickerWindow, '_play_sound') as sound, \
        patch.object(PickerWindow, '_show_error') as errors:
    root = Path(temp)
    request = PickerRequest(current_folder=root, explorer=True, multiple=True)
    app = PickerApplication(request, None)
    app.register(None)
    window = PickerWindow(app, request, None)
    window.present()
    settle()
    baseline = window.get_width(), window.get_height()
    try:
        for mode in ('grid', 'list', 'columns'):
            path = root / f'{mode}.txt'
            path.write_text('preserve on Cancel')
            window._set_view(mode)
            window._refresh_files()
            settle()
            error = GLib.Error.new_literal(Gio.io_error_quark(), 'Operation not supported', Gio.IOErrorEnum.NOT_SUPPORTED)
            with patch.object(Gio.File, 'trash', side_effect=error):
                window._confirm_remove([path]).response(Gtk.ResponseType.ACCEPT)
                until(lambda: not window.file_job_active and unavailable() is not None)
                dialog = unavailable()
                assert path.read_text() == 'preserve on Cancel'
                assert dialog.get_default_widget().get_label() == 'Cancel'
                assert 'This cannot be undone.' in ' '.join(w.get_text() for w in descendants(dialog) if isinstance(w, Gtk.Label))
                dialog.response(Gtk.ResponseType.CANCEL)
                settle()
                assert path.exists()
                sound.assert_not_called()
                errors.assert_not_called()
                window._confirm_remove([path]).response(Gtk.ResponseType.ACCEPT)
                until(lambda: not window.file_job_active and unavailable() is not None)
                unavailable().response(Gtk.ResponseType.ACCEPT)
                until(lambda: not window.file_job_active)
                assert not path.exists()
                sound.assert_called_once_with('delete')
                sound.reset_mock()

        path = root / 'changed.txt'
        path.write_text('original')
        window._refresh_files()
        error = GLib.Error.new_literal(Gio.io_error_quark(), 'Operation not supported', Gio.IOErrorEnum.NOT_SUPPORTED)
        with patch.object(Gio.File, 'trash', side_effect=error):
            window._confirm_remove([path]).response(Gtk.ResponseType.ACCEPT)
            until(lambda: not window.file_job_active and unavailable() is not None)
            path.write_text('changed while confirmation was open')
            unavailable().response(Gtk.ResponseType.ACCEPT)
            until(lambda: not window.file_job_active)
            assert path.read_text() == 'changed while confirmation was open'
            assert 'changed' in errors.call_args.args[1]
            sound.assert_not_called()
            errors.reset_mock()

        error = GLib.Error.new_literal(Gio.io_error_quark(), 'Permission denied', Gio.IOErrorEnum.PERMISSION_DENIED)
        with patch.object(Gio.File, 'trash', side_effect=error):
            window._confirm_remove([path]).response(Gtk.ResponseType.ACCEPT)
            until(lambda: not window.file_job_active)
            assert unavailable() is None and path.exists()
            assert 'Not completed: 1' in errors.call_args.args[1]
            sound.assert_not_called()
            errors.reset_mock()

        # Live mode changes only unique, fixture-owned directories/files.
        # GVfs share paths contain ':', so use newline-separated paths.
        for share in os.environ.get('TRASH_QA_MOUNT_PATHS', '').splitlines():
            with tempfile.TemporaryDirectory(prefix='.gudfiles-trash-ui-', dir=share) as fixture:
                folder = Path(fixture)
                path = folder / 'disposable-trash-test.txt'
                path.write_text('live NAS fixture')
                window.navigate(folder)
                settle()
                window._confirm_remove([path]).response(Gtk.ResponseType.ACCEPT)
                until(lambda: not window.file_job_active and unavailable() is not None)
                assert path.read_text() == 'live NAS fixture'
                dialog = unavailable()
                if screenshot := os.environ.get('TRASH_QA_SCREENSHOT'):
                    settle(250)
                    snapshot = Gtk.Snapshot.new()
                    Gtk.WidgetPaintable.new(dialog).snapshot(snapshot, dialog.get_width(), dialog.get_height())
                    dialog.get_renderer().render_texture(snapshot.to_node(), None).save_to_png(screenshot)
                dialog.response(Gtk.ResponseType.CANCEL)
                settle()
                assert path.exists()
                window._confirm_remove([path]).response(Gtk.ResponseType.ACCEPT)
                until(lambda: not window.file_job_active and unavailable() is not None)
                unavailable().response(Gtk.ResponseType.ACCEPT)
                until(lambda: not window.file_job_active)
                assert not path.exists()
                sound.assert_called_once_with('delete')
                sound.reset_mock()
                errors.assert_not_called()
                window.navigate(root)
                settle()
                print('PASS: live NAS unsupported Trash, Cancel preservation and explicitly confirmed fixture deletion')
        assert (window.get_width(), window.get_height()) == baseline
        print('PASS: all-view unavailable-Trash dialogs, Cancel default, guarded delete, changed-file refusal, ordinary failures and sound routing')
    finally:
        window.destroy()
