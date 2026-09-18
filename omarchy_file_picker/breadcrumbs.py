"""Connected chevron buttons, with overlapping allocation and accurate hit tests."""
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Graphene', '1.0')
from gi.repository import Gdk, Graphene, Gsk, Gtk, Pango

TIP = 10


class BreadcrumbButton(Gtk.Button):
    __gtype_name__ = 'OmarchyBreadcrumbButton'

    def __init__(self, text, colors, *, first=False, current=False):
        super().__init__(label=text)
        self.set_tooltip_text(text)
        self.colors, self.first, self.current = colors, first, current
        self.add_css_class('path-segment')
        if current:
            self.add_css_class('current')
        self.get_child().set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self.get_child().set_max_width_chars(22)
        # Keep padding on the label, so the custom snapshot spans the whole
        # button instead of GTK's smaller CSS content box.
        self.get_child().set_margin_start(12 if first else 20)
        self.get_child().set_margin_end(20)
        self.connect('state-flags-changed', lambda *_: self.queue_draw())

    def do_snapshot(self, snapshot):
        w, h = self.get_width(), self.get_height()
        if not w or not h:
            return
        hovered = bool(self.get_state_flags() & (Gtk.StateFlags.PRELIGHT | Gtk.StateFlags.ACTIVE))
        color = Gdk.RGBA()
        color.parse(self.colors['selection' if self.current else 'lighter_background' if hovered else 'dark_background'])
        cr = snapshot.append_cairo(Graphene.Rect().init(0, 0, w, h))
        cr.move_to(0, 0)
        cr.line_to(w - TIP, 0)
        cr.line_to(w, h / 2)
        cr.line_to(w - TIP, h)
        cr.line_to(0, h)
        if not self.first:
            cr.line_to(TIP, h / 2)
        cr.close_path()
        cr.set_source_rgba(color.red, color.green, color.blue, color.alpha)
        cr.fill_preserve()
        border = Gdk.RGBA()
        border.parse(self.colors['background'])
        cr.set_source_rgba(border.red, border.green, border.blue, 1)
        cr.set_line_width(1.5)
        cr.stroke()
        Gtk.Button.do_snapshot(self, snapshot)

    def do_contains(self, x, y):
        w, h = self.get_width(), self.get_height()
        if not (0 <= x <= w and 0 <= y <= h) or h <= 0:
            return False
        notch = TIP * (1 - abs(2 * y / h - 1))
        return (self.first or x >= notch) and x <= w - TIP + notch


class BreadcrumbTrail(Gtk.Widget):
    __gtype_name__ = 'OmarchyBreadcrumbTrail'

    def __init__(self):
        super().__init__(hexpand=True)
        self.buttons = []

    def append(self, button):
        self.buttons.append(button)
        button.set_parent(self)
        self.queue_resize()

    def remove(self, button):
        self.buttons.remove(button)
        button.unparent()
        self.queue_resize()

    def do_measure(self, orientation, for_size):
        sizes = [button.measure(orientation, -1) for button in self.buttons]
        if orientation == Gtk.Orientation.HORIZONTAL:
            width = max(0, sum(size[1] for size in sizes) - TIP * max(0, len(sizes) - 1))
            return width, width, -1, -1
        height = max((size[1] for size in sizes), default=0)
        return height, height, -1, -1

    def do_size_allocate(self, width, height, baseline):
        x = 0
        for button in self.buttons:
            size = button.measure(Gtk.Orientation.HORIZONTAL, -1)[1]
            button.allocate(size, height, baseline, Gsk.Transform.new().translate(Graphene.Point().init(x, 0)))
            x += size - TIP

    def do_snapshot(self, snapshot):
        for button in self.buttons:
            self.snapshot_child(button, snapshot)

    def do_unroot(self):
        for button in list(self.buttons):
            self.remove(button)
        Gtk.Widget.do_unroot(self)


def scroll_breadcrumbs(controller, dx, dy, adjustment):
    delta = dx if abs(dx) > abs(dy) else dy
    if controller.get_unit() == Gdk.ScrollUnit.WHEEL:
        delta *= 48
    adjustment.set_value(max(adjustment.get_lower(), min(
        adjustment.get_upper() - adjustment.get_page_size(), adjustment.get_value() + delta)))
    return True
