"""Bounded, read-only creative metadata; selection changes never block GTK."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from fractions import Fraction
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
from typing import Callable


IMAGE_SUFFIXES = {'.avif', '.bmp', '.gif', '.heic', '.heif', '.jpeg', '.jpg',
                  '.png', '.tif', '.tiff', '.webp', '.dng', '.cr2', '.cr3',
                  '.nef', '.arw', '.orf', '.raf', '.rw2'}
MEDIA_SUFFIXES = {'.avi', '.m4v', '.mkv', '.mov', '.mp4', '.webm', '.mts',
                  '.m2ts', '.mxf', '.mpg', '.mpeg', '.wav', '.mp3', '.flac',
                  '.aac', '.m4a', '.ogg', '.opus', '.aif', '.aiff', '.wma'}
MAX_OUTPUT = 128 * 1024


@dataclass(frozen=True)
class MediaDetails:
    summary: str = ''
    fields: tuple[tuple[str, str], ...] = ()

    @property
    def tooltip(self) -> str:
        return '\n'.join(f'{key}: {value}' for key, value in self.fields)


def _text(value: object) -> str:
    return ' '.join(str(value or '').split())[:180]


def _positive(value: object) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) and number > 0 else None
    except (ValueError, TypeError, OverflowError):
        return None


def _duration(value: object) -> str:
    seconds = _positive(value)
    if seconds is None:
        return ''
    total = round(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f'{hours}:{minutes:02d}:{seconds:02d}' if hours else f'{minutes}:{seconds:02d}'


def _run(command: list[str]) -> str:
    # A file-backed stdout avoids an unbounded in-memory pipe for malformed
    # metadata. The parser receives only a small, complete output, never a prefix.
    with tempfile.TemporaryFile() as output:
        subprocess.run(command, stdin=subprocess.DEVNULL, stdout=output,
                       stderr=subprocess.DEVNULL, timeout=6, check=True)
        output.seek(0)
        data = output.read(MAX_OUTPUT + 1)
        if len(data) > MAX_OUTPUT:
            raise ValueError('Metadata output exceeds limit')
        return data.decode('utf-8', errors='replace')


def _stream_depth(stream: dict) -> str:
    for key in ('bits_per_raw_sample', 'bits_per_sample'):
        depth = _positive(stream.get(key))
        if depth is not None and depth <= 64:
            return f'{depth:g}-bit'
    # Only formats with an explicit, unambiguous component depth are inferred.
    pixel = str(stream.get('pix_fmt', ''))
    explicit = re.search(r'(?:p|gray|rgb|bgr|gbrp)(9|10|12|14|16)(?:le|be)?$', pixel)
    if explicit:
        return f'{explicit.group(1)}-bit'
    if pixel in {'yuv420p', 'yuv422p', 'yuv444p', 'yuvj420p', 'yuvj422p',
                 'yuvj444p', 'nv12', 'nv21', 'rgb24', 'bgr24', 'rgba', 'bgra', 'gray'}:
        return '8-bit'
    return ''


def details_from_probe(data: dict) -> MediaDetails:
    """Parse only reported fields; absent metadata stays absent."""
    streams = data.get('streams', [])
    if not isinstance(streams, list):
        return MediaDetails()
    streams = [item for item in streams if isinstance(item, dict)]
    video = next((s for s in streams if s.get('codec_type') == 'video'
                  and not s.get('disposition', {}).get('attached_pic')), {})
    audio = next((s for s in streams if s.get('codec_type') == 'audio'), {})
    container = data.get('format', {})
    container = container if isinstance(container, dict) else {}
    fields: list[tuple[str, str]] = []
    summary: list[str] = []
    width, height = _positive(video.get('width')), _positive(video.get('height'))
    if width and height:
        resolution = f'{width:g} × {height:g}'
        fields.append(('Resolution', resolution))
        summary.append(resolution)
    if video:
        try:
            fps = float(Fraction(video.get('avg_frame_rate') or '0'))
        except (ValueError, TypeError, ZeroDivisionError, OverflowError):
            fps = 0
        if math.isfinite(fps) and 0 < fps < 10000:
            rate = f'{fps:.3f}'.rstrip('0').rstrip('.') + ' fps'
            fields.append(('Frame rate', rate))
            summary.append(rate)
        codec = _text(video.get('codec_name')).upper()
        profile = _text(video.get('profile'))
        if codec:
            fields.append(('Video codec', codec + (f' · {profile}' if profile else '')))
            summary.append(codec)
        depth = _stream_depth(video)
        if depth:
            fields.append(('Video depth', depth))
    duration = _duration(container.get('duration') or video.get('duration') or audio.get('duration'))
    if duration:
        fields.append(('Duration', duration))
        summary.append(duration)
    if audio:
        codec = _text(audio.get('codec_name')).upper()
        if codec:
            fields.append(('Audio codec', codec))
            if not video:
                summary.insert(0, codec)
        channels = _positive(audio.get('channels'))
        layout = _text(audio.get('channel_layout'))
        if channels:
            value = f'{channels:g} channel' + ('s' if channels != 1 else '')
            fields.append(('Audio channels', value + (f' · {layout}' if layout else '')))
            if not video:
                summary.append(layout or value)
        sample_rate = _positive(audio.get('sample_rate'))
        if sample_rate:
            fields.append(('Sample rate', f'{sample_rate / 1000:g} kHz'))
        depth = _stream_depth(audio)
        if depth:
            fields.append(('Audio depth', depth))
    tags = dict(container.get('tags') or {})
    tags.update(video.get('tags') or {})
    tags = {str(key).lower(): value for key, value in tags.items()}
    for label, keys in (
        ('Camera make', ('com.apple.quicktime.make', 'make')),
        ('Camera model', ('com.apple.quicktime.model', 'model')),
        ('Captured', ('com.apple.quicktime.creationdate', 'creation_time')),
    ):
        value = next((_text(tags[key]) for key in keys if tags.get(key)), '')
        if value:
            fields.append((label, value))
    return MediaDetails(' · '.join(summary), tuple(fields))


def _image_details(path: Path) -> MediaDetails:
    executable = shutil.which('magick') or shutil.which('identify')
    if not executable:
        return MediaDetails()
    exif_keys = ('Make', 'Model', 'LensModel', 'ISOSpeedRatings',
                 'ExposureTime', 'FNumber', 'DateTimeOriginal')
    template = '\x1e'.join(('%w', '%h', '%z', '%m') + tuple(f'%[EXIF:{key}]' for key in exif_keys))
    command = [executable] + (['identify'] if Path(executable).name == 'magick' else [])
    # Read the first frame only. Local absolute input prevents option/URI parsing.
    values = _run(command + ['-limit', 'memory', '64MiB', '-limit', 'map', '128MiB',
                             '-quiet', '-ping', '-format', template, str(path.absolute()) + '[0]']).split('\x1e')
    if len(values) != 11:
        return MediaDetails()
    width, height = _positive(values[0]), _positive(values[1])
    if not width or not height:
        return MediaDetails()
    resolution = f'{width:g} × {height:g}'
    fields = [('Resolution', resolution), ('Format', _text(values[3]))]
    depth = _positive(values[2])
    if depth:
        fields.append(('Image depth', f'{depth:g}-bit'))
    for label, value in zip(('Camera make', 'Camera model', 'Lens', 'ISO',
                              'Exposure', 'Aperture', 'Captured'), values[4:]):
        if _text(value):
            rendered = _text(value)
            if label in {'Exposure', 'Aperture'}:
                try:
                    fraction = Fraction(rendered)
                    if fraction > 0:
                        if label == 'Aperture':
                            rendered = f'f/{float(fraction):g}'
                        elif fraction < 1 and fraction.numerator == 1:
                            rendered = f'1/{fraction.denominator} s'
                        else:
                            rendered = f'{float(fraction):g} s'
                except (ValueError, ZeroDivisionError, OverflowError):
                    pass
            fields.append((label, rendered))
    summary = resolution + (f' · {depth:g}-bit' if depth else '')
    return MediaDetails(summary, tuple(fields))


def probe_media(path: Path) -> MediaDetails:
    """Run on a worker: tolerate missing dependencies, unreadable and bad files."""
    try:
        if not path.is_file():
            return MediaDetails()
        if path.suffix.casefold() in IMAGE_SUFFIXES:
            return _image_details(path)
        if path.suffix.casefold() not in MEDIA_SUFFIXES:
            return MediaDetails()
        executable = shutil.which('ffprobe')
        if not executable:
            return MediaDetails()
        data = json.loads(_run([
            executable, '-v', 'error', '-probesize', '5000000',
            '-analyzeduration', '5000000', '-show_entries',
            'stream=codec_type,codec_name,profile,width,height,pix_fmt,avg_frame_rate,'
            'duration,bits_per_raw_sample,bits_per_sample,channels,channel_layout,sample_rate:'
            'stream_disposition=attached_pic:stream_tags=make,model,creation_time,'
            'com.apple.quicktime.make,com.apple.quicktime.model,com.apple.quicktime.creationdate:'
            'format=duration:format_tags=make,model,creation_time,com.apple.quicktime.make,'
            'com.apple.quicktime.model,com.apple.quicktime.creationdate',
            '-of', 'json', '-i', str(path.absolute()),
        ]))
        return details_from_probe(data) if isinstance(data, dict) else MediaDetails()
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, AttributeError):
        return MediaDetails()


class MediaDetailsService:
    """One active probe + one replacement request; no unbounded job queue."""

    def __init__(self, *, dispatch=None, probe=probe_media, cache_size: int = 128):
        if dispatch is None:
            from gi.repository import GLib
            dispatch = GLib.idle_add
        self._dispatch = dispatch
        self._probe = probe
        self._cache_size = max(1, cache_size)
        self._cache: OrderedDict[tuple, MediaDetails] = OrderedDict()
        self._condition = threading.Condition()
        self._pending = None
        self._generation = 0
        self._closed = False
        self._worker = threading.Thread(target=self._work, daemon=True, name='media-details')
        self._worker.start()

    def request(self, path: Path, callback: Callable[[MediaDetails], None]) -> int:
        with self._condition:
            self._generation += 1
            if not self._closed:
                self._pending = (self._generation, Path(path), callback)
                self._condition.notify()
            return self._generation

    def cancel(self) -> None:
        with self._condition:
            self._generation += 1
            self._pending = None

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._generation += 1
            self._pending = None
            self._condition.notify()

    @staticmethod
    def _key(path: Path) -> tuple:
        stat = path.stat()
        return (str(path.absolute()), stat.st_dev, stat.st_ino, stat.st_size,
                stat.st_mtime_ns, stat.st_ctime_ns)

    def _work(self) -> None:
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._pending is not None or self._closed)
                if self._closed:
                    return
                generation, path, callback = self._pending
                self._pending = None
            try:
                key = self._key(path)
                result = self._cache.get(key)
                if result is None:
                    result = self._probe(path)
                    if self._key(path) != key:
                        result = MediaDetails()  # It changed while being inspected.
                    else:
                        self._cache[key] = result
                if key in self._cache:
                    self._cache.move_to_end(key)
                while len(self._cache) > self._cache_size:
                    self._cache.popitem(last=False)
            except (OSError, ValueError):
                result = MediaDetails()

            def deliver(generation=generation, result=result, callback=callback):
                with self._condition:
                    valid = not self._closed and generation == self._generation
                if valid:
                    callback(result)
                return False

            with self._condition:
                if self._closed:
                    return
            self._dispatch(deliver)


def make_details_widget(service: MediaDetailsService, path: Path):
    """A single bounded line; an anchored information card, never a busy menu."""
    import gi
    gi.require_version('Gtk', '4.0')
    from gi.repository import Gtk, Pango

    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    row.add_css_class('media-details-row')
    row.set_hexpand(True)
    summary = Gtk.Label(label='Reading media…', xalign=0)
    summary.add_css_class('muted')
    summary.set_hexpand(True)
    summary.set_ellipsize(Pango.EllipsizeMode.END)
    summary.set_max_width_chars(20)
    row.append(summary)
    button = Gtk.MenuButton(icon_name='dialog-information-symbolic')
    button.add_css_class('flat')
    button.add_css_class('media-details-button')
    button.set_tooltip_text('Media details')
    button.set_visible(False)
    row.append(button)

    def ready(details: MediaDetails) -> None:
        if not details.fields:
            row.set_visible(False)
            return
        summary.set_text(details.summary or 'Media details')
        summary.set_tooltip_text(details.tooltip)
        popover = Gtk.Popover()
        popover.add_css_class('media-details-popover')
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        content.add_css_class('media-details-content')
        for setter in ('set_margin_top', 'set_margin_bottom', 'set_margin_start', 'set_margin_end'):
            getattr(content, setter)(16)
        heading = Gtk.Label(label='Media details', xalign=0)
        heading.add_css_class('metadata-title')
        content.append(heading)
        grid = Gtk.Grid(column_spacing=18, row_spacing=8)
        for index, (key, value) in enumerate(details.fields):
            key_label = Gtk.Label(label=key, xalign=0)
            key_label.add_css_class('muted')
            key_label.add_css_class('media-details-key')
            value_label = Gtk.Label(label=value, xalign=0)
            value_label.add_css_class('media-details-value')
            value_label.set_ellipsize(Pango.EllipsizeMode.END)
            value_label.set_max_width_chars(28)
            value_label.set_tooltip_text(value)
            value_label.set_selectable(True)
            grid.attach(key_label, 0, index, 1, 1)
            grid.attach(value_label, 1, index, 1, 1)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_propagate_natural_width(True)
        scroller.set_min_content_width(300)
        scroller.set_max_content_width(380)
        scroller.set_propagate_natural_height(True)
        scroller.set_max_content_height(340)
        scroller.set_child(grid)
        content.append(scroller)
        popover.set_child(content)
        button.set_popover(popover)
        button.set_visible(True)

    service.request(path, ready)
    return row
