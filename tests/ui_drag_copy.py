"""Alt-drag handlers and native GTK payload/drop signals on disposable files."""
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gdk, Gio, GLib, GObject, Gtk

from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow
from omarchy_file_picker.theme import load_colors


def settle(ms=80):
    loop = GLib.MainLoop()
    GLib.timeout_add(ms, lambda: loop.quit() or False)
    loop.run()


def until(predicate):
    deadline = time.monotonic() + 8
    while not predicate() and time.monotonic() < deadline:
        settle()
    assert predicate(), 'Drag-copy QA timed out'


def float_fixtures():
    for client in json.loads(subprocess.check_output(['hyprctl', 'clients', '-j'])):
        if client['pid'] == os.getpid() and client['class'] == 'org.omarchy.FilePicker' and not client['floating']:
            subprocess.run(['hyprctl', 'dispatch', 'hl.dsp.window.float({action="toggle",window=' +
                            json.dumps('address:' + client['address']) + '})'],
                           check=True, stdout=subprocess.DEVNULL)


class Gesture:
    def __init__(self, state=Gdk.ModifierType.ALT_MASK):
        self.modifiers = state
        self.state = None

    def get_current_event_state(self):
        return self.modifiers

    def set_state(self, state):
        self.state = state


colors = load_colors()
with tempfile.TemporaryDirectory(prefix='picker-drag-copy-') as temp, \
        patch.object(Path, 'home', return_value=Path(temp)), \
        patch.object(Gio.VolumeMonitor, 'get_mounts', return_value=[]), \
        patch('omarchy_file_picker.picker.load_colors', return_value=colors):
    root = Path(temp)
    first, second, folder = root / 'A % #.txt', root / 'B.txt', root / 'Folder.v2'
    first.write_text('first')
    second.write_text('second')
    folder.mkdir()
    (folder / 'inside.txt').write_text('nested')
    request = PickerRequest(current_folder=root, multiple=True, explorer=True, title='Drag copy QA')
    app = PickerApplication(request, None)
    app.register(None)
    window = PickerWindow(app, request, None)
    errors = []
    window._show_error = lambda *args: errors.append(args)
    window.present()
    settle(150)
    float_fixtures()
    settle()
    drag, queue = window.drag_copy, window.transfer_queue
    geometry = window.get_width(), window.get_height()

    def point(path, column=None):
        children = column.children if column else window.children_by_path
        valid, rect = children[path].compute_bounds(window.browser_stack)
        assert valid
        return rect.get_x() + rect.get_width() / 2, rect.get_y() + rect.get_height() / 2

    def blank(column=None):
        scroller = column.scroller if column else window.file_scroller
        valid, rect = scroller.compute_bounds(window.browser_stack)
        assert valid
        return rect.get_x() + 10, rect.get_y() + rect.get_height() - 16

    def arm(path, paths=None, column=None):
        if column:
            window.columns.activate(column)
        window.flow.unselect_all()
        for item in paths or [path]:
            window.flow.select_child(window.children_by_path[item])
        gesture = Gesture()
        drag._arm(gesture, *point(path, column))
        assert gesture.state == Gtk.EventSequenceState.CLAIMED
        assert set(drag.paths) == set(paths or [path])
        with patch.object(Gtk.DragSource, 'get_current_event_state', return_value=Gdk.ModifierType.ALT_MASK):
            provider = drag.source.emit('prepare', *point(path, column))
        assert provider is not None
        assert provider.ref_formats().contain_gtype(Gdk.FileList)
        return Gdk.FileList.new_from_list([Gio.File.new_for_path(str(p)) for p in drag.paths])

    def drop(value, position):
        with patch.object(Gtk.DropTarget, 'get_value', return_value=value):
            action = drag.target.emit('motion', *position)
            assert action == Gdk.DragAction.COPY
            assert drag.highlight.has_css_class('drop-copy-target')
        assert drag.target.emit('drop', value, *position)
        drag._finish()
        job = queue.jobs[-1]
        assert job.duplicate and not job.cut
        until(lambda: not queue.active_jobs and job.state == 'completed')
        window._poll_transfers()
        float_fixtures()
        settle()
        assert not drag.highlight and not drag.tick
        return job

    try:
        for mode in ('grid', 'list', 'columns'):
            window.navigate(root)
            window._set_view(mode)
            settle()
            window.flow.unselect_all()
            window.flow.select_child(window.children_by_path[first])
            ordinary = Gesture(Gdk.ModifierType(0))
            drag._arm(ordinary, *point(first))
            assert ordinary.state == Gtk.EventSequenceState.DENIED
            assert not drag.active and drag.source.emit('prepare', *point(first)) is None
            assert window._selected_paths() == [first]
            ordinary = Gesture()
            drag._arm(ordinary, *blank())
            assert ordinary.state == Gtk.EventSequenceState.DENIED
            assert not drag.active

            # Alt click/Escape without a completed native drop creates no job.
            value = arm(first, [first, second])
            count = len(queue.jobs)
            window._on_preview_key(None, Gdk.KEY_Escape, 0, Gdk.ModifierType(0))
            assert not drag.active and len(queue.jobs) == count
            assert set(window._selected_paths()) == {first, second}

            # Copy selected group in place, preserving source bytes/clipboard.
            clipboard = window.get_clipboard()
            clipboard.set('unrelated clipboard text')
            original_provider = clipboard.get_content()
            value = arm(first, [first, second])
            if mode == 'grid':
                # Use GTK's actual cross-process URI serializer/deserializer,
                # including characters which require URI escaping.
                output = Gio.MemoryOutputStream.new_resizable()
                serialized = []
                boxed = GObject.Value(Gdk.FileList, value)
                Gdk.content_serialize_async(output, 'text/uri-list', boxed, GLib.PRIORITY_DEFAULT,
                    None, lambda _o, result: serialized.append(Gdk.content_serialize_finish(result)))
                until(lambda: serialized)
                assert serialized == [True]
                output.close(None)
                stream = Gio.MemoryInputStream.new_from_bytes(output.steal_as_bytes())
                decoded = []
                Gdk.content_deserialize_async(stream, 'text/uri-list', Gdk.FileList, GLib.PRIORITY_DEFAULT,
                    None, lambda _o, result: decoded.append(Gdk.content_deserialize_finish(result)))
                until(lambda: decoded)
                assert decoded[0][0] and set(drag._paths(decoded[0][1])) == {first, second}
            job = drop(value, blank())
            assert set(job.completed) == {first, second}
            assert all(target.parent == root and target != source for source, target in job.completed.items())
            assert all(target.read_bytes() == source.read_bytes() for source, target in job.completed.items())
            assert clipboard.get_content() == original_provider
            assert first.read_text() == 'first' and second.read_text() == 'second'

            # Dropping on a folder copies there; another file is not a target.
            value = arm(first)
            with patch.object(Gtk.DropTarget, 'get_value', return_value=value):
                assert drag.target.emit('motion', *point(second)) == Gdk.DragAction(0)
            assert not drag.target.emit('drop', value, *point(second))
            job = drop(value, point(folder))
            assert job.completed[first].parent == folder

            # Folder-origin Alt press must not open/remove columns mid-drag.
            value = arm(folder)
            settle()
            if mode == 'columns':
                assert len(window.columns.columns) == 1
            job = drop(value, blank())
            assert (job.completed[folder] / 'inside.txt').read_text() == 'nested'
            assert (folder / 'inside.txt').read_text() == 'nested'
            assert (window.get_width(), window.get_height()) == geometry
            print('PASS:', mode, 'Alt group copy, numbered copies, folder drops, cancellation, native-click handoff, clipboard, geometry')

        # A drop goes to the column under the pointer, never the active one.
        window.navigate(root)
        settle()
        window.flow.select_child(window.children_by_path[folder])
        settle()
        ancestor, child_column = window.columns.columns
        value = arm(first, column=ancestor)
        job = drop(value, blank(child_column))
        assert job.destination == folder
        assert job.completed[first] in child_column.children
        assert window.current_dir == root
        assert window.columns.active is ancestor
        print('PASS: inactive column destination and visible contents refreshed without changing the active column')

        # Invalid recursive, remote and text payloads must not add transfers.
        count = len(queue.jobs)
        recursive = Gdk.FileList.new_from_list([Gio.File.new_for_path(str(root))])
        assert not drag.target.emit('drop', recursive, *blank(ancestor))
        remote = Gdk.FileList.new_from_list([Gio.File.new_for_uri('smb://fixture.invalid/share/file')])
        assert not drag._drop(drag.target, remote, *blank(ancestor))
        assert not drag._drop(drag.target, 'plain text', *blank(ancestor))
        assert len(queue.jobs) == count and not errors, errors
        print('PASS: recursive, nonlocal and wrong-type drops rejected')

        for index in range(80):
            (root / f'Extra {index:02}.txt').write_text('scroll fixture')
        window.navigate(root)
        window._set_view('list')
        settle()
        value = arm(first)
        position = blank()
        with patch.object(Gtk.DropTarget, 'get_value', return_value=value):
            drag.target.emit('motion', *position)
            before = window.file_scroller.get_vadjustment().get_value()
            for _ in range(5):
                drag._scroll(None, None)
            assert window.file_scroller.get_vadjustment().get_value() > before
        drag.cancel()
        assert not drag.tick and not drag.highlight
        print('PASS: file drag edge scrolling and cancellation cleanup')

        if os.environ.get('DRAG_COPY_QA_SCREENSHOT'):
            window.navigate(root)
            window._set_view('grid')
            settle()
            value = arm(first)
            with patch.object(Gtk.DropTarget, 'get_value', return_value=value):
                drag.target.emit('motion', *point(folder))
                settle()
                snapshot = Gtk.Snapshot()
                Gtk.WidgetPaintable.new(window).snapshot(snapshot, window.get_width(), window.get_height())
                node = snapshot.to_node()
                assert node is not None
                texture = window.get_renderer().render_texture(node, None)
                assert texture.save_to_png(os.environ['DRAG_COPY_QA_SCREENSHOT'])
            drag.cancel()
    finally:
        drag.cancel()
        for job in queue.jobs:
            queue.cancel(job)
        until(lambda: not queue.active_jobs)
        window.destroy()
