"""Native destination picking and real copy/move outcomes using disposable files.

PYTHONPATH=. python tests/ui_transfer_destination.py
TRANSFER_DESTINATION_SCREENSHOTS=/tmp/destinations optionally captures the UI.
"""
import io
import os
from pathlib import Path
import sys
import tempfile
import time
from contextlib import redirect_stdout
from unittest.mock import patch

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import GLib, Gtk

from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow
from omarchy_file_picker.theme import DEFAULT_COLORS, load_colors


callback_errors = []
original_hook = sys.excepthook
def callback_error(kind, value, traceback):
    callback_errors.append(value)
    original_hook(kind, value, traceback)
sys.excepthook = callback_error


def settle(ms=120):
    loop = GLib.MainLoop()
    GLib.timeout_add(ms, lambda: loop.quit() or False)
    loop.run()
    assert not callback_errors, callback_errors


def wait_for(predicate):
    end = time.monotonic() + 10
    while not predicate():
        assert time.monotonic() < end, 'Timed out waiting for transfer'
        settle(30)
    settle()


def descendants(widget):
    yield widget
    child = widget.get_first_child()
    while child:
        yield from descendants(child)
        child = child.get_next_sibling()


def menu_action(window, name):
    return next(widget for widget in descendants(window.context_popover)
                if isinstance(widget, Gtk.Button) and any(
                    isinstance(label, Gtk.Label) and label.get_text() == name
                    for label in descendants(widget)))


class Gesture:
    def set_state(self, state):
        assert state == Gtk.EventSequenceState.CLAIMED


def select(window, paths):
    window.flow.unselect_all()
    for path in paths:
        window.flow.select_child(window.children_by_path[path])
    settle()


def open_destination(window, paths, cut=False):
    select(window, paths)
    tile = window.children_by_path[paths[0]]
    valid, bounds = tile.compute_bounds(window.browser_stack)
    assert valid
    window._on_context_pressed(Gesture(), 1,
                               bounds.get_x() + bounds.get_width() / 2,
                               bounds.get_y() + bounds.get_height() / 2)
    assert set(window._selected_paths()) == set(paths), 'Right-click lost multi-selection'
    settle()
    menu_action(window, 'Move to…' if cut else 'Copy to…').emit('clicked')
    settle()
    chooser = window.destination_picker
    assert chooser is not None and chooser.get_visible()
    assert chooser.get_modal() and chooser.get_transient_for() is window
    assert chooser.request.directory and not chooser.request.multiple
    assert chooser.accept_button.get_label() == ('Move here' if cut else 'Copy here')
    assert chooser.transfer_queue is not window.transfer_queue
    return chooser


def capture(window, name):
    target = os.environ.get('TRANSFER_DESTINATION_SCREENSHOTS')
    if not target:
        return
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    settle()
    snapshot = Gtk.Snapshot.new()
    Gtk.WidgetPaintable.new(window).snapshot(snapshot, window.get_width(), window.get_height())
    node = snapshot.to_node()
    assert node is not None
    window.get_renderer().render_texture(node, None).save_to_png(str(target / f'{name}.png'))


with tempfile.TemporaryDirectory(prefix='gudfiles-destination-') as temporary:
    root = Path(temporary)
    palettes = [('active', load_colors()), ('light', DEFAULT_COLORS)]
    app = PickerApplication(PickerRequest(current_folder=root, explorer=True), None)
    app.register(None)
    with patch.object(Path, 'home', return_value=root), \
         patch('omarchy_file_picker.picker.thumbnail_file', return_value=None), \
         patch('omarchy_file_picker.sound_effects.ActionSounds.play'), \
         patch.object(app, 'quit') as quit_app, redirect_stdout(io.StringIO()) as output:
        for palette, colors in palettes:
            for view in ('grid', 'list', 'columns'):
                source = root / palette / view / 'source'
                destination = source.parent / 'copies'
                moved = source.parent / 'moved'
                source.mkdir(parents=True)
                destination.mkdir()
                moved.mkdir()
                first = source / 'a.txt'
                first.write_bytes(b'original bytes\x00\xff')
                folder = source / 'Folder'
                folder.mkdir()
                (folder / 'nested.txt').write_text('nested bytes')
                (folder / 'Empty').mkdir()
                (destination / first.name).write_text('keep existing')
                with patch('omarchy_file_picker.picker.load_colors', return_value=colors):
                    window = PickerWindow(app, PickerRequest(current_folder=source, explorer=True,
                                                            multiple=True), None)
                    window.set_default_size(820, 650)
                    window.present()
                    window._set_view(view)
                    settle(250)
                    window.get_clipboard().set('leave this clipboard alone')
                    provider = window.get_clipboard().get_content()
                    errors = []
                    window._show_error = lambda *args: errors.append(args)

                    # Cancelling and titlebar-close cannot write or end the host app.
                    chooser = open_destination(window, [first])
                    assert not window.transfer_queue.jobs
                    chooser._on_key_pressed(None, 0xff1b, 0, 0)  # Escape
                    settle()
                    assert window.destination_picker is None and first.exists()
                    assert not window.transfer_queue.jobs
                    chooser = open_destination(window, [first], cut=True)
                    chooser.close()
                    settle()
                    assert window.destination_picker is None and first.exists()

                    chooser = open_destination(window, [first, folder])
                    assert window._choose_transfer_destination([first]) is chooser
                    # Selection changes while the prompt is open cannot change its sources.
                    window.flow.unselect_all()
                    chooser.navigate(destination.parent)
                    select(chooser, [destination])
                    capture(chooser, f'{palette}-{view}-copy')
                    chooser.accept_button.emit('clicked')
                    settle()
                    job = window.transfer_queue.jobs[-1]
                    wait_for(lambda: job.state in {'completed', 'failed'})
                    assert job.state == 'completed', job.error
                    assert set(job.completed) == {first, folder}
                    assert job.completed[first].read_bytes() == first.read_bytes()
                    assert (destination / first.name).read_text() == 'keep existing'
                    assert (destination / 'Folder' / 'nested.txt').read_text() == 'nested bytes'
                    assert (destination / 'Folder' / 'Empty').is_dir()
                    assert window.current_dir == source and window.get_visible()
                    assert window.destination_picker is None
                    assert window.get_clipboard().get_content() == provider
                    chooser._finish(paths=[moved])
                    assert len(window.transfer_queue.jobs) == 1, 'Duplicate completion queued twice'

                    # An entered folder works as well as a selected destination folder.
                    chooser = open_destination(window, [first, folder], cut=True)
                    chooser.navigate(moved)
                    capture(chooser, f'{palette}-{view}-move')
                    chooser.accept_button.emit('clicked')
                    settle()
                    job = window.transfer_queue.jobs[-1]
                    wait_for(lambda: job.state in {'completed', 'failed'})
                    assert job.state == 'completed', job.error
                    assert not first.exists() and not folder.exists()
                    assert (moved / first.name).read_bytes() == b'original bytes\x00\xff'
                    assert (moved / folder.name / 'nested.txt').read_text() == 'nested bytes'
                    assert first not in window.entries and folder not in window.entries
                    assert window.current_dir == source and window.get_visible()
                    assert window.get_clipboard().get_content() == provider
                    assert not quit_app.called and not output.getvalue() and not errors

                    # Reject a move collision without overwriting or removing either item.
                    first.write_text('keep source')
                    window._refresh_files()
                    chooser = open_destination(window, [first], cut=True)
                    chooser.navigate(moved)
                    chooser.accept_button.emit('clicked')
                    settle()
                    job = window.transfer_queue.jobs[-1]
                    wait_for(lambda: job.state == 'failed')
                    assert 'already exists' in job.error
                    assert first.read_text() == 'keep source'
                    assert (moved / first.name).read_bytes() == b'original bytes\x00\xff'
                    assert window.transfer_window.get_visible()
                    window.transfer_queue.cancel(job)
                    wait_for(lambda: job.state == 'cancelled')

                    if palette == 'active' and view == 'grid':
                        # Same-folder copies choose another name and retain the original.
                        chooser = open_destination(window, [first])
                        chooser.accept_button.emit('clicked')
                        settle()
                        job = window.transfer_queue.jobs[-1]
                        assert job.state == 'waiting' and window.transfer_window.get_visible()
                        window.transfer_queue.start(job)  # Resume the queue held by the prior failure.
                        wait_for(lambda: job.state in {'completed', 'failed'})
                        assert job.state == 'completed', job.error
                        assert job.completed[first] != first
                        assert job.completed[first].read_text() == first.read_text() == 'keep source'

                        # The new action retains the engine's cross-volume move refusal.
                        with tempfile.TemporaryDirectory(prefix='gudfiles-move-', dir='/dev/shm') as other:
                            assert Path(other).stat().st_dev != source.stat().st_dev
                            chooser = open_destination(window, [first], cut=True)
                            chooser.navigate(Path(other))
                            chooser.accept_button.emit('clicked')
                            settle()
                            job = window.transfer_queue.jobs[-1]
                            wait_for(lambda: job.state == 'failed')
                            assert 'Moving between volumes is not supported' in job.error
                            assert first.read_text() == 'keep source'
                            assert not list(Path(other).iterdir())
                            window.transfer_queue.cancel(job)
                            wait_for(lambda: job.state == 'cancelled')

                        count = len(window.transfer_queue.jobs)
                        chooser = open_destination(window, [first])
                        with patch.object(window.transfer_queue, 'add', side_effect=ValueError('Queue is full')):
                            chooser.accept_button.emit('clicked')
                        settle()
                        assert errors == [('Could not copy', 'Queue is full')]
                        assert len(window.transfer_queue.jobs) == count
                        assert window.destination_picker is None and first.exists()

                    # Closing the owner destroys its prompt without scheduling work.
                    count = len(window.transfer_queue.jobs)
                    chooser = open_destination(window, [first])
                    window.destroy()
                    settle()
                    assert not chooser.get_realized() and window.destination_picker is None, (
                        chooser.get_visible(), chooser.get_realized(), window.destination_picker)
                    assert len(window.transfer_queue.jobs) == count
        assert not quit_app.called and not output.getvalue()
print('PASS: destination actions, cancellation, copies, moves, collisions, clipboard and host lifetime; all views in active/light palettes')
