"""Viewport-only thumbnail scheduling; two workers and no pending decode queue."""
from __future__ import annotations

import threading
import weakref

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk

from .thumbnails import IMAGE_TYPES, RAW_TYPES, VIDEO_TYPES, _valid_png


class ThumbnailScheduler:
    def __init__(self):
        self.widgets = weakref.WeakKeyDictionary()
        self.running = 0
        self.timer = 0
        self.wake_id = 0
        self.sequence = 0

    def add(self, widget):
        self.widgets[widget] = self.sequence
        self.sequence += 1
        if not self.timer:
            self.timer = GLib.timeout_add(50, self.tick)
        self.wake()

    def wake(self):
        if not self.wake_id:
            self.wake_id = GLib.idle_add(self._wake)

    def _wake(self):
        self.wake_id = 0
        self._pump()
        return GLib.SOURCE_REMOVE

    def remove(self, widget):
        self.widgets.pop(widget, None)
        widget.release()

    def tick(self):
        self._pump()
        if not self.widgets and not self.running:
            self.timer = 0
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    def _pump(self):
        # Stable display order; selection previews go ahead of unfinished tiles.
        for widget in sorted(self.widgets, key=lambda w: (w.priority, self.widgets[w])):
            if not widget.in_view():
                widget.release()
            elif not widget.loaded and not widget.failed and widget.cancelled is None and self.running < 2:
                self.start(widget)

    def start(self, widget):
        self.running += 1
        cancelled = widget.cancelled = threading.Event()
        ref = weakref.ref(widget)
        path, width, height, loader = widget.path, widget.width, widget.height, widget.loader

        def work():
            pixbuf = None
            try:
                source = loader(path, cancelled=cancelled.is_set)
                if source and not cancelled.is_set():
                    # Only bounded decoder output enters the application process.
                    if _valid_png(source):
                        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(source), width, height, True)
            except Exception:
                # Unreadable/unsupported media retains its ordinary file icon.
                pass
            GLib.idle_add(done, pixbuf)

        def done(pixbuf):
            self.running -= 1
            target = ref()
            if target is not None and target.cancelled is cancelled:
                target.cancelled = None
                if not cancelled.is_set() and target.in_view():
                    target.failed = pixbuf is None
                    if pixbuf is not None:
                        target.picture.set_paintable(Gdk.Texture.new_for_pixbuf(pixbuf))
                        target.image.set_visible(False)
                        target.loaded = True
                        if target.on_loaded:
                            target.on_loaded(pixbuf)
            self.wake()
            return GLib.SOURCE_REMOVE

        threading.Thread(target=work, name='file-thumbnail', daemon=True).start()


SCHEDULER = ThumbnailScheduler()


class Thumbnail(Gtk.Overlay):
    def __init__(self, path, width, height, icon, loader, *, crop=True, priority=1):
        super().__init__()
        self.path, self.width, self.height, self.loader = path, width, height, loader
        self.priority = priority
        self.loaded = self.failed = False
        self.on_loaded = None
        self.cancelled = None
        self.set_size_request(width, height)
        self.image = Gtk.Image.new_from_gicon(icon)
        self.image.set_pixel_size(min(64, max(14, height - 18)))
        self.image.add_css_class('muted')
        self.set_child(self.image)
        self.picture = Gtk.Picture()
        self.picture.set_content_fit(Gtk.ContentFit.COVER if crop else Gtk.ContentFit.CONTAIN)
        self.picture.set_can_shrink(True)
        self.add_overlay(self.picture)
        self.set_measure_overlay(self.picture, False)
        self.set_clip_overlay(self.picture, True)
        if path.suffix.casefold() in IMAGE_TYPES | RAW_TYPES | VIDEO_TYPES:
            self.connect('map', lambda *_: SCHEDULER.add(self))
            self.connect('unmap', lambda *_: SCHEDULER.remove(self))

    def in_view(self):
        if not self.get_mapped() or self.get_width() <= 0:
            return False
        parent = self.get_parent()
        while parent is not None:
            if isinstance(parent, Gtk.ScrolledWindow):
                valid, bounds = self.compute_bounds(parent)
                if not valid or bounds.get_y() + bounds.get_height() <= 0 or \
                        bounds.get_y() >= parent.get_height() or \
                        bounds.get_x() + bounds.get_width() <= 0 or bounds.get_x() >= parent.get_width():
                    return False
            parent = parent.get_parent()
        return True

    def release(self):
        if self.cancelled is not None:
            self.cancelled.set()
            self.cancelled = None
        if self.loaded:
            self.picture.set_paintable(None)
            self.image.set_visible(True)
            self.loaded = False
