"""Native keep-originals action after a paused verified cross-drive move."""
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import GLib, Gtk
from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow
from omarchy_file_picker.transfers import TransferEngine


def settle_until(predicate):
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        while GLib.MainContext.default().pending():
            GLib.MainContext.default().iteration(False)
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError('move-retention UI timed out')


def descendants(widget):
    yield widget
    child = widget.get_first_child()
    while child:
        yield from descendants(child)
        child = child.get_next_sibling()


class PauseHeldEngine(TransferEngine):
    def run(self, job):
        def pause(current):
            if current.items and current.items[0].quarantine_id:
                current.stop.set()
        job.on_checkpoint = pause
        super().run(job)


failures = []
def report_exception(*args):
    failures.append(args)
    sys.__excepthook__(*args)
sys.excepthook = report_exception
with tempfile.TemporaryDirectory(prefix='gudfiles-retention-ui-') as temporary, \
        tempfile.TemporaryDirectory(prefix='gudfiles-retention-dest-', dir='/dev/shm') as target:
    home, destination = Path(temporary), Path(target)
    source = home / 'clip.mov'
    source.write_bytes(b'footage')
    request = PickerRequest(current_folder=home, explorer=True, multiple=True)
    app = PickerApplication(request, None)
    app.register(None)
    with patch.object(Path, 'home', return_value=home), \
            patch.dict(os.environ, {'XDG_STATE_HOME': str(home / 'state')}), \
            patch.object(PickerWindow, '_play_sound'):
        window = PickerWindow(app, request, None)
        window.present()
        window.transfer_queue.engine = PauseHeldEngine()
        job = window.transfer_queue.add([source], destination, cut=True, start=True)
        settle_until(lambda: job.state == 'paused' and not window.transfer_queue.active_jobs)
        assert not source.exists()
        source.write_bytes(b'new recording')
        window._show_transfers()
        window._poll_transfers()
        row = window.transfer_rows[job.id]
        assert row.keep_originals.get_visible() and row.keep_originals.get_sensitive()
        row.keep_originals.emit('clicked')
        settle_until(lambda: job.state in {'cancelled', 'failed'} and not window.transfer_queue.active_jobs)
        assert job.state == 'cancelled', job.error
        window._poll_transfers()
        retained = source.with_name('clip (remaining 1).mov')
        assert retained.read_bytes() == b'footage'
        assert source.read_bytes() == b'new recording'
        assert (destination/source.name).read_bytes() == b'footage'
        assert not window.transfer_queue.unfinished
        labels = [node.get_text() for node in descendants(row)
                  if isinstance(node, Gtk.Label) and node.get_visible()]
        assert any(str(retained) in text for text in labels), labels
        assert retained in window.children_by_path
        assert not job.completed, 'Keeping originals must not announce a completed move'
        window.destroy()
        settle_until(lambda: True)
assert not failures, failures
print('PASS: native Keep remaining originals, collision-safe retained path visible, browser refreshed, exact preserved bytes')
