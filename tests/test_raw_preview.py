"""Exercise decoder cancellation, process cleanup and RAW type recognition."""
import concurrent.futures
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from omarchy_file_picker import raw_preview


def wait_for(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(.01)
    if not predicate():
        raise AssertionError('Decoder test condition timed out')


def running(pid):
    try:
        return Path(f'/proc/{pid}/stat').read_text().split(') ', 1)[1][0] != 'Z'
    except FileNotFoundError:
        return False


class RawPreviewTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='raw-decoder-test-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root / 'camera photo ü.CR3'
        self.source.write_bytes(b'original camera file')
        self.helper = self.root / 'raw-preview'
        self.helper.write_text(
            '#!/usr/bin/python\n'
            'import json, os, pathlib, subprocess, sys, time\n'
            'child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])\n'
            f'markers = pathlib.Path({str(self.root)!r})\n'
            'marker = markers / (str(os.getpid()) + ".json")\n'
            'pending = marker.with_suffix(".tmp")\n'
            'pending.write_text(json.dumps({\n'
            '    "pid": os.getpid(), "child": child.pid, "args": sys.argv[1:],\n'
            '    "directory": str(pathlib.Path(sys.argv[3]).parent)}))\n'
            'pending.replace(marker)\n'
            'time.sleep(60)\n')
        self.helper.chmod(0o755)
        self.finder = patch.object(raw_preview.shutil, 'which', return_value=str(self.helper))
        self.finder.start()
        self.addCleanup(self.finder.stop)

    def markers(self):
        return [json.loads(path.read_text()) for path in self.root.glob('*.json')]

    def assert_cleaned(self):
        for marker in self.markers():
            wait_for(lambda: not running(marker['pid']) and not running(marker['child']))
            self.assertFalse(Path(marker['directory']).exists())
        self.assertEqual(self.source.read_bytes(), b'original camera file')

    def test_camera_mime_types_and_regular_files(self):
        for name in ('file.CR3', 'file.ArW', 'file.RAF', 'file.NEF', 'file.DNG', 'file.X3F'):
            self.assertTrue(raw_preview.is_raw_image(self.root / name), name)
        for name in ('file.jpg', 'file.png', 'file.tiff', 'file.mp4', 'file.txt'):
            self.assertFalse(raw_preview.is_raw_image(self.root / name), name)

    def test_cancel_stops_decoder_children_and_removes_temporary_output(self):
        cancelled = threading.Event()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            task = pool.submit(raw_preview.read_raw_preview, self.source,
                               cancelled=cancelled.is_set)
            try:
                wait_for(lambda: bool(self.markers()))
                args = self.markers()[0]['args']
                self.assertEqual(args[:2], ['--thumbnail', str(self.source)])
                self.assertNotEqual(Path(args[2]).parent, self.source.parent)
            finally:
                cancelled.set()
            with self.assertRaises(raw_preview.RawPreviewCancelled):
                task.result(timeout=3)
        self.assert_cleaned()

    def test_timeout_stops_decoder_children(self):
        with patch.object(raw_preview, 'DECODE_TIMEOUT', .2):
            with self.assertRaisesRegex(RuntimeError, 'too long'):
                raw_preview.read_raw_preview(self.source)
        self.assert_cleaned()

    def test_rapid_navigation_has_two_decoders_and_cancels_waiting_work(self):
        cancelled = threading.Event()
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            tasks = [pool.submit(raw_preview.read_raw_preview, self.source,
                                 cancelled=cancelled.is_set) for _ in range(6)]
            try:
                wait_for(lambda: len(self.markers()) == 2)
                time.sleep(.15)
                self.assertEqual(len(self.markers()), 2)
            finally:
                cancelled.set()
            for task in tasks:
                with self.assertRaises(raw_preview.RawPreviewCancelled):
                    task.result(timeout=3)
        self.assertEqual(len(self.markers()), 2)
        self.assert_cleaned()

    def test_missing_and_failed_reader_have_actionable_errors(self):
        with patch.object(raw_preview.shutil, 'which', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'not installed'):
                raw_preview.read_raw_preview(self.source)
        self.helper.write_text('#!/usr/bin/python\nraise SystemExit(1)\n')
        with self.assertRaisesRegex(RuntimeError, 'could not be previewed'):
            raw_preview.read_raw_preview(self.source)


if __name__ == '__main__':
    unittest.main()
