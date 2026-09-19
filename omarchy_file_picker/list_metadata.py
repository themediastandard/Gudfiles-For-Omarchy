"""Read-only list metadata with one worker and a replaceable, bounded batch."""
from collections import OrderedDict
from datetime import datetime
import stat
import threading

from .media_details import probe_media, IMAGE_SUFFIXES, MEDIA_SUFFIXES

COLUMNS = {
    'name': ('Name', 220), 'size': ('Size', 92), 'type': ('Type', 130),
    'created': ('Date Created', 156), 'modified': ('Date Modified', 156),
    'resolution': ('Resolution', 120), 'fps': ('FPS', 76),
    'duration': ('Duration', 90), 'codec': ('Codec', 130),
}
DEFAULT_COLUMNS = ['name', 'size', 'modified', 'resolution', 'fps']
MEDIA_COLUMNS = {'resolution', 'fps', 'duration', 'codec'}
EXTRA_SORTS = MEDIA_COLUMNS | {'created'}


def normalize_columns(columns):
    if not isinstance(columns, list):
        return list(DEFAULT_COLUMNS)
    return ['name'] + [key for key in COLUMNS if key != 'name' and key in columns]


def media_values(details):
    fields = dict(details.fields)
    result = {}
    try:
        width, height = (int(v.strip()) for v in fields.get('Resolution', '').split('×'))
        if width > 0 and height > 0:
            result['resolution'] = (width * height, width, height)
    except ValueError:
        pass
    try:
        result['fps'] = float(fields['Frame rate'].removesuffix(' fps'))
    except (KeyError, ValueError):
        pass
    try:
        result['duration'] = sum(int(v) * 60 ** i for i, v in
                                 enumerate(reversed(fields['Duration'].split(':'))))
    except (KeyError, ValueError):
        pass
    result['codec'] = fields.get('Video codec') or fields.get('Audio codec') or fields.get('Format')
    return result


def read_values(path, want_media=False):
    from gi.repository import Gio, GLib
    info = path.stat()
    directory = stat.S_ISDIR(info.st_mode)
    values = dict(directory=directory, size=None if directory else info.st_size,
                  modified=info.st_mtime, created=None, _media=False)
    # On Linux ctime is metadata-change time, never a substitute for birth time.
    try:
        attributes = Gio.File.new_for_path(str(path)).query_info(
            'time::created', Gio.FileQueryInfoFlags.NONE, None)
        if attributes.has_attribute('time::created'):
            value = attributes.get_attribute_uint64('time::created')
            values['created'] = value if value > 0 else None
    except GLib.Error:
        pass
    if want_media:
        if not directory and path.suffix.casefold() in IMAGE_SUFFIXES | MEDIA_SUFFIXES:
            values.update(media_values(probe_media(path)))
        values['_media'] = True
    return values


def format_value(key, values, *, show_time=True):
    from .model import format_size
    value = values.get(key)
    if value is None:
        return '—'
    if key == 'size':
        return format_size(value)
    if key in {'created', 'modified'}:
        try:
            return datetime.fromtimestamp(value).strftime('%b %-d, %Y %H:%M' if show_time else '%b %-d, %Y')
        except (OSError, ValueError, OverflowError):
            return '—'
    if key == 'resolution':
        return f'{value[1]} × {value[2]}'
    if key == 'fps':
        return f'{value:g}'
    if key == 'duration':
        hours, remainder = divmod(int(value), 3600)
        minutes, seconds = divmod(remainder, 60)
        return f'{hours}:{minutes:02d}:{seconds:02d}' if hours else f'{minutes}:{seconds:02d}'
    return str(value)


class ListMetadataWorker:
    def __init__(self, dispatch, reader=read_values):
        self.dispatch, self.reader = dispatch, reader
        self.condition = threading.Condition()
        self.generation = 0
        self.closed = False
        self.pending = None
        self.cache = OrderedDict()
        threading.Thread(target=self.run, daemon=True, name='list-metadata').start()

    def cancel(self):
        with self.condition:
            self.generation += 1
            self.pending = None

    def close(self):
        with self.condition:
            self.closed = True
            self.generation += 1
            self.pending = None
            self.condition.notify()

    def submit(self, paths, want_media, callback):
        with self.condition:
            self.generation += 1
            self.pending = (self.generation, tuple(paths)[:16], want_media, callback)
            self.condition.notify()

    def valid(self, generation):
        with self.condition:
            return not self.closed and generation == self.generation

    @staticmethod
    def identity(path):
        info = path.stat()
        return (str(path), info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)

    def run(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.closed or self.pending is not None)
                if self.closed:
                    return
                generation, paths, want_media, callback = self.pending
                self.pending = None
            for index, path in enumerate(paths):
                if not self.valid(generation):
                    break
                try:
                    identity = self.identity(path)
                    values = self.cache.get(identity)
                    if values is None or (want_media and not values.get('_media')):
                        values = self.reader(path, want_media)
                        if self.identity(path) == identity:
                            self.cache[identity] = values
                        else:
                            values = dict(_media=want_media)
                    if identity in self.cache:
                        self.cache.move_to_end(identity)
                    while len(self.cache) > 512:
                        self.cache.popitem(last=False)
                except Exception:
                    values = dict(_media=want_media)
                def deliver(path=path, values=values, last=index == len(paths) - 1,
                            generation=generation, callback=callback):
                    if self.valid(generation):
                        callback(path, values, last)
                    return False
                if self.valid(generation):
                    self.dispatch(deliver)
