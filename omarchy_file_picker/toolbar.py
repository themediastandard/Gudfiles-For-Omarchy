"""Keep navigation together and wrap toolbar actions when space is limited."""
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Graphene', '1.0')
from gi.repository import Graphene, Gsk, Gtk


class AdaptiveToolbar(Gtk.Widget):
    __gtype_name__ = 'GudfilesAdaptiveToolbar'
    spacing = 8

    def __init__(self, *, compact=False):
        super().__init__(hexpand=True)
        self.compact = compact
        if compact:
            self.spacing = 2
        self.navigation = Gtk.Box(spacing=self.spacing)
        self.actions = Gtk.Box(spacing=self.spacing)
        for row in (self.navigation, self.actions):
            row.set_parent(self)
        self.add_css_class('toolbar')
        if compact:
            self.add_css_class('compact-toolbar')

    def do_get_request_mode(self):
        return Gtk.SizeRequestMode.HEIGHT_FOR_WIDTH

    def set_controls_sensitive(self, sensitive):
        self.navigation.set_sensitive(sensitive)
        child = self.actions.get_first_child()
        while child:
            if not isinstance(child, Gtk.WindowControls) and not child.has_css_class('header-utility'):
                child.set_sensitive(sensitive)
            child = child.get_next_sibling()

    def _widths(self):
        return [row.measure(Gtk.Orientation.HORIZONTAL, -1)[:2]
                for row in (self.navigation, self.actions)]

    def do_measure(self, orientation, for_size):
        nav, actions = self._widths()
        if orientation == Gtk.Orientation.HORIZONTAL:
            minimum = nav[0] + self.spacing + actions[1] if self.compact else max(nav[0], actions[0])
            return minimum, nav[1] + self.spacing + actions[1], -1, -1
        wrapped = not self.compact and 0 <= for_size < nav[0] + self.spacing + actions[1]
        nav_width = for_size if wrapped or for_size < 0 else for_size - actions[1] - self.spacing
        heights = [self.navigation.measure(orientation, nav_width),
                   self.actions.measure(orientation, actions[1])]
        combine = (lambda values: sum(values) + self.spacing) if wrapped else max
        return combine([h[0] for h in heights]), combine([h[1] for h in heights]), -1, -1

    def do_size_allocate(self, width, height, baseline):
        nav, actions = self._widths()
        actions_width = min(width, actions[1])
        if not self.compact and width < nav[0] + self.spacing + actions[1]:
            nav_height = self.navigation.measure(Gtk.Orientation.VERTICAL, width)[1]
            actions_height = self.actions.measure(Gtk.Orientation.VERTICAL, actions_width)[1]
            self.navigation.allocate(width, nav_height, -1, None)
            x, y = width - actions_width, nav_height + self.spacing
        else:
            self.navigation.allocate(width - actions_width - self.spacing, height, -1, None)
            actions_height = height
            x, y = width - actions_width, 0
        self.actions.allocate(actions_width, actions_height, -1,
                              Gsk.Transform.new().translate(Graphene.Point().init(x, y)))

    def do_snapshot(self, snapshot):
        self.snapshot_child(self.navigation, snapshot)
        self.snapshot_child(self.actions, snapshot)

    def do_unroot(self):
        for row in (self.navigation, self.actions):
            row.unparent()
        Gtk.Widget.do_unroot(self)
