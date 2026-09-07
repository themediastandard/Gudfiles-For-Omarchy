"""Real concurrent copies, native mode controls, saved preference and safe close."""
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
from gi.repository import Gio, GLib, Gtk

from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow
from omarchy_file_picker.theme import load_colors
from omarchy_file_picker.transfers import CHUNK_SIZE, TransferEngine


def settle(ms=60):
    loop = GLib.MainLoop()
    GLib.timeout_add(ms, lambda: loop.quit() or False)
    loop.run()


def until(predicate):
    deadline = time.monotonic() + 8
    while not predicate() and time.monotonic() < deadline:
        settle()
    assert predicate(), 'Transfer mode QA did not reach the expected state'


def float_fixtures():
    for client in json.loads(subprocess.check_output(['hyprctl', 'clients', '-j'])):
        if client['pid'] == os.getpid() and client['class'] == 'org.omarchy.FilePicker' and not client['floating']:
            selector = json.dumps('address:' + client['address'])
            subprocess.run(['hyprctl', 'dispatch', 'hl.dsp.window.float({action="toggle",window=' + selector + '})'],
                           check=True, stdout=subprocess.DEVNULL)


class MultiGateEngine(TransferEngine):
    def __init__(self):
        self.local = threading.local()
        self.lock = threading.Lock()
        self.gates = {}
        self.writes = {}
        self.release_all = threading.Event()

    def _copy_file(self, job, *args):
        self.local.job = job
        return super()._copy_file(job, *args)

    def _write(self, fd, data):
        super()._write(fd, data)
        job = self.local.job
        with self.lock:
            self.writes[job.id] = self.writes.get(job.id, 0) + 1
            gate = threading.Event() if self.writes[job.id] == 2 else None
            if gate:
                self.gates[job.id] = gate
        if gate:
            deadline = time.monotonic() + 12
            while not gate.wait(.01) and not self.release_all.is_set():
                if time.monotonic() > deadline:
                    raise OSError('Fixture I/O gate timed out')


colors = load_colors()
with tempfile.TemporaryDirectory(prefix='picker-transfer-modes-') as temp, \
        patch.object(Path, 'home', return_value=Path(temp)), \
        patch.object(Gio.VolumeMonitor, 'get_mounts', return_value=[]), \
        patch('omarchy_file_picker.picker.load_colors', return_value=colors):
    root = Path(temp)
    source, dest = root / 'source', root / 'destination'
    source.mkdir()
    dest.mkdir()
    data = bytes(range(256)) * 16384
    paths = [source / f'Sequence {index:02}.bin' for index in range(1, 6)]
    for path in paths:
        path.write_bytes(data)
    request = PickerRequest(current_folder=dest, explorer=True, multiple=True, title='Transfer modes QA')
    app = PickerApplication(request, None)
    app.register(None)
    window = PickerWindow(app, request, None)
    errors = []
    window._show_error = lambda *args: errors.append(args)
    queue = window.transfer_queue
    engine = queue.engine = MultiGateEngine()
    window.present()
    settle(150)
    float_fixtures()
    settle()
    geometry = window.get_width(), window.get_height()
    try:
        jobs = [queue.add([path], dest) for path in paths]
        manager = window._show_transfers()
        float_fixtures()
        settle(150)
        manager_geometry = manager.get_width(), manager.get_height()
        assert window.transfer_mode_buttons['queue'].get_active()
        window.transfer_mode_buttons['all'].emit('clicked')
        assert queue.mode == 'all' and window.transfer_start.get_label() == 'Start all'
        assert not engine.gates and all(job.state == 'queued' for job in jobs)
        assert json.loads(window.preferences_path.read_text())['transfer_mode'] == 'all'
        window.transfer_start.emit('clicked')
        until(lambda: len(engine.gates) == 3)
        window._poll_transfers()
        assert len(queue.active_jobs) == 3
        assert not window.transfer_start.get_sensitive()
        assert '3 running' in window.transfer_summary.get_text()
        assert window.transfer_pause.get_label() == 'Pause all'
        assert all(job.state == 'waiting' for job in jobs[3:])
        assert (window.get_width(), window.get_height()) == geometry
        assert (manager.get_width(), manager.get_height()) == manager_geometry
        capture = os.environ.get('TRANSFER_MODES_QA_SCREENSHOT')
        if capture:
            settle(150)
            snapshot = Gtk.Snapshot.new()
            Gtk.WidgetPaintable.new(manager).snapshot(snapshot, manager.get_width(), manager.get_height())
            node = snapshot.to_node()
            assert node is not None
            manager.get_renderer().render_texture(node, None).save_to_png(capture)

        # The row Pause applies to one transfer in All mode; the remaining
        # workers continue, and another already-authorized transfer gets its slot.
        window.transfer_rows[jobs[0].id].primary.emit('clicked')
        assert jobs[0].state == 'pausing'
        engine.gates[jobs[0].id].set()
        until(lambda: jobs[0].state == 'paused' and jobs[3].id in engine.gates)
        assert all(job.state == 'running' for job in jobs[1:4])
        assert jobs[4].state == 'waiting'
        window.transfer_mode_buttons['queue'].emit('clicked')
        assert queue.mode == 'queue'
        assert '3 finishing' in window.transfer_summary.get_text()
        for job in jobs[1:3]:
            engine.gates[job.id].set()
        until(lambda: len(queue.active_jobs) == 1)
        assert jobs[4].id not in engine.gates
        engine.gates[jobs[3].id].set()
        until(lambda: jobs[4].id in engine.gates)
        assert len(queue.active_jobs) == 1
        window._poll_transfers()
        window.transfer_rows[jobs[0].id].primary.emit('clicked')
        assert jobs[0].state == 'waiting'
        engine.gates[jobs[4].id].set()
        until(lambda: not queue.unfinished)
        assert jobs[0].verified_bytes == CHUNK_SIZE * 2
        assert jobs[0].written_bytes == len(data) - CHUNK_SIZE * 2
        assert all((dest / path.name).read_bytes() == data and path.read_bytes() == data for path in paths)

        # Closing waits for every parallel worker, even when some stop first.
        closing_dest = root / 'cancel destination'
        closing_dest.mkdir()
        closing = [queue.add([path], closing_dest) for path in paths[:3]]
        window.transfer_mode_buttons['all'].emit('clicked')
        assert all(job.state == 'queued' for job in closing)
        window.transfer_start.emit('clicked')
        until(lambda: all(job.id in engine.gates for job in closing))
        closed = []
        assert window._guard_transfer_close(lambda: closed.append(True))
        window.transfer_close_confirm.emit('clicked')
        assert all(job.state == 'cancelling' for job in closing)
        assert not window.transfer_mode_buttons['queue'].get_sensitive()
        for job in closing[:2]:
            engine.gates[job.id].set()
        until(lambda: len(queue.active_jobs) == 1)
        assert not closed
        engine.gates[closing[2].id].set()
        until(lambda: closed)
        assert all(job.state == 'cancelled' for job in closing)
        assert not queue.unfinished and not list(closing_dest.iterdir())
        assert all(path.read_bytes() == data for path in paths)
        assert not errors, errors
    finally:
        engine.release_all.set()
        queue.pause()
        until(lambda: not queue.active_jobs)
        window.destroy()

    # A new Files window restores the user's mode without starting anything.
    restored = PickerWindow(app, request, None)
    restored.present()
    settle(150)
    try:
        assert restored.transfer_queue.mode == 'all'
        assert not restored.transfer_queue.unfinished
    finally:
        restored.destroy()
    print('PASS: native Queue/All toggle, bounded real concurrent copies, individual pause, safe mode switching, '
          'verified resume, stable geometry, all-worker close/cleanup and saved mode')
