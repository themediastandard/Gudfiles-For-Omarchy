from pathlib import Path
import os
import queue
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from omarchy_file_picker.folder_sizes import FolderSize, FolderSizeWorker, read_folder, scan_folder
from omarchy_file_picker.file_actions import sort_entries


class FolderSizeTests(unittest.TestCase):
    def test_nested_hidden_sparse_links_and_empty(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'empty').mkdir()
            self.assertEqual(scan_folder(root), FolderSize(0, True, ''))
            (root / '.hidden').write_bytes(b'x' * 1024)
            (root / 'empty' / 'child').write_bytes(b'x' * 2048)
            with (root / 'sparse').open('wb') as file:
                file.truncate(10_000_000)
            (root / 'cycle').symlink_to(root, target_is_directory=True)
            (root / 'link').symlink_to(root / '.hidden')
            (root / 'broken').symlink_to(root / 'missing')
            os.mkfifo(root / 'pipe')
            expected = FolderSize(10_003_072, True, '')
            self.assertEqual(scan_folder(root), expected)
            self.assertEqual(read_folder(root, lambda: False), expected)
            self.assertFalse(scan_folder(root / 'cycle').complete)
            self.assertFalse(scan_folder(root / 'missing').complete)

    def test_limits_and_unreadable_subfolder_are_partial(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'known').write_bytes(b'a' * 4096)
            denied = root / 'denied'; denied.mkdir()
            original = os.open
            def open_path(path, *args, **kwargs):
                if Path(path) == denied:
                    raise PermissionError()
                return original(path, *args, **kwargs)
            with patch('omarchy_file_picker.folder_sizes.os.open', side_effect=open_path):
                result = scan_folder(root)
            self.assertEqual(result.total, 4096)
            self.assertFalse(result.complete)
            self.assertFalse(scan_folder(root, max_entries=0).complete)
            self.assertFalse(scan_folder(root, seconds=0).complete)

    def test_process_timeout_cancellation_and_invalid_reply_recover(self):
        slow = [sys.executable, '-c', 'import time; time.sleep(10)']
        start = time.monotonic()
        result = read_folder(Path('/unused'), lambda: False, command=slow, timeout=.08)
        self.assertIn('timed out', result.reason)
        self.assertLess(time.monotonic() - start, 2)
        stop = threading.Event()
        timer = threading.Timer(.08, stop.set); timer.start()
        try:
            self.assertIsNone(read_folder(Path('/unused'), stop.is_set, command=slow))
        finally:
            timer.join()
        self.assertFalse(read_folder(Path('/unused'), lambda: False,
            command=[sys.executable, '-c', "print('invalid')"]).complete)
        with tempfile.TemporaryDirectory() as temp:
            self.assertTrue(read_folder(Path(temp), lambda: False).complete)

    def test_worker_preemption_late_reply_and_close(self):
        dispatched, results = queue.Queue(), []
        started = threading.Event()
        calls = []
        def reader(path, cancelled):
            calls.append(path)
            if path == 'slow':
                started.set()
                while not cancelled():
                    time.sleep(.005)
                return None
            return FolderSize(42, True, '')
        worker = FolderSizeWorker(dispatched.put, reader)
        try:
            worker.submit('slow', lambda *args: results.append(args))
            self.assertTrue(started.wait(2))
            worker.submit('new', lambda *args: results.append(args))
            callback = dispatched.get(timeout=2)
            worker.cancel(); callback()
            self.assertEqual(results, [])
            worker.submit('latest', lambda *args: results.append(args))
            dispatched.get(timeout=2)()
            self.assertEqual(results, [('latest', FolderSize(42, True, ''))])
            worker.submit('closing', lambda *args: results.append(args))
            callback = dispatched.get(timeout=2)
            worker.close(); callback()
            worker.thread.join(2)
            self.assertFalse(worker.thread.is_alive())
            self.assertEqual(len(results), 1)
        finally:
            worker.close()

    def test_folder_sort_uses_content_sizes_and_unknowns_stay_last(self):
        small, large, missing = map(Path, ['small', 'large', 'missing'])
        data = {small: dict(size=0, directory=True), large: dict(size=12345, directory=True),
                missing: dict(size=None, directory=True)}
        self.assertEqual(sort_entries([missing, small, large], 'size', True, True, metadata=data),
                         [large, small, missing])
        self.assertEqual(sort_entries([missing, small, large], 'size', False, True, metadata=data),
                         [small, large, missing])
