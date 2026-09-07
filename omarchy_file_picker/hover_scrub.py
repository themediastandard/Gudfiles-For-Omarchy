"""Silent, bounded thumbnail scrubbing. No source media or disk cache is written."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import json
import math
from pathlib import Path
import subprocess
import threading
import weakref

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gdk, GLib, Gtk


SCRUB_STEPS = 48
HOVER_DELAY_MS = 220
POLL_MS = 90
MAX_FRAME_BYTES = 512 * 1024


def scrub_step(fraction: float) -> int:
    """Quantize motion so every pointer pixel does not start another decoder."""
    return round(max(0.0, min(1.0, fraction)) * (SCRUB_STEPS - 1))


@dataclass(frozen=True)
class ScrubFrame:
    data: bytes
    seconds: float
    duration: float
    step: int


class FrameCache:
    """Used on one worker at a time; bounded by entries AND compressed bytes."""
    def __init__(self, max_frames=72, max_bytes=12 * 1024 * 1024):
        self.frames = OrderedDict()
        self.durations = OrderedDict()
        self.max_frames = max_frames
        self.max_bytes = max_bytes
        self.bytes = 0

    def _remember(self, key, result):
        previous = self.frames.pop(key, None)
        if previous:
            self.bytes -= len(previous.data)
        self.frames[key] = result
        self.bytes += len(result.data)
        while self.frames and (len(self.frames) > self.max_frames or self.bytes > self.max_bytes):
            _, oldest = self.frames.popitem(last=False)
            self.bytes -= len(oldest.data)

    def frame(self, path: Path, step: int) -> ScrubFrame | None:
        try:
            stat = path.stat()
            identity = (str(path.absolute()), stat.st_mtime_ns, stat.st_size)
            step = max(0, min(SCRUB_STEPS - 1, int(step)))
            key = (*identity, step)
            if key in self.frames:
                self.frames.move_to_end(key)
                return self.frames[key]
            duration = self.durations.get(identity)
            if duration is None:
                probe = subprocess.run(
                    ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                     '-of', 'json', str(path.absolute())],
                    capture_output=True, timeout=4, check=True,
                )
                duration = float(json.loads(probe.stdout).get('format', {}).get('duration', 0))
                if not math.isfinite(duration) or duration <= 0:
                    return None
                self.durations[identity] = duration
                while len(self.durations) > 128:
                    self.durations.popitem(last=False)
            else:
                self.durations.move_to_end(identity)
            # Seeking exactly to EOF produces no frame; stay just before it.
            seconds = step / (SCRUB_STEPS - 1) * max(0, duration - min(.25, duration / 2))
            output = subprocess.run(
                ['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error',
                 '-threads', '1', '-ss', f'{seconds:.6f}', '-i', str(path.absolute()),
                 '-map', '0:v:0', '-an', '-sn', '-dn', '-frames:v', '1',
                 '-vf', 'scale=320:180:force_original_aspect_ratio=decrease',
                 '-threads', '1', '-f', 'image2pipe', '-vcodec', 'mjpeg', '-q:v', '5', 'pipe:1'],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=6, check=True,
            )
            if not output.stdout or len(output.stdout) > MAX_FRAME_BYTES:
                return None
            frame = ScrubFrame(output.stdout, seconds, duration, step)
            self._remember(key, frame)
            return frame
        except (OSError, subprocess.SubprocessError, ValueError, TypeError, AttributeError):
            # Missing tools, broken clips and slow/offline NAS files keep their poster.
            return None


class ScrubWorker:
    """One running extraction, no queued jobs or per-thumbnail thread pools."""
    def __init__(self):
        self.cache = FrameCache()
        self._slot = threading.BoundedSemaphore(1)

    def request(self, path, step, callback) -> bool:
        if not self._slot.acquire(blocking=False):
            return False

        def run():
            try:
                frame = self.cache.frame(path, step)
            finally:
                self._slot.release()
            GLib.idle_add(callback, frame)

        threading.Thread(target=run, name='thumbnail-scrub', daemon=True).start()
        return True


_WORKER = ScrubWorker()


class HoverScrub(Gtk.Overlay):
    """Wrap a pre-sized thumbnail; motion never consumes click/selection gestures."""
    __gtype_name__ = 'OmarchyHoverScrub'

    def __init__(self, path: Path, thumbnail: Gtk.Widget, *, worker=None):
        super().__init__()
        self.path = path
        self.worker = worker or _WORKER
        self.active = False
        self.fraction = 0.0
        self.displayed_step = None
        self.frame = None
        self._generation = 0
        self._busy = False
        self._timer = 0
        self.set_child(thumbnail)
        self.set_overflow(Gtk.Overflow.HIDDEN)
        self.set_tooltip_text('Move across to skim · Space to watch')
        self.picture = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, can_shrink=True)
        self.picture.set_can_target(False)
        self.picture.set_visible(False)
        self.add_overlay(self.picture)
        self.set_measure_overlay(self.picture, False)
        self.set_clip_overlay(self.picture, True)
        self.track = Gtk.DrawingArea(height_request=3, valign=Gtk.Align.END)
        self.track.set_can_target(False)
        self.track.add_css_class('hover-scrub-track')
        self.track.set_visible(False)
        self.track.set_draw_func(self._draw_track)
        self.add_overlay(self.track)
        self.set_measure_overlay(self.track, False)
        self.set_clip_overlay(self.track, True)
        self.motion = Gtk.EventControllerMotion()
        self.motion.connect('enter', self._enter)
        self.motion.connect('motion', self._motion)
        self.motion.connect('leave', self._leave)
        self.add_controller(self.motion)
        self.connect('unmap', self._leave)

    def _draw_track(self, area, cr, width, height):
        cr.set_source_rgba(0, 0, 0, .22)
        cr.paint()
        color = area.get_color()
        cr.set_source_rgba(color.red, color.green, color.blue, .95)
        cr.rectangle(0, 0, max(2, width * self.fraction), height)
        cr.fill()

    def _enter(self, controller, x, y):
        if self.active:
            self._motion(controller, x, y)
            return
        self.active = True
        self._generation += 1
        self._motion(controller, x, y)
        self._timer = GLib.timeout_add(HOVER_DELAY_MS, self._start)

    def _motion(self, controller, x, _y):
        # Do not skim while the user is dragging files or selecting a range.
        state = controller.get_current_event_state()
        if state & (Gdk.ModifierType.BUTTON1_MASK | Gdk.ModifierType.BUTTON2_MASK |
                    Gdk.ModifierType.BUTTON3_MASK):
            self._leave(controller)
            return
        self.fraction = max(0, min(1, x / max(1, self.get_width())))
        self.track.queue_draw()

    def _start(self):
        self._timer = 0
        if self.active:
            self._tick()
            self._timer = GLib.timeout_add(POLL_MS, self._tick)
        return False

    def _tick(self):
        if not self.active:
            self._timer = 0
            return False
        step = scrub_step(self.fraction)
        if self._busy or self.displayed_step == step:
            return True
        generation = self._generation
        ref = weakref.ref(self)

        def complete(frame):
            widget = ref()
            if widget is not None:
                widget._complete(generation, step, frame)
            return False

        if self.worker.request(self.path, step, complete):
            self._busy = True
        return True

    def _complete(self, generation, step, frame):
        self._busy = False
        if not self.active or generation != self._generation or not self.get_mapped():
            return
        if frame is None:
            # One failed extraction per hover, not an endless failed subprocess loop.
            self._leave()
            return
        if step != scrub_step(self.fraction):
            return
        try:
            texture = Gdk.Texture.new_from_bytes(GLib.Bytes.new(frame.data))
        except GLib.Error:
            self._leave()
            return
        self.displayed_step = step
        self.frame = frame
        self.picture.set_paintable(texture)
        self.picture.set_visible(True)
        self.track.set_visible(True)
        self.track.queue_draw()

    def _leave(self, *_args):
        self.active = False
        self._generation += 1
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0
        self.displayed_step = None
        self.frame = None
        self.picture.set_visible(False)
        self.picture.set_paintable(None)
        self.track.set_visible(False)
