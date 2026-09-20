"""Native queue controls, real partial recovery, clipboard/move and close behavior.

Uses disposable files and real GTK signals, not physical mouse injection.
"""
import errno
import json
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gdk, Gio, GLib, Gtk

from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow
from omarchy_file_picker.ratings import EMPTY
from omarchy_file_picker.theme import load_colors
from omarchy_file_picker.transfers import TransferEngine, TransferQueue, rename_noreplace


def settle(ms=60):
    loop = GLib.MainLoop()
    GLib.timeout_add(ms, lambda: loop.quit() or False)
    loop.run()


def until(predicate):
    deadline = time.monotonic() + 8
    while not predicate() and time.monotonic() < deadline:
        settle()
    assert predicate(), 'Native transfer did not reach the expected state'


def float_fixture_windows():
    for client in json.loads(subprocess.check_output(['hyprctl', 'clients', '-j'])):
        if client['pid'] == os.getpid() and client['class'] == 'org.omarchy.FilePicker' and not client['floating']:
            selector = json.dumps('address:' + client['address'])
            subprocess.run(['hyprctl', 'dispatch', 'hl.dsp.window.float({action="toggle",window=' + selector + '})'],
                           check=True, stdout=subprocess.DEVNULL)


class GateEngine(TransferEngine):
    def __init__(self):
        self.gate = threading.Event()
        self.release = threading.Event()
        self.gated = False

    def _write(self, fd, data):
        super()._write(fd, data)
        if not self.gated:
            self.gated = True
            self.gate.set()
            if not self.release.wait(6):
                raise OSError('QA gate timed out')


colors = load_colors()
with tempfile.TemporaryDirectory(prefix='picker-transfer-qa-') as temp, \
        patch.object(Path, 'home', return_value=Path(temp)), \
        patch.object(Gio.VolumeMonitor, 'get_mounts', return_value=[]), \
        patch('omarchy_file_picker.picker.load_colors', return_value=colors):
    root = Path(temp)
    source, dest = root / 'Camera originals', root / 'Working drive'
    source.mkdir()
    dest.mkdir()
    footage = source / 'A001 — mountain road.mov'
    data = bytes(range(256)) * 16384
    footage.write_bytes(data)
    notes = source / 'Edit notes.txt'
    notes.write_text('Fixture notes')
    request = PickerRequest(current_folder=dest, explorer=True, multiple=True, title='Files transfer QA')
    app = PickerApplication(request, None)
    app.register(None)
    window = PickerWindow(app, request, None)
    errors = []
    window._show_error = lambda *args: errors.append(args)
    engine = GateEngine()
    window.transfer_queue = queue = TransferQueue(engine)
    window.present()
    settle(150)
    float_fixture_windows()
    settle()
    geometry = window.get_width(), window.get_height()
    try:
        window._copy_files([footage])
        window._on_key_pressed(None, Gdk.KEY_V, 0, Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK)
        until(lambda: len(queue.jobs) == 1)
        first = queue.jobs[0]
        assert first.state == 'queued' and not engine.gate.is_set()
        assert not list(dest.iterdir())
        manager = window.transfer_window
        float_fixture_windows()
        settle()
        manager_geometry = manager.get_width(), manager.get_height()
        row = window.transfer_rows[first.id]
        assert row.primary.get_label() == 'Start'
        row.primary.emit('clicked')
        until(engine.gate.is_set)
        window._poll_transfers()
        assert row.primary.get_label() == 'Pause'
        row.primary.emit('clicked')
        assert first.state == 'pausing'
        engine.release.set()
        until(lambda: first.state == 'paused')
        window._poll_transfers()
        assert row.primary.get_label() == 'Resume'
        assert not (dest / footage.name).exists()
        assert 0 < first.done_bytes < first.total_bytes
        partial_bytes = (dest / first.stage_name / '0').stat().st_size

        # Keep browsing and selecting in each view while a resumable job exists.
        for mode in ('grid', 'list', 'columns'):
            window._set_view(mode)
            window.navigate(source)
            settle()
            window.flow.select_child(window.children_by_path[notes])
            assert window._selected_paths() == [notes]
            assert (window.get_width(), window.get_height()) == geometry
        window.navigate(dest)
        window._copy_files([notes])
        window._paste_files(queued=True)
        until(lambda: len(queue.jobs) == 2)
        second = queue.jobs[1]
        assert second.state == 'queued'
        capture = os.environ.get('TRANSFERS_QA_SCREENSHOT')
        if capture:
            settle(180)
            snapshot = Gtk.Snapshot.new()
            Gtk.WidgetPaintable.new(manager).snapshot(snapshot, manager.get_width(), manager.get_height())
            manager.get_renderer().render_texture(snapshot.to_node(), None).save_to_png(str(Path(capture).with_stem(Path(capture).stem + '-paused')))
        # Hiding the panel leaves the paused queue accessible from the header.
        manager.close()
        assert not manager.get_visible() and queue.unfinished
        window.transfer_button.emit('clicked')
        assert manager.get_visible()
        window.transfer_rows[first.id].primary.emit('clicked')
        until(lambda: first.state == 'completed')
        window._poll_transfers()
        assert first.written_bytes == len(data) - partial_bytes
        assert (dest / footage.name).read_bytes() == data
        assert second.state == 'queued' and not (dest / notes.name).exists()
        assert not errors, errors

        # One failed copy retains bytes; Resume checks them. Corruption needs an
        # explicitly different Restart action, which really starts at byte zero.
        def fail(fd, block):
            TransferEngine._write(fd, block[:4])
            raise OSError(errno.ENOSPC, 'Fixture destination is full')
        with patch.object(engine, '_write', side_effect=fail):
            window.transfer_rows[second.id].primary.emit('clicked')
            until(lambda: second.state == 'failed')
        window._poll_transfers()
        failed_row = window.transfer_rows[second.id]
        assert failed_row.primary.get_label() == 'Resume'
        assert failed_row.error.get_visible()
        (dest / second.stage_name / '0').write_bytes(b'WRNG')
        failed_row.primary.emit('clicked')
        until(lambda: second.state == 'failed' and second.restart_required)
        window._poll_transfers()
        assert not failed_row.primary.get_visible() and failed_row.restart.get_visible()
        failed_row.restart.emit('clicked')
        until(lambda: second.state == 'completed')
        assert (dest / notes.name).read_text() == notes.read_text()
        assert second.written_bytes == notes.stat().st_size

        # A partial cut migrates only completed annotations and removes those
        # sources from our own cut clipboard. A newer clipboard stays untouched.
        moving = [source / name for name in ('Move A.txt', 'Move B.txt')]
        for path in moving:
            path.write_text('move fixture')
        window.ratings.set_many(moving, stars=4, color='blue')
        window._copy_files(moving, cut=True)
        window._paste_files(queued=True)
        until(lambda: len(queue.jobs) == 3)
        moving_job = queue.jobs[-1]
        def fail_second(srcfd, name, dstfd, target):
            if target == moving[1].name:
                raise OSError(errno.EIO, 'Fixture disconnect')
            rename_noreplace(srcfd, name, dstfd, target)
        with patch('omarchy_file_picker.transfers.rename_noreplace', side_effect=fail_second):
            window.transfer_rows[moving_job.id].primary.emit('clicked')
            until(lambda: moving_job.state == 'failed')
        window._poll_transfers()
        all_paths = moving + [dest / path.name for path in moving]
        window.ratings.refresh(all_paths)
        assert window.ratings.get(moving[0]) == EMPTY
        assert window.ratings.get(dest / moving[0].name) == (4, 'blue', False)
        assert window.ratings.get(moving[1]) == (4, 'blue', False)
        clipboard_data = []
        window.get_clipboard().read_async(['x-special/gnome-copied-files'], GLib.PRIORITY_DEFAULT, None,
            lambda clip, res: clipboard_data.append(clip.read_finish(res)[0].read_bytes(8192, None).get_data().decode()))
        until(lambda: clipboard_data)
        assert clipboard_data[0] == 'cut\n' + moving[1].as_uri(), clipboard_data
        window._copy_files([notes])
        new_provider = window.get_clipboard().get_content()
        window.transfer_rows[moving_job.id].primary.emit('clicked')
        until(lambda: moving_job.state == 'completed')
        window._poll_transfers()
        assert window.get_clipboard().get_content() == new_provider
        window.ratings.refresh(all_paths)
        assert window.ratings.get(dest / moving[1].name) == (4, 'blue', False)

        # Many rows and long names stay inside the transfer scroller; the Files
        # window and preview area do not grow with queue/progress content.
        for index in range(8):
            queue.add([source / ('Very long staged project name ' * 5 + str(index))], dest)
        window._poll_transfers()
        settle(180)
        assert (manager.get_width(), manager.get_height()) == manager_geometry
        assert (window.get_width(), window.get_height()) == geometry
        capture = os.environ.get('TRANSFERS_QA_SCREENSHOT')
        if capture:
            snapshot = Gtk.Snapshot.new()
            Gtk.WidgetPaintable.new(manager).snapshot(snapshot, manager.get_width(), manager.get_height())
            node = snapshot.to_node()
            assert node is not None
            manager.get_renderer().render_texture(node, None).save_to_png(capture)

        # Closing Files stops queue scheduling, retains it on Keep open, and
        # waits for cancellation before invoking the actual close callback.
        closed = []
        assert window._guard_transfer_close(lambda: closed.append(True))
        assert window.transfer_close_box.get_visible() and queue.held
        window.transfer_keep.emit('clicked')
        assert queue.unfinished and not closed
        assert window._guard_transfer_close(lambda: closed.append(True))
        window.transfer_close_confirm.emit('clicked')
        until(lambda: closed)
        assert not queue.unfinished and queue.active is None
        assert (dest / footage.name).read_bytes() == data

        # Files cannot disappear while a blocked filesystem call is still
        # processing a cancellation. Close happens only after it returns.
        engine.gated = False
        engine.gate.clear()
        engine.release.clear()
        blocked_source = source / 'Close during copy.mov'
        blocked_source.write_bytes(data)
        blocked = queue.add([blocked_source], dest, start=True)
        queue.held = False
        queue.start(blocked)
        until(engine.gate.is_set)
        assert window._guard_transfer_close(lambda: closed.append(True))
        window.transfer_close_confirm.emit('clicked')
        settle()
        assert len(closed) == 1 and queue.active is blocked and blocked.state == 'cancelling'
        engine.release.set()
        until(lambda: len(closed) == 2)
        assert blocked.state == 'cancelled' and blocked_source.read_bytes() == data
        assert not (dest / blocked_source.name).exists() and not blocked.stage_name

        # Cleanup failure offers an explicit leave-partials exit, never a silent
        # lost queue or deletion of unexpected files in a staging directory.
        cleanup_source = source / 'Cleanup sample.txt'
        cleanup_source.write_text('cleanup fixture')
        with patch.object(engine, '_write', side_effect=fail):
            damaged = queue.add([cleanup_source], dest)
            queue.start(damaged)
            until(lambda: damaged.state == 'failed')
        stage = dest / damaged.stage_name
        unexpected = stage / 'unowned.txt'
        unexpected.write_text('keep this')
        assert window._guard_transfer_close(lambda: closed.append(True))
        window.transfer_close_confirm.emit('clicked')
        until(lambda: window.transfer_cleanup_blocked)
        window._poll_transfers()
        assert len(closed) == 2 and window.transfer_leave.get_visible()
        assert unexpected.read_text() == 'keep this'
        window.transfer_leave.emit('clicked')
        until(lambda: len(closed) == 3)
        assert stage.is_dir() and cleanup_source.read_text() == 'cleanup fixture'
        assert queue.unfinished and queue.active is None
        assert damaged.state == 'paused'
        assert not errors, errors
        print('PASS: native stage/start/pause/resume/restart/cancel; verified partial bytes; sequential queue; '
              'three-view browsing; clipboard ownership; partial move ratings; bounded geometry; close guard and cleanup')
    finally:
        engine.release.set()
        queue.pause()
        until(lambda: queue.active is None)
        window.destroy()
