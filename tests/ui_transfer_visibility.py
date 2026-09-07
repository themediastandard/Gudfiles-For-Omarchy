"""Automatic transfer panels close after quick work, preserving review/attention."""
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gio, GLib, Gtk

from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow
from omarchy_file_picker.theme import load_colors
from omarchy_file_picker.transfers import TransferEngine


def settle():
    loop = GLib.MainLoop()
    GLib.timeout_add(60, lambda: loop.quit() or False)
    loop.run()


def until(predicate):
    deadline = time.monotonic() + 8
    while not predicate() and time.monotonic() < deadline:
        settle()
    assert predicate(), 'Transfer visibility QA timed out'


class GateEngine(TransferEngine):
    def __init__(self):
        self.gates = {}
        self.release_all = threading.Event()
        self.fail = False

    def _copy_file(self, job, *args):
        if job.id not in self.gates:
            gate = self.gates[job.id] = threading.Event()
            deadline = time.monotonic() + 8
            while not gate.wait(.01) and not self.release_all.is_set():
                if time.monotonic() > deadline:
                    raise OSError('Fixture gate timed out')
            if self.fail:
                raise OSError('Fixture unavailable destination')
        return super()._copy_file(job, *args)


colors = load_colors()
with tempfile.TemporaryDirectory(prefix='picker-transfer-visibility-') as temp, \
        patch.object(Path, 'home', return_value=Path(temp)), \
        patch.object(Gio.VolumeMonitor, 'get_mounts', return_value=[]), \
        patch('omarchy_file_picker.picker.load_colors', return_value=colors):
    root = Path(temp)
    source = root / 'source.txt'
    source.write_text('fixture')
    request = PickerRequest(current_folder=root, explorer=True, multiple=True)
    app = PickerApplication(request, None)
    app.register(None)
    window = PickerWindow(app, request, None)
    window.present()
    settle()
    queue = window.transfer_queue
    engine = queue.engine = GateEngine()
    index = 0

    def add(*, start=True):
        global index
        index += 1
        dest = root / f'destination-{index}'
        dest.mkdir()
        return queue.add([source], dest, start=start)

    def running():
        job = add()
        until(lambda: job.id in engine.gates)
        window._show_transfers(automatic_job=job)
        assert window.transfer_window.get_visible()
        return job

    def finish(job):
        engine.gates[job.id].set()
        until(lambda: job not in queue.active_jobs and job.state == 'completed')
        window._poll_transfers()
        assert job.completed[source].read_text() == 'fixture'

    try:
        # Copies done before the idle show request should not flash a window.
        engine.release_all.set()
        job = add()
        until(lambda: job.state == 'completed' and not queue.active_jobs)
        assert window._show_transfers(automatic_job=job) is None
        assert window.transfer_window is None
        engine.release_all.clear()
        print('PASS: already-complete quick copies never open a panel')

        # Force completion between the visibility decision and first poll.
        # The resulting hidden window still needs a valid native surface when
        # the Files session later destroys its application windows.
        job = add()
        until(lambda: job.id in engine.gates)
        poll = window._poll_transfers
        def complete_during_construction():
            engine.gates[job.id].set()
            deadline = time.monotonic() + 5
            while job in queue.active_jobs and time.monotonic() < deadline:
                time.sleep(.001)
            assert job.state == 'completed'
            return poll()
        with patch.object(window, '_poll_transfers', side_effect=complete_during_construction):
            manager = window._show_transfers(automatic_job=job)
        assert manager.get_realized() and not manager.get_visible()
        print('PASS: completion during window construction creates a safe hidden native surface')

        job = running()
        assert window.transfer_auto_close
        finish(job)
        assert not window.transfer_window.get_visible()
        window.transfer_button.emit('clicked')
        assert window.transfer_window.get_visible()
        assert job.id in window.transfer_rows
        window.transfer_window.close()
        print('PASS: quick automatic panels hide, with history available from Transfers')

        # Exercise the exact five-minute boundary without sleeping five minutes.
        job = running()
        with queue.lock:
            job.elapsed_seconds = 299
            job.active_since = time.monotonic()
        window._poll_transfers()
        assert window.transfer_auto_close
        with queue.lock:
            job.elapsed_seconds = 300
        window._poll_transfers()
        assert not window.transfer_auto_close
        finish(job)
        assert window.transfer_window.get_visible()
        window.transfer_window.close()
        # An old long-running receipt must not pin the next quick transfer.
        job = running()
        finish(job)
        assert not window.transfer_window.get_visible()
        print('PASS: five-minute transfers stay open after completion; later quick transfers close')

        job = running()
        window.transfer_button.emit('clicked')
        finish(job)
        assert window.transfer_window.get_visible()
        window.transfer_window.close()
        print('PASS: manually opening the automatic panel keeps it open')

        queue.set_mode('all')
        first, second = running(), running()
        finish(first)
        assert window.transfer_window.get_visible()
        finish(second)
        assert not window.transfer_window.get_visible()
        print('PASS: All mode waits for every active transfer before hiding')

        job = running()
        queue.pause(job)
        engine.gates[job.id].set()
        until(lambda: job.state == 'paused' and not queue.active_jobs)
        window._poll_transfers()
        assert window.transfer_window.get_visible() and not window.transfer_auto_close
        queue.start(job)
        finish(job)
        assert window.transfer_window.get_visible()
        window.transfer_window.close()
        print('PASS: pause and resume preserve the review panel')

        job = running()
        engine.fail = True
        engine.gates[job.id].set()
        until(lambda: job.state == 'failed' and not queue.active_jobs)
        window._poll_transfers()
        assert window.transfer_window.get_visible() and not window.transfer_auto_close
        queue.cancel(job)
        until(lambda: not queue.active_jobs and job.state == 'cancelled')
        engine.fail = False
        window.transfer_window.close()
        print('PASS: failures stay visible until reviewed')

        staged = add(start=False)
        window._show_transfers()
        window._poll_transfers()
        assert staged.state == 'queued' and window.transfer_window.get_visible()
        assert staged.id not in engine.gates
        print('PASS: manually staged queues remain visible and do not start automatically')
    finally:
        engine.release_all.set()
        for job in queue.jobs:
            queue.cancel(job)
        until(lambda: not queue.active_jobs)
        window.destroy()
