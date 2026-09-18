"""Bounded filename searches in a disposable process, independent of GTK."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import threading
import time

from .model import FileFilter

SEARCH_SECONDS = 15
SEARCH_LIMIT = 500
VIRTUAL_ROOTS = {'/proc', '/sys', '/dev', '/run'}


@dataclass
class SearchResult:
    paths: list[Path] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    skipped: int = 0
    limited: bool = False
    timed_out: bool = False
    error: str = ''


def scan(options, emit):
    """Walk real directories once; never descend through directory symlinks."""
    needle = options['query'].strip().casefold()
    if not needle:
        emit(dict(done=True))
        return
    rule = options.get('filter')
    active_filter = FileFilter.from_portal(rule) if rule else None
    deadline = time.monotonic() + options.get('seconds', SEARCH_SECONDS)
    limit = options.get('limit', SEARCH_LIMIT)
    seen, emitted = set(), set()
    skipped = count = 0
    # Roots are ordered with the user's files before the rest of the machine.
    pending = list(reversed([Path(p) for p in options['roots']]))
    while pending:
        if time.monotonic() >= deadline:
            emit(dict(done=True, timed_out=True, skipped=skipped))
            return
        folder = pending.pop()
        try:
            identity = folder.stat()
            key = (identity.st_dev, identity.st_ino)
            if key in seen:
                continue
            seen.add(key)
            with os.scandir(folder) as entries:
                for entry in entries:
                    if time.monotonic() >= deadline:
                        emit(dict(done=True, timed_out=True, skipped=skipped))
                        return
                    if not options.get('hidden') and entry.name.startswith('.'):
                        continue
                    path = Path(entry.path)
                    if str(path) in VIRTUAL_ROOTS:
                        continue
                    try:
                        is_dir = entry.is_dir(follow_symlinks=False)
                        if is_dir:
                            pending.append(path)
                        if needle not in entry.name.casefold() or path in emitted:
                            continue
                        if options.get('directories_only') and not entry.is_dir():
                            continue
                        if active_filter and not active_filter.matches(path):
                            continue
                        emitted.add(path)
                        info = entry.stat()
                        emit(dict(path=str(path), directory=entry.is_dir(),
                                  size=info.st_size, modified=info.st_mtime))
                        count += 1
                        if count >= limit:
                            emit(dict(done=True, limited=True, skipped=skipped))
                            return
                    except OSError:
                        skipped += 1
        except OSError:
            skipped += 1
    emit(dict(done=True, skipped=skipped))


def run_search(options, cancelled, *, command=None):
    """Stream matches so a blocked filesystem can be killed without losing them."""
    result = SearchResult()
    command = command or [sys.executable, '-m', 'omarchy_file_picker.search', json.dumps(options)]
    deadline = time.monotonic() + options.get('seconds', SEARCH_SECONDS) + 1
    # Propagate this installation, including source runs whose cwd later changes.
    env = dict(os.environ)
    env['PYTHONPATH'] = str(Path(__file__).resolve().parent.parent)
    try:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, env=env)
    except OSError as error:
        result.error = str(error)
        return result
    buffer, done = b'', False
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while not done:
                if cancelled.is_set():
                    return result
                if time.monotonic() >= deadline:
                    result.timed_out = True
                    break
                if not selector.select(.05):
                    continue
                data = os.read(process.stdout.fileno(), 65536)
                if not data:
                    result.error = 'The search stopped unexpectedly. Try again.'
                    break
                buffer += data
                while b'\n' in buffer:
                    line, buffer = buffer.split(b'\n', 1)
                    record = json.loads(line)
                    if 'path' in record:
                        path = Path(record['path'])
                        result.paths.append(path)
                        result.metadata[path] = record
                    if record.get('done'):
                        result.skipped = record.get('skipped', 0)
                        result.limited = record.get('limited', False)
                        result.timed_out = record.get('timed_out', False)
                        done = True
    except (OSError, ValueError) as error:
        result.error = str(error)
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        process.stdout.close()
    return result


class SearchService:
    """One active worker and one replaceable pending request per window."""
    def __init__(self):
        self.condition = threading.Condition()
        self.pending = None
        self.cancelled = threading.Event()
        self.closed = False
        self.worker = threading.Thread(target=self._work, daemon=True)
        self.worker.start()

    def submit(self, options, callback):
        with self.condition:
            if self.closed:
                return
            self.cancelled.set()
            self.pending = (options, callback)
            self.condition.notify()

    def cancel(self):
        with self.condition:
            self.cancelled.set()
            self.pending = None

    def close(self):
        with self.condition:
            self.closed = True
            self.cancelled.set()
            self.pending = None
            self.condition.notify()
        # Closing the application must let the worker reap its subprocess;
        # otherwise interpreter shutdown could abandon a running search.
        self.worker.join(timeout=1)

    def _work(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.closed or self.pending is not None)
                if self.closed:
                    return
                options, callback = self.pending
                self.pending = None
                self.cancelled = cancelled = threading.Event()
            result = run_search(options, cancelled)
            if not cancelled.is_set():
                callback(result)


if __name__ == '__main__':
    scan(json.loads(sys.argv[1]), lambda record: print(json.dumps(record), flush=True))
