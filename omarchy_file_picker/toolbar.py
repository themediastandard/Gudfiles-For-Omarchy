"""Keep navigation together and wrap toolbar actions when space is limited."""
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Graphene', '1.0')
from gi.repository import Graphene, Gsk, Gtk


class AdaptiveToolbar(Gtk.Widget):
    __gtype_name__ = 'GudfilesAdaptiveToolbar'
    spacing = 8

    def __init__(self):
        super().__init__(hexpand=True)
        self.navigation = Gtk.Box(spacing=self.spacing)
        self.actions = Gtk.Box(spacing=self.spacing)
        for row in (self.navigation, self.actions):
            row.set_parent(self)
        self.add_css_class('toolbar')

    def do_get_request_mode(self):
        return Gtk.SizeRequestMode.HEIGHT_FOR_WIDTH

    def _widths(self):
        return [row.measure(Gtk.Orientation.HORIZONTAL, -1)[:2]
                for row in (self.navigation, self.actions)]

    def do_measure(self, orientation, for_size):
        nav, actions = self._widths()
        if orientation == Gtk.Orientation.HORIZONTAL:
            return max(nav[0], actions[0]), nav[1] + self.spacing + actions[1], -1, -1
        wrapped = 0 <= for_size < nav[0] + self.spacing + actions[1]
        nav_width = for_size if wrapped or for_size < 0 else for_size - actions[1] - self.spacing
        heights = [self.navigation.measure(orientation, nav_width),
                   self.actions.measure(orientation, actions[1])]
        combine = (lambda values: sum(values) + self.spacing) if wrapped else max
        return combine([h[0] for h in heights]), combine([h[1] for h in heights]), -1, -1

    def do_size_allocate(self, width, height, baseline):
        nav, actions = self._widths()
        actions_width = min(width, actions[1])
        if width < nav[0] + self.spacing + actions[1]:
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
