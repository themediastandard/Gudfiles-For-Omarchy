"""Background-only rubber-band selection; file clicks remain GTK-native."""
from gi.repository import Gdk, Gtk

from .theme import load_colors


class BackgroundSelection(Gtk.DrawingArea):
    def __init__(self, owner):
        super().__init__(hexpand=True, vexpand=True, can_target=False)
        self.owner = owner
        self.active = False
        self.dragging = False
        self.tick = 0
        self.rectangle = None
        self.original = set()
        self.color = Gdk.RGBA()
        self.color.parse(load_colors()['accent'])
        self.set_draw_func(self._draw)
        self.set_visible(False)
        gesture = Gtk.GestureDrag(button=Gdk.BUTTON_PRIMARY)
        gesture.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        gesture.connect('drag-begin', self._begin)
        gesture.connect('drag-update', self._update)
        gesture.connect('drag-end', self._end)
        gesture.connect('cancel', lambda *_: self.cancel())
        owner.browser_stack.add_controller(gesture)
        self.gesture = gesture

    def _begin(self, gesture, x, y):
        self.cancel()
        if self.owner.special_mode == 'trash':
            gesture.set_state(Gtk.EventSequenceState.DENIED)
            return
        widget = self.owner.browser_stack.pick(x, y, Gtk.PickFlags.DEFAULT)
        while widget and widget is not self.owner.browser_stack:
            if isinstance(widget, (Gtk.FlowBoxChild, Gtk.Scrollbar, Gtk.Popover)):
                gesture.set_state(Gtk.EventSequenceState.DENIED)
                return
            widget = widget.get_parent()
        if not self.owner.request.multiple or self.owner.context_popover:
            gesture.set_state(Gtk.EventSequenceState.DENIED)
            return
        if self.owner.view_mode == 'columns':
            self.owner.columns.activate_at(self.owner.browser_stack, x, y)
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        self.original = set(self.owner._selected_paths())
        self.modifiers = gesture.get_current_event_state()
        self.start = (x, y)
        self.pointer = (x, y)
        self.origin = (x, y + self.adjustment.get_value())
        self.active = True
        self.owner.flow.grab_focus()
        if not self.modifiers & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK):
            self._select(set())

    @property
    def adjustment(self):
        return self.owner.file_scroller.get_vadjustment()

    def _update(self, _gesture, dx, dy):
        if not self.active:
            return
        self.pointer = self.start[0] + dx, self.start[1] + dy
        if not self.dragging and max(abs(dx), abs(dy)) < 8:
            return
        if not self.dragging:
            self.dragging = True
            self.set_visible(True)
            self.tick = self.add_tick_callback(self._scroll)
        self._refresh()

    def _refresh(self):
        width = self.owner.browser_stack.get_width()
        height = self.owner.browser_stack.get_height()
        x = min(width, max(0, self.pointer[0]))
        y = min(height, max(0, self.pointer[1])) + self.adjustment.get_value()
        ox, oy = self.origin
        left, top, right, bottom = min(x, ox), min(y, oy), max(x, ox), max(y, oy)
        self.rectangle = left, top - self.adjustment.get_value(), right - left, bottom - top
        hits = set()
        for path, child in self.owner.children_by_path.items():
            valid, bounds = child.compute_bounds(self.owner.browser_stack)
            if not valid:
                continue
            cx, cy = bounds.get_x(), bounds.get_y() + self.adjustment.get_value()
            if cx < right and cx + bounds.get_width() > left and cy < bottom and cy + bounds.get_height() > top:
                hits.add(path)
        if self.modifiers & Gdk.ModifierType.CONTROL_MASK:
            hits = self.original ^ hits
        elif self.modifiers & Gdk.ModifierType.SHIFT_MASK:
            hits |= self.original
        self._select(hits)
        self.queue_draw()

    def _select(self, paths):
        current = set(self.owner._selected_paths())
        if current == paths:
            return
        # Refresh the metadata once per rectangle update, not once per file.
        flow = self.owner.flow
        flow.handler_block(self.owner.selection_changed_handler)
        try:
            for path in current - paths:
                child = self.owner.children_by_path.get(path)
                if child:
                    flow.unselect_child(child)
            for path in paths - current:
                child = self.owner.children_by_path.get(path)
                if child:
                    flow.select_child(child)
        finally:
            flow.handler_unblock(self.owner.selection_changed_handler)
        self.owner._on_selection_changed(flow)

    def _scroll(self, _widget, _clock):
        if not self.active:
            self.tick = 0
            return False
        height = self.owner.browser_stack.get_height()
        y = self.pointer[1]
        speed = -10 if y < 24 else (10 if y > height - 24 else 0)
        if speed:
            adjustment = self.adjustment
            previous = adjustment.get_value()
            adjustment.set_value(max(adjustment.get_lower(), min(
                adjustment.get_upper() - adjustment.get_page_size(), previous + speed)))
            if previous != adjustment.get_value():
                self._refresh()
        return True

    def _end(self, gesture, dx, dy):
        if not self.active:
            return
        self._update(gesture, dx, dy)
        self._stop()

        if self.owner.view_mode == 'columns':
            self.owner.columns.schedule_open()

    def cancel(self):
        if self.active:
            self._select(self.original)
        self._stop()

    def _stop(self):
        self.active = self.dragging = False
        if self.tick:
            self.remove_tick_callback(self.tick)
            self.tick = 0
        self.rectangle = None
        self.set_visible(False)

    def _draw(self, _area, context, _width, _height):
        if self.rectangle:
            context.rectangle(*self.rectangle)
            color = self.color
            context.set_source_rgba(color.red, color.green, color.blue, .16)
            context.fill_preserve()
            context.set_source_rgba(color.red, color.green, color.blue, .9)
            context.set_line_width(1)
            context.stroke()
