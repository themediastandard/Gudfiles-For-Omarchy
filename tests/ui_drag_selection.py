"""Exercise background drag handlers against real GTK layout/hit testing."""
from pathlib import Path
import tempfile

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gdk, GLib, Gtk
from omarchy_file_picker.model import PickerRequest
from omarchy_file_picker.picker import PickerApplication, PickerWindow


def settle():
    loop = GLib.MainLoop()
    GLib.timeout_add(120, lambda: loop.quit() or False)
    loop.run()


class Gesture:
    def __init__(self, modifiers=0):
        self.modifiers = Gdk.ModifierType(modifiers)
        self.state = None

    def set_state(self, state):
        self.state = state

    def get_current_event_state(self):
        return self.modifiers


with tempfile.TemporaryDirectory(prefix='picker-drag-') as temp:
    root = Path(temp)
    for index in range(3):
        (root / f'{index}.txt').write_text('fixture')
    request = PickerRequest(current_folder=root, multiple=True)
    app = PickerApplication(request, None)
    app.register(None)
    window = PickerWindow(app, request, None)
    window.present()
    settle()
    drag = window.drag_selection
    paths = list(window.entries)
    try:
        for mode in ('grid', 'list', 'columns'):
            window._set_view(mode)
            settle()
            geometry = window.get_width(), window.get_height()
            def bounds(path):
                valid, rect = window.children_by_path[path].compute_bounds(window.browser_stack)
                assert valid
                return rect
            first, last = bounds(paths[0]), bounds(paths[-1])
            sx, sy = 2, last.get_y() + last.get_height() + 20
            ex, ey = last.get_x() + last.get_width() / 2, first.get_y() + 2
            assert sy < window.browser_stack.get_height(), sy
            def begin(modifiers=0):
                gesture = Gesture(modifiers)
                drag._begin(gesture, sx, sy)
                assert gesture.state == Gtk.EventSequenceState.CLAIMED
                return gesture
            gesture = begin()
            drag._update(gesture, ex - sx, ey - sy)
            assert set(window._selected_paths()) == set(paths)
            assert drag.get_visible()
            # Shrinking the rectangle must remove items, not only add them.
            drag._update(gesture, 1, -1)
            assert not window._selected_paths()
            drag._end(gesture, ex - sx, ey - sy)
            assert not drag.get_visible() and not drag.active
            assert set(window._selected_paths()) == set(paths)
            gesture = begin(Gdk.ModifierType.CONTROL_MASK)
            drag._end(gesture, ex - sx, ey - sy)
            assert not window._selected_paths()
            window.flow.select_child(window.children_by_path[paths[0]])
            gesture = begin(Gdk.ModifierType.SHIFT_MASK)
            drag._update(gesture, ex - sx, ey - sy)
            assert set(window._selected_paths()) == set(paths)
            window._on_preview_key(None, Gdk.KEY_Escape, 0, Gdk.ModifierType(0))
            assert window._selected_paths() == paths[:1]
            assert not drag.active and not drag.get_visible()
            # File-origin gestures remain available to GTK's native clicks.
            gesture = Gesture()
            drag._begin(gesture, first.get_x() + 10, first.get_y() + 10)
            assert gesture.state == Gtk.EventSequenceState.DENIED
            assert not drag.active
            window.request.multiple = False
            gesture = Gesture()
            drag._begin(gesture, sx, sy)
            assert gesture.state == Gtk.EventSequenceState.DENIED
            window.request.multiple = True
            assert (window.get_width(), window.get_height()) == geometry
            print('PASS:', mode, 'background drag, shrink, Ctrl toggle, Shift add, Escape, native file clicks, single-only restriction')
        for index in range(100):
            (root / f'extra-{index:03d}.txt').write_text('fixture')
        window._load()
        settle()
        gesture = Gesture()
        drag._begin(gesture, 2, 30)
        assert drag.active
        drag._update(gesture, 100, window.browser_stack.get_height())
        old = drag.adjustment.get_value()
        for _ in range(5):
            drag._scroll(None, None)
        assert drag.adjustment.get_value() > old
        assert window._selected_paths()
        window._set_view('grid')
        assert not drag.active and not drag.get_visible() and not drag.tick
        print('PASS: edge auto-scroll and cancellation on view rebuild')
    finally:
        drag.cancel()
        window.destroy()
