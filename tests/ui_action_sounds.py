"""Native success/cancel/failure sound routing with disposable files; no audio."""
import json
import os
from pathlib import Path
import tempfile
import time
from unittest.mock import patch

from omarchy_file_picker.picker import PickerApplication, PickerWindow, parse_args
from omarchy_file_picker.model import PickerRequest
from gi.repository import GLib, Gtk


def settle(seconds=.12):
    loop = GLib.MainLoop()
    GLib.timeout_add(round(seconds * 1000), lambda: loop.quit() or False)
    loop.run()


def until(predicate, seconds=6):
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        settle(.02)
    assert predicate(), 'Action did not finish'


def widgets(widget):
    yield widget
    child = widget.get_first_child()
    while child:
        yield from widgets(child)
        child = child.get_next_sibling()


# Use the home filesystem: GIO deliberately refuses Trash on /tmp's system mount.
with tempfile.TemporaryDirectory(prefix='gudfiles-action-sounds-', dir=Path.home() / '.cache') as directory:
    root = Path(directory)
    source, destination = root / 'source', root / 'destination'
    source.mkdir()
    destination.mkdir()
    data = root / 'data'
    data.mkdir()
    with patch.object(Path, 'home', return_value=root), patch.dict(os.environ, {'XDG_DATA_HOME': str(data)}):
        # Refuse to use the user's real Trash if GLib cached another data path.
        assert Path(GLib.get_user_data_dir()) == data
        request, _ = parse_args(['--demo', str(source)])
        app = PickerApplication(request, None)
        app.register(None)
        window = PickerWindow(app, request, None)
        window.present()
        settle()
        calls, errors = [], []
        with patch.object(window, '_play_sound', side_effect=calls.append), \
                patch.object(window, '_show_error', side_effect=lambda *args: errors.append(args)):
            try:
                files = [source / 'first.txt', source / 'second.txt']
                for path in files:
                    path.write_text('disposable fixture')
                window._refresh_files()
                dialog = window._confirm_remove(files)
                dialog.response(Gtk.ResponseType.CANCEL)
                settle()
                assert calls == [] and all(path.exists() for path in files)
                dialog = window._confirm_remove(files)
                dialog.response(Gtk.ResponseType.ACCEPT)
                until(lambda: not window.file_job_active)
                assert calls == ['trash'] and not any(path.exists() for path in files), (calls, errors)
                assert len(list((data / 'Trash/files').iterdir())) == 2

                doomed = source / 'delete.txt'
                doomed.write_text('delete fixture')
                window._confirm_remove([doomed], permanent=True).response(Gtk.ResponseType.ACCEPT)
                until(lambda: not window.file_job_active)
                assert calls == ['trash', 'delete'] and not doomed.exists()

                # A partially completed removal reports failure without success audio.
                partial = source / 'partial.txt'
                partial.write_text('partial fixture')
                window._confirm_remove([partial, source / 'missing.txt'], permanent=True).response(Gtk.ResponseType.ACCEPT)
                until(lambda: not window.file_job_active)
                assert errors and calls == ['trash', 'delete'] and not partial.exists()
                errors.clear()
                print('PASS: cancelled, successful multi-file Trash, permanent delete and partial failure audio routing')

                calls.clear()
                dropped = [source / 'drop-a.txt', source / 'drop-b.txt']
                for path in dropped:
                    path.write_text('drop fixture')
                assert window.drag_copy.submit(dropped, destination, force_copy=True)
                until(lambda: calls == ['drop'])
                assert all((destination / path.name).read_text() == 'drop fixture' for path in dropped)
                window._poll_transfers()
                window._poll_transfers()
                assert calls == ['drop']
                calls.clear()
                # Same-folder ordinary drops are no-ops.
                window.drag_copy.submit(dropped, source)
                until(lambda: not window.file_job_active)
                settle()
                assert calls == []

                staged_file = source / 'staged.txt'
                staged_file.write_text('staged fixture')
                queue = window.transfer_queue
                staged = queue.add([staged_file], destination, start=False)
                window._poll_transfers()
                assert calls == []
                queue.start(staged)
                try:
                    until(lambda: calls == ['complete'])
                except AssertionError as error:
                    raise AssertionError((calls, staged.state, staged.error, window.transfer_seen_states)) from error
                assert (destination / staged_file.name).read_text() == 'staged fixture'
                window._poll_transfers()
                assert calls == ['complete']
                calls.clear()
                failed = queue.add([source / 'missing-transfer'], destination, start=True)
                until(lambda: failed.state == 'failed' and not queue.active_jobs)
                window._poll_transfers()
                assert calls == []
                cancelled = queue.add([staged_file], destination, start=False)
                queue.cancel(cancelled)
                until(lambda: cancelled.state == 'cancelled' and not queue.active_jobs)
                window._poll_transfers()
                assert calls == []
                print('PASS: drop/copy completion once per batch; no sounds for repeat polling, no-op, staged, failed or cancelled transfers')

                window._set_file_preference('view_mode', 'columns', reload=False)
                before = window.current_dir, window.view_mode, window._selected_paths()
                with patch.dict(os.environ, {'OMARCHY_FILE_PICKER_AUTOMATION': 'context-menu'}):
                    window._show_context_menu(50, 50)
                settle()
                view = next(popover for popover in window.context_submenus
                            if any(isinstance(w, Gtk.Label) and w.get_text() == 'Sound Effects'
                                   for w in widgets(popover)))
                view.popup()
                settle()
                toggle = next(w for w in widgets(view) if isinstance(w, Gtk.Button)
                              and any(isinstance(label, Gtk.Label) and label.get_text() == 'Sound Effects'
                                      for label in widgets(w)))
                assert 'On' in [w.get_text() for w in widgets(toggle) if isinstance(w, Gtk.Label)]
                if capture := os.environ.get('SOUND_QA_SCREENSHOT'):
                    snapshot = Gtk.Snapshot.new()
                    Gtk.WidgetPaintable.new(view).snapshot(snapshot, view.get_width(), view.get_height())
                    node = snapshot.to_node()
                    assert node is not None
                    view.get_native().get_renderer().render_texture(node, None).save_to_png(capture)
                toggle.emit('clicked')
                settle()
                assert not window.action_sounds.enabled
                saved = json.loads(window.preferences_path.read_text())
                assert saved['sound_effects'] is False and saved['view_mode'] == 'columns'
                assert (window.current_dir, window.view_mode, window._selected_paths()) == before
                other = PickerWindow(app, PickerRequest(current_folder=source), None)
                other.present()
                settle()
                try:
                    assert not other.action_sounds.enabled
                    window._toggle_sound_effects()
                    assert other.action_sounds.enabled
                    other._set_file_preference('show_size', False, reload=False)
                    assert json.loads(window.preferences_path.read_text())['sound_effects'] is True
                finally:
                    other.destroy()
                print('PASS: mute persistence, other-window readback, unrelated preferences and selection preserved')
            finally:
                window.destroy()
                settle()
