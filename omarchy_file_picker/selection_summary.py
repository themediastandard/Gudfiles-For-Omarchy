"""A bounded, collective preview for multiple selected items (no directory scan)."""
from gi.repository import Gdk, Gtk, Pango


class SelectionStack(Gtk.DrawingArea):
    def __init__(self, colors, kind):
        super().__init__(width_request=132, height_request=76, valign=Gtk.Align.CENTER)
        self.kind = kind
        self.accent, self.background = Gdk.RGBA(), Gdk.RGBA()
        self.accent.parse(colors['accent'])
        self.background.parse(colors['background'])
        self.set_draw_func(self._draw)

    def _color(self, cr, opacity):
        a, b = self.accent, self.background
        cr.set_source_rgb(b.red + (a.red - b.red) * opacity,
                          b.green + (a.green - b.green) * opacity,
                          b.blue + (a.blue - b.blue) * opacity)

    def _folder(self, cr, x, y, opacity):
        cr.save()
        cr.translate(x, y)
        cr.move_to(5, 0)
        cr.line_to(23, 0)
        cr.line_to(30, 7)
        cr.line_to(62, 7)
        cr.curve_to(65, 7, 67, 9, 67, 12)
        cr.line_to(67, 43)
        cr.curve_to(67, 46, 65, 48, 62, 48)
        cr.line_to(5, 48)
        cr.curve_to(2, 48, 0, 46, 0, 43)
        cr.line_to(0, 5)
        cr.curve_to(0, 2, 2, 0, 5, 0)
        cr.close_path()
        self._color(cr, opacity)
        cr.fill()
        cr.set_source_rgba(1, 1, 1, .16)
        cr.set_line_width(1)
        cr.move_to(5, 15)
        cr.line_to(62, 15)
        cr.stroke()
        cr.restore()

    def _document(self, cr, x, y, opacity):
        cr.save()
        cr.translate(x, y)
        cr.move_to(4, 0)
        cr.line_to(29, 0)
        cr.line_to(42, 13)
        cr.line_to(42, 50)
        cr.curve_to(42, 53, 40, 55, 37, 55)
        cr.line_to(4, 55)
        cr.curve_to(1, 55, 0, 53, 0, 50)
        cr.line_to(0, 5)
        cr.curve_to(0, 2, 1, 0, 4, 0)
        cr.close_path()
        self._color(cr, opacity)
        cr.fill()
        cr.set_source_rgba(1, 1, 1, .3)
        cr.move_to(29, 0)
        cr.line_to(29, 13)
        cr.line_to(42, 13)
        cr.fill()
        cr.set_line_width(2)
        for y in (26, 33, 40):
            cr.move_to(9, y)
            cr.line_to(31 if y != 40 else 24, y)
        cr.stroke()
        cr.restore()

    def _draw(self, _area, cr, width, height):
        cr.translate((width - 132) / 2, (height - 76) / 2)
        if self.kind == 'files':
            for x, y, shade in ((54, 2, .3), (44, 10, .5), (34, 18, .9)):
                self._document(cr, x, y, shade)
        else:
            for x, y, shade in ((41, 5, .3), (31, 14, .5), (21, 23, .9)):
                self._folder(cr, x, y, shade)
            if self.kind == 'mixed':
                cr.save()
                cr.translate(76, 29)
                cr.scale(.7, .7)
                self._document(cr, 0, 0, .6)
                cr.restore()


def show_selection_summary(owner, paths):
    """Called after canceling single-file detail work and clearing the strip."""
    folders = sum(path.is_dir() for path in paths)
    files = len(paths) - folders
    kind = 'folders' if not files else 'files' if not folders else 'mixed'
    owner.metadata.append(SelectionStack(owner.colors, kind))
    primary = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3, hexpand=True)
    primary.set_size_request(140, -1)
    title = Gtk.Label(label=f'{len(paths):,} items selected', xalign=0)
    title.add_css_class('metadata-title')
    title.set_ellipsize(Pango.EllipsizeMode.END)
    primary.append(title)
    parts = []
    if folders:
        parts.append(f'{folders:,} ' + ('folder' if folders == 1 else 'folders'))
    if files:
        parts.append(f'{files:,} ' + ('file' if files == 1 else 'files'))
    detail = Gtk.Label(label=' · '.join(parts), xalign=0)
    detail.add_css_class('muted')
    detail.set_ellipsize(Pango.EllipsizeMode.END)
    primary.append(detail)
    primary.append(owner._rating_controls(paths))
    owner.metadata.append(primary)
