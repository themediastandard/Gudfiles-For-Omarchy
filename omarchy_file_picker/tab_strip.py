"""Equal-width tabs with clipped, interruptible native open/close motion."""
import math

import gi
gi.require_version('Graphene', '1.0')
from gi.repository import GLib, Graphene, Gsk, Gtk


class TabSlot(Gtk.Widget):
    def __init__(self, content, weight):
        super().__init__()
        self.content = content
        self.weight = self.initial = weight
        self.target = 1.0
        self.started = 0
        self.set_overflow(Gtk.Overflow.HIDDEN)
        content.set_parent(self)

    def do_measure(self, orientation, for_size):
        if orientation == Gtk.Orientation.HORIZONTAL:
            return 0, 0, -1, -1
        return self.content.measure(orientation, for_size)

    def do_size_allocate(self, width, height, baseline):
        minimum = self.content.measure(Gtk.Orientation.HORIZONTAL, -1)[0]
        offset = 4 * (1 - self.weight)
        self.content.allocate(max(width, minimum), height, baseline,
                              Gsk.Transform.new().translate(Graphene.Point().init(0, offset)))

    def do_snapshot(self, snapshot):
        snapshot.push_opacity(self.weight)
        self.snapshot_child(self.content, snapshot)
        snapshot.pop()

    def do_unroot(self):
        self.content.unparent()
        Gtk.Widget.do_unroot(self)


class AnimatedTabStrip(Gtk.Widget):
    duration = 220_000
    spacing = 0

    def __init__(self):
        super().__init__(hexpand=True)
        self.slots = []
        self.tick_id = 0
        self.settings_handler = 0
        self.connect('map', self._connect_settings)
        self.connect('unrealize', self._stop)

    def _connect_settings(self, *_):
        if not self.settings_handler:
            self.settings_handler = self.get_settings().connect('notify::gtk-enable-animations', self._animations_changed)

    def _stop(self, *_):
        if self.settings_handler:
            self.get_settings().disconnect(self.settings_handler)
            self.settings_handler = 0
        self.finish()

    def _animations_changed(self, settings, _property):
        if not settings.get_property('gtk-enable-animations'):
            self.finish()

    def _motion_enabled(self):
        settings = self.get_settings()
        return self.get_mapped() and (not settings or settings.get_property('gtk-enable-animations'))

    def append(self, widget):
        slot = TabSlot(widget, 0.0 if self._motion_enabled() else 1.0)
        self.slots.append(slot)
        slot.set_parent(self)
        self._animate(slot, 1.0)

    def remove(self, widget):
        slot = next((item for item in self.slots if item.content is widget), None)
        if slot is not None:
            # Logical closure is immediate. Its disappearing visual cannot
            # receive another close, keyboard focus, or a file/tab drop.
            slot.set_sensitive(False)
            slot.set_can_target(False)
            self._animate(slot, 0.0)

    def reorder_child_after(self, widget, previous):
        self.finish()
        slot = next(item for item in self.slots if item.content is widget)
        self.slots.remove(slot)
        index = next((i + 1 for i, item in enumerate(self.slots) if item.content is previous), 0)
        self.slots.insert(index, slot)
        slot.insert_after(self, self.slots[index - 1] if index else None)
        self.queue_resize()

    def _animate(self, slot, target):
        slot.initial, slot.target = slot.weight, target
        slot.started = GLib.get_monotonic_time()
        if not self._motion_enabled():
            self.finish()
        elif not self.tick_id:
            self.tick_id = self.add_tick_callback(self._tick)
        self.queue_resize()

    def _tick(self, _widget, clock):
        if not self._motion_enabled():
            self.tick_id = 0
            self._settle()
            return False
        moving = False
        for slot in list(self.slots):
            elapsed = min(1.0, max(0.0, (clock.get_frame_time() - slot.started) / self.duration))
            eased = 1 - (1 - elapsed) ** 3
            slot.weight = slot.initial + (slot.target - slot.initial) * eased
            moving |= elapsed < 1 and slot.initial != slot.target
            if elapsed >= 1 and slot.target == 0:
                self.slots.remove(slot)
                slot.unparent()
            else:
                slot.queue_allocate()
                slot.queue_draw()
        self.queue_resize()
        if not moving:
            self.tick_id = 0
        return moving

    def finish(self):
        if self.tick_id:
            self.remove_tick_callback(self.tick_id)
            self.tick_id = 0
        self._settle()

    def _settle(self):
        for slot in list(self.slots):
            slot.weight = slot.initial = slot.target
            if slot.target == 0:
                self.slots.remove(slot)
                slot.unparent()
            else:
                slot.queue_allocate()
                slot.queue_draw()
        self.queue_resize()

    def _metrics(self):
        minimum = max((slot.content.measure(Gtk.Orientation.HORIZONTAL, -1)[0]
                       for slot in self.slots), default=0)
        return minimum, sum(slot.weight for slot in self.slots)

    def do_measure(self, orientation, for_size):
        if orientation == Gtk.Orientation.HORIZONTAL:
            minimum, weights = self._metrics()
            width = max(0, math.ceil((minimum + self.spacing) * weights - self.spacing))
            return width, width, -1, -1
        height = max((slot.content.measure(orientation, for_size)[1] for slot in self.slots), default=24)
        return height, height, -1, -1

    def do_size_allocate(self, width, height, baseline):
        minimum, weights = self._metrics()
        # Animate each tab's full width-plus-gap allocation, trimming the final
        # gap. Removing a zero-width tab then leaves identical geometry even in
        # the middle of the strip; independently shrinking gaps causes a snap.
        extent = max(minimum + self.spacing, (width + self.spacing) / weights) if weights else 0
        x = 0.0
        for slot in self.slots:
            end = x + extent * slot.weight
            slot.allocate(max(0, round(end) - round(x) - self.spacing), height, baseline,
                          Gsk.Transform.new().translate(Graphene.Point().init(round(x), 0)))
            x = end

    def do_snapshot(self, snapshot):
        for slot in self.slots:
            self.snapshot_child(slot, snapshot)

    def do_unroot(self):
        self._stop()
        for slot in self.slots:
            slot.unparent()
        self.slots.clear()
        Gtk.Widget.do_unroot(self)
