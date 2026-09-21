"""Bounded logical folder sizes; scans run in a disposable child process."""
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import threading
import time


@dataclass(frozen=True)
class FolderSize:
    total: int = 0
    complete: bool = False
    reason: str = 'Folder could not be read'


def scan_folder(path, *, max_entries=1_000_000, seconds=30):
    """Sum regular-file lengths, including hidden files, without following links.

    This is logical content size, not allocated disk space. Hard-linked entries
    count once per name, like separately selected files. Partial scans never
    masquerade as complete totals.
    """
    deadline = time.monotonic() + seconds
    total = count = 0
    reason = ''
    pending = [os.fspath(path)]
    try:
        initial = os.lstat(path)
        if not stat.S_ISDIR(initial.st_mode):
            return FolderSize(reason='Linked folders are not scanned' if stat.S_ISLNK(initial.st_mode)
                              else 'Folder is unavailable')
        while pending:
            if time.monotonic() >= deadline:
                return FolderSize(total, False, 'Calculation time limit reached')
            current = pending.pop()
            try:
                fd = os.open(current, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                try:
                    with os.scandir(fd) as entries:
                        for entry in entries:
                            count += 1
                            if count > max_entries or time.monotonic() >= deadline:
                                return FolderSize(total, False, 'Calculation limit reached')
                            try:
                                info = entry.stat(follow_symlinks=False)
                                if stat.S_ISREG(info.st_mode):
                                    total += info.st_size
                                elif stat.S_ISDIR(info.st_mode):
                                    if len(pending) >= 4096:
                                        return FolderSize(total, False, 'Calculation limit reached')
                                    pending.append(os.path.join(current, entry.name))
                            except OSError:
                                reason = 'Some contents could not be read'
                finally:
                    os.close(fd)
            except OSError:
                reason = 'Some contents could not be read'
        final = os.lstat(path)
        if (initial.st_dev, initial.st_ino, initial.st_mtime_ns) != (final.st_dev, final.st_ino, final.st_mtime_ns):
            reason = 'Folder changed during calculation'
    except OSError:
        reason = 'Folder could not be read'
    return FolderSize(total, not reason, reason)


def read_folder(path, cancelled, *, timeout=32, command=None):
    """Bound even a blocked filesystem read; cancellation releases the worker."""
    if cancelled():
        return None
    process = None
    try:
        command = command or [sys.executable, str(Path(__file__).resolve()), str(path)]
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + timeout
        while process.poll() is None:
            if cancelled():
                return None
            if time.monotonic() >= deadline:
                return FolderSize(reason='Folder size calculation timed out')
            time.sleep(.04)
        payload = process.stdout.read(4096)
        if process.returncode != 0:
            return FolderSize()
        data = json.loads(payload)
        if (type(data.get('total')) is not int or data['total'] < 0 or
                type(data.get('complete')) is not bool or not isinstance(data.get('reason'), str)):
            return FolderSize()
        return FolderSize(**data)
    except (OSError, ValueError, TypeError):
        return FolderSize()
    finally:
        if process is not None:
            if process.poll() is None:
                process.kill()
            try:
                process.wait(timeout=.2)
            except subprocess.TimeoutExpired:
                # Popen's cleanup will reap an uninterruptible filesystem task
                # when the kernel releases it. Do not block the UI worker.
                pass
            if process.stdout:
                process.stdout.close()


class FolderSizeWorker:
    """One active scan and one replaceable request, with guarded delivery."""
    def __init__(self, dispatch, reader=read_folder):
        self.dispatch, self.reader = dispatch, reader
        self.condition = threading.Condition()
        self.generation = 0
        self.closed = False
        self.pending = None
        self.thread = threading.Thread(target=self.run, daemon=True, name='folder-size')
        self.thread.start()

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

    def valid(self, generation):
        with self.condition:
            return not self.closed and generation == self.generation

    def submit(self, path, callback):
        with self.condition:
            self.generation += 1
            self.pending = (self.generation, path, callback)
            self.condition.notify()

    def run(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.closed or self.pending is not None)
                if self.closed:
                    return
                generation, path, callback = self.pending
                self.pending = None
            try:
                result = self.reader(path, lambda: not self.valid(generation))
            except Exception:
                result = FolderSize()
            def deliver(generation=generation, path=path, result=result, callback=callback):
                if self.valid(generation) and result is not None:
                    callback(path, result)
                return False
            if self.valid(generation):
                self.dispatch(deliver)


if __name__ == '__main__':
    print(json.dumps(asdict(scan_folder(sys.argv[1]))))
