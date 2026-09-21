"""Shared, viewport-driven folder sizes for rows and the selection status."""
import time

from gi.repository import GLib

from .folder_sizes import FolderSizeWorker
from .model import format_size


class FolderSizes:
    TTL = 60

    def __init__(self, owner):
        self.owner = owner
        self.labels = []
        self.results = {}
        self.selected = ()
        self.active = None
        self.worker = FolderSizeWorker(GLib.idle_add)
        self.timer = GLib.timeout_add(160, self.tick)
        owner.connect('unrealize', self.close)

    def invalidate(self):
        self.worker.cancel()
        self.active = None
        self.results.clear()

    def reset(self):
        self.worker.cancel()
        self.active = None
        self.results.clear()
        self.selected = ()
        self.labels.clear()

    def close(self, *_):
        self.worker.close()
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = 0

    def bind(self, path, label):
        self.labels.append((path, label))
        self.paint(path, label)

    def select(self, paths):
        self.selected = tuple(p for p in paths if self.owner._entry_is_dir(p))
        if self.selected and self.active not in self.selected:
            self.worker.cancel()
            self.active = None
        self.tick()

    def result(self, path):
        record = self.results.get(path)
        if record and (self.owner.file_preferences['sort_key'] == 'size' or
                       time.monotonic() - record[0] < self.TTL):
            return record[1]
        return None

    def paint(self, path, label):
        result = self.result(path)
        if result is None:
            label.set_text('…')
            label.set_tooltip_text('Calculating folder size…')
        else:
            text = format_size(result.total)
            if not result.complete:
                text = '≥ ' + text if result.total else 'Unavailable'
            label.set_text(text)
            label.set_tooltip_text(f'{result.total:,} bytes in folder contents · Symbolic links excluded'
                                   + (f' · {result.reason}' if result.reason else ''))

    def visible(self, label):
        if not label.get_mapped():
            return False
        viewport = self.owner.columns if self.owner.view_mode == 'columns' else self.owner.standard_scroller
        valid, bounds = label.compute_bounds(viewport)
        return (valid and bounds.get_y() + bounds.get_height() > 0 and bounds.get_y() < viewport.get_height()
                and bounds.get_x() + bounds.get_width() > 0 and bounds.get_x() < viewport.get_width())

    def tick(self):
        if not self.owner.get_mapped() or self.owner.special_mode == 'trash':
            if self.active is not None:
                self.worker.cancel()
                self.active = None
            return True
        candidates = list(self.selected)
        live = []
        for path, label in self.labels:
            if label.get_root() is None:
                continue
            live.append((path, label))
            if self.visible(label):
                self.paint(path, label)
                candidates.append(path)
        self.labels = live
        if self.owner.file_preferences['sort_key'] == 'size':
            candidates.extend(p for p in self.owner.entries if self.owner._entry_is_dir(p))
        # A folder that has left the viewport must not monopolize a NAS scan.
        if self.active is not None and self.active not in candidates:
            self.worker.cancel()
            self.active = None
        if self.active is None:
            for path in candidates:
                if self.result(path) is None:
                    self.active = path
                    self.started = time.monotonic()
                    self.worker.submit(path, self.ready)
                    break
        # Drop old/offscreen records instead of growing a navigation cache.
        wanted = set(candidates)
        self.results = {p: r for p, r in self.results.items() if p in wanted}
        status = getattr(self.owner, 'view_status', None)
        if status:
            status.render_summary()
        return True

    def ready(self, path, result):
        self.active = None
        self.results[path] = (self.started, result)
        self.tick()
