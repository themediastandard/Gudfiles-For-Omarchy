"""Native tabs, drag payloads and real disk-aware transfers on disposable files."""
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
from gi.repository import Gdk, Gio, GLib, Gtk
from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow
from omarchy_file_picker.theme import load_colors


def settle(ms=100):
    loop = GLib.MainLoop()
    GLib.timeout_add(ms, lambda: loop.quit() or False)
    loop.run()


def until(check):
    deadline = time.monotonic() + 8
    while not check() and time.monotonic() < deadline:
        settle(30)
    assert check(), 'Timed out'


class Gesture:
    def __init__(self, modifiers=Gdk.ModifierType(0)):
        self.modifiers = modifiers
        self.state = None
    def get_current_event_state(self):
        return self.modifiers
    def set_state(self, state):
        self.state = state


colors = load_colors()
with tempfile.TemporaryDirectory(prefix='tabs-drag-') as temporary, \
        patch.object(Path, 'home', return_value=Path(temporary)), \
        patch.dict(os.environ, {'XDG_STATE_HOME': str(Path(temporary) / 'state')}), \
        patch.object(Gio.VolumeMonitor, 'get_mounts', return_value=[]), \
        patch('omarchy_file_picker.picker.load_colors', return_value=colors):
    root = Path(temporary)
    first, second, nested = root / 'Source', root / 'Destination', root / 'Source/Nested'
    nested.mkdir(parents=True)
    second.mkdir()
    paths = [first / f'{i:03d}.txt' for i in range(95)]
    for path in paths:
        path.write_text(path.name * 20)
    (nested / 'inside.txt').write_text('inside')
    request = PickerRequest(current_folder=first, explorer=True, multiple=True, title='Tabs and dragging QA')
    app = PickerApplication(request, None)
    app.register(None)
    window = PickerWindow(app, request, None)
    window.present()
    settle()
    clients = (json.loads(subprocess.check_output(['hyprctl', 'clients', '-j']))
               if os.environ.get('GDK_BACKEND') != 'x11' else [])
    for client in clients:
        if client['pid'] == os.getpid() and not client['floating']:
            subprocess.run(['hyprctl', 'dispatch', 'hl.dsp.window.float({action="toggle",window=' +
                            json.dumps('address:' + client['address']) + '})'], check=True, stdout=subprocess.DEVNULL)
    settle()
    tabs, drag, queue = window.tabs, window.drag_copy, window.transfer_queue
    errors = []
    window._show_error = lambda *args: errors.append(args)
    geometry = window.get_width(), window.get_height()
    original = tabs.current

    def point(path):
        valid, bounds = window.children_by_path[path].compute_bounds(window.browser_stack)
        assert valid
        return bounds.get_x() + bounds.get_width() / 2, bounds.get_y() + bounds.get_height() / 2

    def select(paths):
        window.flow.unselect_all()
        for path in paths:
            window.flow.select_child(window.children_by_path[path])
        window.columns.cancel_pending()

    def drop(value, target, position, *, copy=False):
        count = len(queue.jobs)
        modifiers = Gdk.ModifierType.ALT_MASK if copy else Gdk.ModifierType(0)
        with patch.object(Gtk.DropTarget, 'get_current_event_state', return_value=modifiers):
            assert target.emit('drop', value, *position)
        drag._finish()
        until(lambda: not window.file_job_active and len(queue.jobs) > count and not queue.unfinished)
        window._poll_transfers()
        assert all(j.state == 'completed' for j in queue.jobs[count:]), [j.error for j in queue.jobs[count:]]
        settle()
        return queue.jobs[count:]

    try:
        window._set_view('list')
        select(paths[20:23])
        window.file_scroller.get_vadjustment().set_value(460)
        settle()
        saved_scroll = window.file_scroller.get_vadjustment().get_value()
        destination = tabs.new(second)
        settle()
        assert window.current_dir == second and not window._selected_paths()
        window._set_view('grid')
        tabs.select(original)
        # Tab selection is restored after allocation on the frame clock.
        until(lambda: window._selected_paths() == paths[20:23])
        assert window.current_dir == first and window.view_mode == 'list'
        assert window._selected_paths() == paths[20:23], window._selected_paths()
        assert abs(window.file_scroller.get_vadjustment().get_value() - saved_scroll) < 2
        window.navigate(nested)
        saved_history = list(window.history)
        tabs.select(destination)
        settle()
        assert window.history == [second]
        tabs.select(original)
        settle()
        assert window.current_dir == nested and window.history == saved_history
        window._go_back(None)
        assert window.current_dir == first
        window.search.set_text('020')
        settle(250)
        select(paths[20:21])
        tabs.select(destination)
        settle()
        assert window.search.get_text() == ''
        tabs.select(original)
        settle(300)
        assert window.search.get_text() == '020' and window._selected_paths() == paths[20:21]
        print('PASS: independent tab folders, back/forward history, view, search, selection and scroll')

        window.search.set_text('')
        settle(250)
        window._set_view('columns')
        select([nested])
        window.columns._open_selection()
        settle()
        child_column = window.columns.columns[-1]
        window.columns.activate(child_column)
        select([nested / 'inside.txt'])
        trail = [c.path for c in window.columns.columns]
        tabs.select(destination)
        settle()
        tabs.select(original)
        settle(250)
        assert window.view_mode == 'columns'
        assert [c.path for c in window.columns.columns] == trail
        assert window.current_dir == nested and window._selected_paths() == [nested / 'inside.txt']
        print('PASS: column trail and active-column selection survive tab switches')

        assert tabs.shortcut(Gdk.KEY_t, Gdk.ModifierType.CONTROL_MASK)
        extra = tabs.current
        assert len(tabs.items) == 3
        tabs.shortcut(Gdk.KEY_w, Gdk.ModifierType.CONTROL_MASK)
        assert len(tabs.items) == 2
        tabs.shortcut(Gdk.KEY_T, Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK)
        assert len(tabs.items) == 3 and tabs.current.path == nested
        extra = tabs.current
        assert tabs.reorder(extra.id, tabs.items[0], 0)
        assert tabs.items[0] is extra
        tabs.shortcut(Gdk.KEY_9, Gdk.ModifierType.ALT_MASK)
        assert tabs.current is tabs.items[-1]
        tabs.close(extra)
        tabs.select(original)
        settle()
        print('PASS: new, close, reopen, reorder and keyboard tab navigation')

        for mode in ('grid', 'list', 'columns'):
            window.navigate(first)
            window._set_view(mode)
            settle()
            file1 = first / f'drag-{mode}.txt'
            file2 = first / f'drag-{mode}-second.txt'
            file1.write_text('first original')
            file2.write_text('second original')
            window._refresh_files()
            settle()
            # Put the rows in view for actual GTK hit testing.
            window.file_scroller.get_vadjustment().set_value(window.file_scroller.get_vadjustment().get_upper())
            settle()
            select([file1, file2])
            gesture = Gesture()
            drag._arm(gesture, *point(file1))
            assert drag.armed and not drag.active and gesture.state is None
            with patch.object(Gtk.DragSource, 'get_current_event_state', return_value=Gdk.ModifierType(0)):
                provider = drag.source.emit('prepare', *point(file1))
            assert provider is not None and set(drag.paths) == {file1, file2}
            value = Gdk.FileList.new_from_list([Gio.File.new_for_path(str(p)) for p in drag.paths])
            # Hover to another tab while the source drag remains alive.
            target = next(c for c in destination.widget.observe_controllers() if isinstance(c, Gtk.DropTarget) and c.get_preload())
            with patch.object(Gtk.DropTarget, 'get_value', return_value=value):
                target.emit('motion', 10, 10)
            settle(700)
            assert tabs.current is destination and drag.active and set(drag.paths) == {file1, file2}
            jobs = drop(value, target, (10, 10))
            assert jobs[0].cut and not file1.exists() and not file2.exists()
            assert (second / file1.name).read_text() == 'first original'
            tabs.select(original)
            settle()
            assert file1 not in window.children_by_path
            print('PASS:', mode, 'ordinary multi-file drag, hover-switch, tab drop and source refresh')

        window.navigate(first)
        window._set_view('list')
        settle()
        value = Gdk.FileList.new_from_list([Gio.File.new_for_path(str(paths[0]))])
        home_button = next(b for b in window.location_buttons if getattr(b, '_picker_path', None) == root)
        sidebar_target = next(c for c in window.sidebar_scroll.observe_controllers() if isinstance(c, Gtk.DropTarget))
        valid, bounds = home_button.compute_bounds(window.sidebar_scroll)
        assert valid
        jobs = drop(value, sidebar_target, (bounds.get_x() + 20, bounds.get_y() + 10), copy=True)
        assert not jobs[0].cut and paths[0].exists() and (root / paths[0].name).exists()
        print('PASS: Alt-copy to sidebar location preserves original')
        assert (window.get_width(), window.get_height()) == geometry
        assert not errors, errors
        if screenshot := os.environ.get('TABS_QA_SCREENSHOT'):
            tabs.select(destination)
            settle(250)
            subprocess.run(['grim', screenshot], check=True)
    finally:
        window.destroy()
        settle()
print('PASS: tabs and drag QA')
