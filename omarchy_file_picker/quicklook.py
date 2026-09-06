"""Read-only Quick Look, animated within the picker rather than a new window."""
from __future__ import annotations

import io
import mimetypes
import threading
from pathlib import Path

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Graphene', '1.0')
from gi.repository import Gdk, GdkPixbuf, GLib, Graphene, Gsk, Gtk, Pango

from .model import file_type, format_size


def point(x, y):
    return Graphene.Point().init(x, y)


def read_preview(path: Path):
    """Bound rendered size and text reads; never execute or modify the file."""
    if not path.is_file():
        return 'info', 'Folder' if path.is_dir() else 'This file is no longer available.'
    mime = mimetypes.guess_type(path.name)[0] or ''
    if mime.startswith('image/'):
        pixels = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(path), 1800, 1400, True)
        return 'image', pixels
    if mime == 'application/pdf':
        gi.require_version('Poppler', '0.18')
        gi.require_foreign('cairo')
        from gi.repository import Poppler
        import cairo
        doc = Poppler.Document.new_from_file(path.absolute().as_uri(), None)
        page = doc.get_page(0)
        width, height = page.get_size()
        scale = min(1600 / width, 1400 / height, 2)
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, int(width * scale), int(height * scale))
        context = cairo.Context(surface)
        context.set_source_rgb(1, 1, 1)
        context.paint()
        context.scale(scale, scale)
        page.render(context)
        output = io.BytesIO()
        surface.write_to_png(output)
        return 'pdf', (output.getvalue(), doc.get_n_pages())
    if mime.startswith(('video/', 'audio/')):
        return 'media', None
    with path.open('rb') as stream:
        sample = stream.read(128 * 1024 + 1)
    if b'\0' not in sample:
        try:
            text = sample[:128 * 1024].decode('utf-8')
            if len(sample) > 128 * 1024:
                text += '\n\n[Preview limited to the first 128 KB]'
            return 'text', text
        except UnicodeDecodeError:
            pass
    return 'info', 'No built-in preview for this file type.'


class QuickLook(Gtk.Widget):
    __gtype_name__ = 'OmarchyQuickLook'

    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.path = None
        self.progress = 0.0
        self.target = 0.0
        self.tick_id = 0
        self.generation = 0
        self.media = None
        self.origin = (0, 0, 100, 100)
        self.rect = (0, 0, 1, 1)
        self.kind = None
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_focusable(True)
        self.set_overflow(Gtk.Overflow.HIDDEN)

        self.card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.card.add_css_class('quicklook-card')
        self.card.set_parent(self)
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        bar.add_css_class('quicklook-bar')
        self.card.append(bar)
        close = Gtk.Button.new_from_icon_name('window-close-symbolic')
        close.set_tooltip_text('Close preview (Space / Escape)')
        close.connect('clicked', lambda *_: self.close())
        bar.append(close)
        self.title = Gtk.Label(xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.MIDDLE)
        self.title.add_css_class('metadata-title')
        bar.append(self.title)
        for icon, step, name in [('go-previous-symbolic', -1, 'Previous file'),
                                  ('go-next-symbolic', 1, 'Next file')]:
            button = Gtk.Button.new_from_icon_name(icon)
            button.set_tooltip_text(name)
            button.connect('clicked', lambda _b, s=step: self.step(s))
            bar.append(button)
        self.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, vexpand=True, hexpand=True)
        self.content.add_css_class('quicklook-content')
        self.card.append(self.content)
        self.caption = Gtk.Label(ellipsize=Pango.EllipsizeMode.MIDDLE)
        self.caption.add_css_class('quicklook-caption')
        self.card.append(self.caption)
        click = Gtk.GestureClick()
        click.connect('pressed', self._backdrop_click)
        self.add_controller(click)
        self.set_visible(False)

    def do_measure(self, orientation, for_size):
        return 0, 0, -1, -1

    def do_size_allocate(self, width, height, baseline):
        w, h = max(1, min(940, width - 64)), max(1, min(720, height - 56))
        x, y = (width - w) / 2, (height - h) / 2
        self.rect = x, y, w, h
        self.card.allocate(w, h, -1, Gsk.Transform.new().translate(point(x, y)))

    def do_snapshot(self, snapshot):
        if self.progress <= 0:
            return
        shade = Gdk.RGBA()
        shade.parse('#10131b')
        shade.alpha = 0.24 * self.progress
        snapshot.append_color(shade, Graphene.Rect().init(0, 0, self.get_width(), self.get_height()))
        x, y, w, h = self.rect
        ox, oy, ow, oh = self.origin
        initial_scale = max(0.08, min(ow / w, oh / h, 0.4))
        scale = initial_scale + (1 - initial_scale) * self.progress
        cx = (ox + ow / 2) * (1 - self.progress) + (x + w / 2) * self.progress
        cy = (oy + oh / 2) * (1 - self.progress) + (y + h / 2) * self.progress
        snapshot.save()
        snapshot.translate(point(cx - w * scale / 2, cy - h * scale / 2))
        snapshot.scale(scale, scale)
        snapshot.translate(point(-x, -y))
        snapshot.push_opacity(min(1, self.progress * 3))
        self.snapshot_child(self.card, snapshot)
        snapshot.pop()
        snapshot.restore()

    def _animate(self, target):
        if self.tick_id:
            self.remove_tick_callback(self.tick_id)
            self.tick_id = 0
        self.target = target
        settings = self.get_settings()
        if settings and not settings.get_property('gtk-enable-animations'):
            self.progress = target
            self._animation_done()
            return
        start, initial = GLib.get_monotonic_time(), self.progress
        duration = 240000 * max(0.3, abs(target - initial))
        def tick(_widget, clock):
            elapsed = max(0, min(1, (clock.get_frame_time() - start) / duration))
            eased = 1 - (1 - elapsed) ** 3
            self.progress = initial + (target - initial) * eased
            self.queue_draw()
            if elapsed >= 1:
                self.tick_id = 0
                self._animation_done()
                return False
            return True
        self.tick_id = self.add_tick_callback(tick)

    def _animation_done(self):
        self.queue_draw()
        if self.target == 0:
            self.set_visible(False)
            self._clear_content()
            self.owner.preview_overlay.get_child().set_sensitive(True)
            child = self.owner.children_by_path.get(self.path)
            if child:
                child.grab_focus()
            else:
                self.owner.flow.grab_focus()

    def _source_rect(self, path):
        child = self.owner.children_by_path.get(path)
        if child:
            valid, bounds = child.compute_bounds(self.owner.preview_overlay)
            if valid:
                return bounds.get_x(), bounds.get_y(), bounds.get_width(), bounds.get_height()
        return self.owner.get_width() / 2, self.owner.get_height() / 2, 80, 80

    def show_file(self, path):
        self.path = path
        self.origin = self._source_rect(path)
        self.owner._close_context_menu()
        self.owner.preview_overlay.get_child().set_sensitive(False)
        self.set_visible(True)
        self.grab_focus()
        self._load_file(path)
        self._animate(1.0)

    def close(self):
        self.generation += 1  # Ignore late decoder results after closing.
        if self.media:
            self.media.pause()
        self.origin = self._source_rect(self.path)
        self._animate(0.0)

    def _clear_content(self):
        if self.media:
            self.media.pause()
            self.media = None
        while child := self.content.get_first_child():
            self.content.remove(child)

    def _message(self, text):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16, valign=Gtk.Align.CENTER, vexpand=True)
        icon = Gtk.Image.new_from_icon_name('document-preview-symbolic')
        icon.set_pixel_size(64)
        box.append(icon)
        box.append(Gtk.Label(label=text, wrap=True, max_width_chars=60, justify=Gtk.Justification.CENTER))
        self.content.append(box)

    def _load_file(self, path):
        self.generation += 1
        generation = self.generation
        self._clear_content()
        self.title.set_text(path.name)
        try:
            self.details = f'{file_type(path)}  ·  {format_size(path.stat().st_size)}'
        except OSError:
            self.details = 'Unavailable file'
        self.caption.set_text(self.details + '  ·  Space to close  ·  ← → Browse')
        self._message('Loading preview…')
        self.kind = 'loading'
        def worker():
            try:
                kind, data = read_preview(path)
            except Exception as error:
                kind, data = 'info', f'Preview unavailable: {error}'
            GLib.idle_add(self._loaded, generation, kind, data)
        threading.Thread(target=worker, daemon=True).start()

    def _loaded(self, generation, kind, data):
        if generation != self.generation or not self.get_visible():
            return False
        self._clear_content()
        self.kind = kind
        if kind in ('image', 'pdf'):
            texture = (Gdk.Texture.new_for_pixbuf(data) if kind == 'image' else
                       Gdk.Texture.new_from_bytes(GLib.Bytes.new(data[0])))
            picture = Gtk.Picture.new_for_paintable(texture)
            picture.set_content_fit(Gtk.ContentFit.CONTAIN)
            picture.set_can_shrink(True)
            picture.set_vexpand(True)
            self.content.append(picture)
            if kind == 'pdf':
                self.caption.set_text(f'{self.details}  ·  Page 1 of {data[1]}  ·  Space to close')
        elif kind == 'text':
            view = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
            view.get_buffer().set_text(data)
            for side in ('top', 'bottom', 'left', 'right'):
                getattr(view, 'set_' + side + '_margin')(24)
            scroller = Gtk.ScrolledWindow(vexpand=True)
            scroller.set_child(view)
            self.content.append(scroller)
        elif kind == 'media':
            video = Gtk.Video.new_for_filename(str(self.path))
            video.set_vexpand(True)
            video.set_autoplay(True)
            self.media = video.get_media_stream()
            self.media.connect('notify::error', self._media_error, generation)
            self.content.append(video)
            self._media_error(self.media, None, generation)
        else:
            self._message(data)
        return False

    def _media_error(self, media, _property, generation):
        if generation == self.generation and media.get_error():
            error = media.get_error().message
            self._clear_content()
            if 'plug-in' in error.lower() or 'plugin' in error.lower():
                self._message('Playback needs additional media codecs.\nInstall gst-plugins-good and gst-libav to play this file.')
            else:
                self._message('Media preview unavailable.\n' + error.splitlines()[0][:200])
            self.kind = 'info'

    def step(self, direction):
        files = [p for p in self.owner.entries if p.is_file()]
        if self.path not in files:
            return
        index = files.index(self.path) + direction
        if 0 <= index < len(files):
            self.path = files[index]
            self.owner.flow.unselect_all()
            self.owner.flow.select_child(self.owner.children_by_path[self.path])
            self._load_file(self.path)

    def _backdrop_click(self, gesture, _count, x, y):
        rx, ry, width, height = self.rect
        if not (rx <= x <= rx + width and ry <= y <= ry + height):
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            self.close()

    def do_unroot(self):
        self.generation += 1
        if self.tick_id:
            self.remove_tick_callback(self.tick_id)
            self.tick_id = 0
        self._clear_content()
        self.card.unparent()
        Gtk.Widget.do_unroot(self)
