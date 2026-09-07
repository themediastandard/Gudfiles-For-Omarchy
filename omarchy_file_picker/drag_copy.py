"""Option/Alt file drags: native copy payloads and shared verified transfers."""
from pathlib import Path

from gi.repository import Gdk, Gio, GLib, Gtk, Pango


class DragCopy:
    def __init__(self, owner):
        self.owner = owner
        self.paths = ()
        self.active = False
        self.highlight = None
        self.pointer = None
        self.drop_paths = ()
        self.scroller = None
        self.tick = 0
        source = Gtk.DragSource(actions=Gdk.DragAction.COPY, button=Gdk.BUTTON_PRIMARY)
        source.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        source.connect('begin', self._begin)
        source.connect('end', self._gesture_end)
        source.connect('cancel', self._gesture_end)
        source.connect('prepare', self._prepare)
        source.connect('drag-begin', self._drag_begin)
        source.connect('drag-end', self._finish)
        owner.browser_stack.add_controller(source)
        self.source = source
        target = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        target.set_preload(True)
        target.connect('enter', self._motion)
        target.connect('motion', self._motion)
        target.connect('leave', self._leave)
        target.connect('drop', self._drop)
        target.connect('notify::value', self._value_changed)
        owner.browser_stack.add_controller(target)
        self.target = target
        owner.connect('unrealize', lambda *_: self.cancel())

    def _hit(self, x, y):
        widget = self.owner.browser_stack.pick(x, y, Gtk.PickFlags.DEFAULT)
        child = column = None
        while widget and widget is not self.owner.browser_stack:
            if isinstance(widget, (Gtk.Popover, Gtk.Scrollbar)):
                return None, None, False
            if isinstance(widget, Gtk.FlowBoxChild):
                child = widget
            if self.owner.view_mode == 'columns':
                column = column or next((c for c in self.owner.columns.columns if c.panel is widget), None)
            widget = widget.get_parent()
        return child, column, widget is self.owner.browser_stack

    def _begin(self, source, sequence):
        valid, x, y = source.get_point(sequence)
        if valid:
            self._arm(source, x, y)

    def _arm(self, source, x, y):
        self.paths, self.active = (), False
        child, column, valid = self._hit(x, y)
        if (not valid or child is None or self.owner.context_popover or
                not source.get_current_event_state() & Gdk.ModifierType.ALT_MASK):
            source.set_state(Gtk.EventSequenceState.DENIED)
            return
        # Claim only Alt file presses, before FlowBox can collapse a selection
        # or a column can open the folder under the pointer during the drag.
        self.active = True
        source.set_state(Gtk.EventSequenceState.CLAIMED)
        if column:
            self.owner.columns.activate(column)
            self.owner.columns.cancel_pending()
        flow = child.get_parent()
        if not child.is_selected():
            flow.unselect_all()
            flow.select_child(child)
        self.paths = tuple(item._picker_path for item in flow.get_selected_children())

    def _prepare(self, source, _x, _y):
        if not self.active or not self.paths or not source.get_current_event_state() & Gdk.ModifierType.ALT_MASK:
            return None
        files = Gdk.FileList.new_from_list([Gio.File.new_for_path(str(p)) for p in self.paths])
        return Gdk.ContentProvider.new_for_value(files)

    def _drag_begin(self, _source, drag):
        icon = Gtk.Box(spacing=8)
        icon.add_css_class('file-copy-drag')
        icon.append(Gtk.Image.new_from_icon_name('list-add-symbolic'))
        name = self.paths[0].name if len(self.paths) == 1 else f'{len(self.paths)} items'
        title = Gtk.Label(label='Copy ' + name, ellipsize=Pango.EllipsizeMode.MIDDLE,
                          max_width_chars=28)
        icon.append(title)
        Gtk.DragIcon.get_for_drag(drag).set_child(icon)
        drag.set_hotspot(-12, -12)

    def _gesture_end(self, source, _sequence):
        # GTK resets gestures after creating GdkDrag, before drag-begin. Keep
        # the captured group across that reset, clearing it on the DND end.
        if source.get_drag() is None:
            self._finish()

    def _finish(self, *_args):
        self.paths, self.active = (), False
        self._leave()

    def cancel(self):
        self.source.drag_cancel()
        self.source.reset()
        self._finish()

    @staticmethod
    def _paths(value):
        if not isinstance(value, Gdk.FileList):
            return ()
        files = value.get_files()
        if not files or len(files) > 10_000:
            return ()
        paths = [file.get_path() for file in files]
        if any(path is None for path in paths):
            return ()
        return tuple(dict.fromkeys(Path(path) for path in paths))

    def _destination(self, x, y, paths):
        child, column, valid = self._hit(x, y)
        if not valid or (self.owner.view_mode == 'columns' and column is None):
            return None, None, None
        directory = column.path if column else self.owner.current_dir
        surface = column.panel if column else self.owner.browser_stack
        scroller = column.scroller if column else self.owner.standard_scroller
        if child and child._picker_path not in paths:
            if not child._picker_is_dir:
                return None, None, scroller
            directory, surface = child._picker_path, child
        elif self.owner.special_mode is not None:
            return None, None, scroller
        # Filesystem/alias checks happen again on the worker. Hover uses only
        # cached row kinds and path comparisons, never a potentially blocked NAS.
        if any(path == directory or path in directory.parents for path in paths):
            return None, None, scroller
        return directory, surface, scroller

    def _motion(self, target, x, y):
        if not self.drop_paths:
            self.drop_paths = self._paths(target.get_value())
        paths = self.drop_paths
        directory, surface, self.scroller = self._destination(x, y, paths) if paths else (None, None, None)
        self._highlight(surface)
        self.pointer = (x, y)
        if not self.tick:
            self.tick = self.owner.browser_stack.add_tick_callback(self._scroll)
        return Gdk.DragAction.COPY if directory is not None else Gdk.DragAction(0)

    def _value_changed(self, target, _property):
        self.drop_paths = self._paths(target.get_value())
        if self.pointer:
            self._motion(target, *self.pointer)

    def _highlight(self, surface):
        if self.highlight is not surface:
            if self.highlight:
                self.highlight.remove_css_class('drop-copy-target')
            self.highlight = surface
            if surface:
                surface.add_css_class('drop-copy-target')

    def _leave(self, *_args):
        self._highlight(None)
        self.pointer = self.scroller = None
        self.drop_paths = ()
        if self.tick:
            self.owner.browser_stack.remove_tick_callback(self.tick)
            self.tick = 0

    def _scroll(self, _widget, _clock):
        if self.pointer and self.scroller:
            x, y = self.pointer
            vertical = self.scroller.get_vadjustment()
            horizontal = self.owner.columns.get_hadjustment()
            previous = vertical.get_value(), horizontal.get_value()
            valid, bounds = self.scroller.compute_bounds(self.owner.browser_stack)
            if valid:
                self._step(vertical, y - bounds.get_y(), bounds.get_height())
            if self.owner.view_mode == 'columns':
                self._step(horizontal, x, self.owner.browser_stack.get_width())
            if previous != (vertical.get_value(), horizontal.get_value()):
                self._motion(self.target, x, y)
        return True

    @staticmethod
    def _step(adjustment, position, size):
        speed = -10 if position < 24 else 10 if position > size - 24 else 0
        if speed:
            adjustment.set_value(max(adjustment.get_lower(), min(
                adjustment.get_upper() - adjustment.get_page_size(), adjustment.get_value() + speed)))

    def _drop(self, _target, value, x, y):
        paths = self._paths(value)
        directory, _, _ = self._destination(x, y, paths) if paths else (None, None, None)
        self._leave()
        if directory is None:
            return False
        try:
            job = self.owner.transfer_queue.add(paths, directory, duplicate=True, start=True)
        except ValueError as error:
            self.owner._show_error('Could not copy', str(error))
            return False
        # Let GTK finish the drop before presenting another native window.
        def show():
            self.owner._show_transfers(automatic_job=job)
            return False
        GLib.idle_add(show)
        return True
