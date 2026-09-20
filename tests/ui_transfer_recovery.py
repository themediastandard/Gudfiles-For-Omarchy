"""Native recovery banner, explicit Resume and Save queue & close controls."""
import os
from pathlib import Path
import tempfile
import threading
import time
from unittest.mock import patch

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gio, GLib
from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow
from omarchy_file_picker.transfers import TransferEngine


def settle(ms=40):
    loop = GLib.MainLoop()
    GLib.timeout_add(ms, lambda: loop.quit() or False)
    loop.run()


def until(predicate):
    deadline = time.monotonic() + 10
    while not predicate() and time.monotonic() < deadline:
        settle()
    assert predicate(), 'Recovery UI did not reach its expected state'


class GateEngine(TransferEngine):
    def __init__(self):
        self.ready = threading.Event()
        self.release = threading.Event()

    def _write(self, fd, data):
        super()._write(fd, data)
        if not self.ready.is_set():
            self.ready.set()
            if not self.release.wait(10):
                raise OSError('QA gate timed out')


with tempfile.TemporaryDirectory(prefix='gudfiles-recovery-ui-') as temp, \
        patch.object(Path, 'home', return_value=Path(temp)), \
        patch.dict(os.environ, {'XDG_STATE_HOME': str(Path(temp)/'state')}), \
        patch.object(Gio.VolumeMonitor, 'get_mounts', return_value=[]), \
        patch.object(PickerWindow, '_play_sound') as sounds:
    root = Path(temp)
    source = root/'footage.mov'
    source.write_bytes(b'12345678' * 400000)
    destination = root/'destination'
    destination.mkdir()
    request = PickerRequest(current_folder=destination, explorer=True, multiple=True, title='Recovery QA')
    app = PickerApplication(request, None)
    app.register(None)
    first = PickerWindow(app, request, None)
    first.present()
    engine = first.transfer_queue.engine = GateEngine()
    job = first.transfer_queue.add([source], destination, start=True)
    until(engine.ready.is_set)
    closed = []
    assert first._guard_transfer_close(lambda: (closed.append(True), first.destroy()))
    first.transfer_save.emit('clicked')
    settle()
    assert not closed and first.transfer_save_close
    engine.release.set()
    until(lambda: bool(closed))
    until(lambda: not first.transfer_queue.active_jobs)
    assert not (destination/source.name).exists()

    second = PickerWindow(app, request, None)
    second.present()
    until(lambda: second.transfer_window is not None and second.transfer_window.get_visible())
    recovered, = second.transfer_queue.jobs
    assert recovered.id == job.id and recovered.state == 'paused'
    assert second.transfer_queue.held
    row = second.transfer_rows[recovered.id]
    assert row.primary.get_visible() and row.primary.get_label() == 'Resume'
    assert 'Recovered' in row.detail.get_text()
    assert not sounds.called
    row.primary.emit('clicked')
    until(lambda: recovered.state == 'completed' and not second.transfer_queue.active_jobs)
    second._poll_transfers()
    assert (destination/source.name).read_bytes() == source.read_bytes()
    assert recovered.verified_bytes > 0
    assert sounds.call_count == 1
    second.destroy()
    settle()
    if Path('/dev/shm').is_dir() and Path('/dev/shm').stat().st_dev != root.stat().st_dev:
        with tempfile.TemporaryDirectory(dir='/dev/shm', prefix='gudfiles-recovery-ui-') as remote:
            class EditedSource(TransferEngine):
                def _record_published(self, job, item, expected_id):
                    super()._record_published(job, item, expected_id)
                    item.source.write_bytes(b'edited original')

            third = PickerWindow(app, request, None)
            third.present()
            third.transfer_queue.engine = EditedSource()
            move = third.transfer_queue.add([source], Path(remote), True, start=True)
            until(lambda: move.state == 'failed' and not third.transfer_queue.active_jobs)
            third._show_transfers()
            row = third.transfer_rows[move.id]
            assert row.keep_originals.get_visible() and row.keep_originals.get_sensitive()
            assert not row.restart.get_visible()
            row.keep_originals.emit('clicked')
            until(lambda: move.state == 'cancelled' and not third.transfer_queue.active_jobs)
            third._poll_transfers()
            assert source.read_bytes() == b'edited original'
            assert (Path(remote)/source.name).read_bytes() == (destination/source.name).read_bytes()
            assert move.items[0].abandoned and not move.completed
            assert sounds.call_count == 1
            third.destroy()
            settle()
    label_destination = root/'label-destination'
    label_destination.mkdir()
    fourth = PickerWindow(app, request, None)
    fourth.present()
    fourth.ratings.set_many([source], stars=4)
    migrate = fourth._creative_transfer_paths_renamed
    attempts = []
    def fail_labels_once(mapping, receipt):
        attempts.append(receipt)
        return False if len(attempts) == 1 else migrate(mapping, receipt)
    fourth._creative_transfer_paths_renamed = fail_labels_once
    moved = fourth.transfer_queue.add([source], label_destination, True, start=True)
    until(lambda: moved.state == 'completed' and not fourth.transfer_queue.active_jobs)
    fourth._show_transfers()
    row = fourth.transfer_rows[moved.id]
    assert row.error.get_visible() and 'labels could not be saved' in row.error.get_text()
    assert row.retry_labels.get_visible()
    fourth._clear_transfers()
    assert moved in fourth.transfer_queue.jobs
    row.retry_labels.emit('clicked')
    assert not row.retry_labels.get_visible() and not fourth.transfer_queue.annotation_failures
    fourth.ratings.refresh([label_destination/source.name])
    assert fourth.ratings.get(label_destination/source.name)[0] == 4
    fourth.destroy()
    settle()
print('PASS: native recovery, Keep remaining originals, durable label failure and Retry labels')
