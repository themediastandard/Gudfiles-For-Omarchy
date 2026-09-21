"""Compact file-area controls and cancellable selection-size summaries."""
import threading

from gi.repository import GLib, Gtk, Pango

from .model import format_size
from .selection_summary import selection_totals
from .thumbnail_widgets import SCHEDULER, Thumbnail


class ViewStatus(Gtk.CenterBox):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.add_css_class('file-view-status')
        self.resize_timer = 0
        self.closed = False
        self.selection = None
        self.totals = None
        self.pending = None
        self.running = False
        self.cancelled = threading.Event()
        controls = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
        icon = Gtk.Image.new_from_icon_name('view-grid-symbolic')
        icon.set_pixel_size(12)
        controls.append(icon)
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 96, 312, 12)
        self.scale.set_draw_value(False)
        self.scale.set_size_request(132, -1)
        self.scale.set_value(owner.file_preferences['thumbnail_size'])
        self.scale.update_property([Gtk.AccessibleProperty.LABEL], ['Thumbnail size'])
        self.scale.set_tooltip_text('Thumbnail size')
        self.scale.connect('value-changed', self.resize)
        controls.append(self.scale)
        self.set_start_widget(controls)
        self.summary = Gtk.Label(ellipsize=Pango.EllipsizeMode.END, max_width_chars=52)
        self.set_center_widget(self.summary)
        # Symmetric reserve keeps the summary centered in the file area.
        self.set_end_widget(Gtk.Box(width_request=162))
        owner.connect('unrealize', self.close)

    def update(self, paths):
        thumbnails = self.owner.view_mode == 'grid'
        self.scale.set_sensitive(thumbnails)
        self.get_start_widget().set_visible(thumbnails)
        self.get_end_widget().set_visible(thumbnails)
        paths = tuple(paths)
        if paths == self.selection:
            return
        self.selection = paths
        self.totals = None
        self.owner.folder_sizes.select(paths)
        self.cancelled.set()
        self.pending = paths or None
        if not paths:
            self.summary.set_text('')
            return
        self.summary.set_text(f'{len(paths):,} selected · Calculating…')
        self._start_summary()

    def _start_summary(self):
        if self.running or self.closed or self.pending is None:
            return
        paths, self.pending = self.pending, None
        self.running = True
        cancelled = self.cancelled = threading.Event()

        def done(result):
            self.running = False
            if not self.closed and not cancelled.is_set() and paths == self.selection and result is not None:
                self.totals = result
                self.render_summary()
            self._start_summary()
            return False

        def work():
            result = selection_totals(paths, cancelled=cancelled.is_set)
            GLib.idle_add(done, result)
        threading.Thread(target=work, name='selection-size', daemon=True).start()

    def render_summary(self):
        if self.closed or not self.selection or self.totals is None:
            return
        folders, files, total, unavailable = self.totals
        counts = []
        if files:
            counts.append(f'{files:,} ' + ('file' if files == 1 else 'files'))
        if folders:
            counts.append(f'{folders:,} ' + ('folder' if folders == 1 else 'folders'))
        pending = False
        for path in self.owner.folder_sizes.selected:
            result = self.owner.folder_sizes.result(path)
            if result is None:
                pending = True
            else:
                total += result.total
                unavailable += not result.complete
        if pending:
            size = 'Calculating…'
        elif unavailable:
            size = '≥ ' + format_size(total) + ' known' if total else 'Size unavailable'
        else:
            size = format_size(total)
        self.summary.set_text(', '.join(counts) + ' · ' + size)
        self.summary.set_tooltip_text('Logical size of selected contents, including subfolders. Symbolic links inside folders are excluded.'
                                      if folders else None)

    def resize(self, scale):
        if self.closed or self.owner.view_mode != 'grid':
            return
        width = round(scale.get_value())
        self.owner.file_preferences['thumbnail_size'] = width
        if self.owner.special_mode == 'trash':
            self.owner.trash_page.resize_tiles(width)
        else:
            for child in self.owner.children_by_path.values():
                self.size_tile(child.get_child(), width)
        if self.resize_timer:
            GLib.source_remove(self.resize_timer)
        self.resize_timer = GLib.timeout_add(180, self._finish_resize)

    @staticmethod
    def size_tile(item, width):
        parts = getattr(item, '_grid_size_parts', None)
        if parts is None:
            return
        poster, name, detail = parts
        height = round(width * 98 / 156)
        item.set_size_request(width + 4, height + 40)
        poster.set_size_request(width, height)
        if isinstance(poster, Thumbnail):
            poster.width, poster.height = width, height
            poster.image.set_pixel_size(min(64, max(24, height - 18)))
        else:
            poster.set_pixel_size(min(64, max(24, height - 18)))
        chars = max(8, width // 9)
        name.set_width_chars(chars)
        name.set_max_width_chars(chars)
        if detail is not None:
            detail.set_max_width_chars(chars)

    def _finish_resize(self):
        self.resize_timer = 0
        self.owner._set_file_preference('thumbnail_size', round(self.scale.get_value()), reload=False)
        # Keep existing images painted while dragging; refresh their bounded
        # cached textures once the slider settles. Rows and selection stay put.
        if self.owner.special_mode != 'trash':
            for child in self.owner.children_by_path.values():
                parts = getattr(child.get_child(), '_grid_size_parts', None)
                if parts and isinstance(parts[0], Thumbnail):
                    parts[0].release()
        if not self.closed:
            SCHEDULER.wake()
        return False

    def close(self, *_):
        self.closed = True
        self.pending = None
        self.cancelled.set()
        if self.resize_timer:
            GLib.source_remove(self.resize_timer)
            self._finish_resize()
