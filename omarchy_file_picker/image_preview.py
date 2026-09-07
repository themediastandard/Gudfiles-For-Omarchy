"""Clipped, read-only image zoom without changing any layout size requests."""
from __future__ import annotations

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Graphene', '1.0')
from gi.repository import Gdk, Graphene, Gtk


class ZoomImage(Gtk.Widget):
    __gtype_name__ = 'OmarchyZoomImage'

    def __init__(self, texture):
        super().__init__(hexpand=True, vexpand=True)
        self.texture = texture
        self.zoom = 1.0
        self.offset = (0.0, 0.0)
        self.pointer = None
        self.drag_origin = None
        self.set_overflow(Gtk.Overflow.HIDDEN)
        self.set_tooltip_text('Scroll to zoom · Drag to pan · Double-click to fit')
        self.scroll = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
        self.scroll.connect('scroll', self._scroll)
        self.add_controller(self.scroll)
        motion = Gtk.EventControllerMotion()
        motion.connect('enter', self._motion)
        motion.connect('motion', self._motion)
        motion.connect('leave', lambda *_: setattr(self, 'pointer', None))
        self.add_controller(motion)
        self.drag = Gtk.GestureDrag(button=1)
        self.drag.connect('drag-begin', self._drag_begin)
        self.drag.connect('drag-update', self._drag_update)
        self.drag.connect('drag-end', self._drag_end)
        self.add_controller(self.drag)
        self.click = Gtk.GestureClick(button=1)
        self.click.connect('pressed', self._pressed)
        self.add_controller(self.click)

    def do_measure(self, orientation, for_size):
        return 0, 0, -1, -1

    def image_size(self):
        scale = min(self.get_width() / self.texture.get_width(),
                    self.get_height() / self.texture.get_height()) * self.zoom
        return self.texture.get_width() * scale, self.texture.get_height() * scale

    def _clamp(self):
        width, height = self.image_size()
        limits = (max(0, (width - self.get_width()) / 2),
                  max(0, (height - self.get_height()) / 2))
        self.offset = tuple(max(-limit, min(limit, value))
                            for value, limit in zip(self.offset, limits))

    def do_size_allocate(self, width, height, baseline):
        self._clamp()

    def do_snapshot(self, snapshot):
        width, height = self.image_size()
        if width <= 0 or height <= 0:
            return
        x = (self.get_width() - width) / 2 + self.offset[0]
        y = (self.get_height() - height) / 2 + self.offset[1]
        snapshot.push_clip(Graphene.Rect().init(0, 0, self.get_width(), self.get_height()))
        snapshot.append_texture(self.texture, Graphene.Rect().init(x, y, width, height))
        snapshot.pop()

    def _motion(self, _controller, x, y):
        self.pointer = (x, y)

    def _scroll(self, controller, _dx, dy):
        # Wheel deltas are steps; touchpad surface deltas are pixels.
        if controller.get_unit() == Gdk.ScrollUnit.SURFACE:
            dy /= 50
        previous = self.zoom
        self.zoom = max(1.0, min(8.0, previous * 1.2 ** max(-20, min(20, -dy))))
        ratio = self.zoom / previous
        center = (self.get_width() / 2, self.get_height() / 2)
        pointer = self.pointer or center
        self.offset = tuple((p - c) * (1 - ratio) + offset * ratio
                            for p, c, offset in zip(pointer, center, self.offset))
        self._clamp()
        self.set_cursor_from_name('grab' if self.zoom > 1 else 'default')
        self.queue_draw()
        return True

    def _drag_begin(self, gesture, _x, _y):
        if self.zoom <= 1:
            gesture.set_state(Gtk.EventSequenceState.DENIED)
            return
        self.drag_origin = self.offset

    def _drag_update(self, gesture, dx, dy):
        if self.drag_origin is not None:
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            self.set_cursor_from_name('grabbing')
            self.offset = (self.drag_origin[0] + dx, self.drag_origin[1] + dy)
            self._clamp()
            self.queue_draw()

    def _drag_end(self, _gesture, _dx, _dy):
        self.drag_origin = None
        self.set_cursor_from_name('grab' if self.zoom > 1 else 'default')

    def _pressed(self, gesture, count, _x, _y):
        if count == 2:
            self.zoom = 1.0
            self.offset = (0.0, 0.0)
            self.drag_origin = None
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            self.set_cursor_from_name('default')
            self.queue_draw()
