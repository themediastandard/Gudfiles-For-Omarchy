import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from omarchy_file_picker.hover_scrub import FrameCache, SCRUB_STEPS, ScrubFrame, ScrubWorker, scrub_step


class HoverScrubTests(unittest.TestCase):
    def test_quantization_and_limits(self):
        self.assertEqual(scrub_step(-1), 0)
        self.assertEqual(scrub_step(2), SCRUB_STEPS - 1)
        self.assertEqual(scrub_step(.5), scrub_step(.501))

    def test_cache_limits(self):
        cache = FrameCache(max_frames=2, max_bytes=7)
        for n in range(3):
            cache._remember(n, ScrubFrame(b'123', n, 3, n))
        self.assertEqual(list(cache.frames), [1, 2])
        self.assertEqual(cache.bytes, 6)
        cache._remember(3, ScrubFrame(b'12345678', 3, 4, 3))
        self.assertEqual(len(cache.frames), 0)
        self.assertEqual(cache.bytes, 0)

    def test_extraction_is_silent_bounded_and_cached(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'movie.mp4'
            path.touch()
            outputs = [subprocess.CompletedProcess([], 0, b'{"format":{"duration":"10"}}'),
                       subprocess.CompletedProcess([], 0, b'jpeg-data')]
            cache = FrameCache()
            with patch('omarchy_file_picker.hover_scrub.subprocess.run', side_effect=outputs) as run:
                first = cache.frame(path, SCRUB_STEPS - 1)
                self.assertIs(cache.frame(path, SCRUB_STEPS - 1), first)
                self.assertEqual(run.call_count, 2)
                command = run.call_args.args[0]
                self.assertIn('-an', command)
                self.assertIn('-nostdin', command)
                self.assertIn('pipe:1', command)
                self.assertEqual(run.call_args.kwargs['timeout'], 6)
                self.assertLess(first.seconds, first.duration)

    def test_changed_file_invalidates_cached_frame(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'movie.mp4'
            path.touch()
            probe = subprocess.CompletedProcess([], 0, b'{"format":{"duration":"10"}}')
            frame = subprocess.CompletedProcess([], 0, b'jpeg-data')
            with patch('omarchy_file_picker.hover_scrub.subprocess.run', side_effect=[probe, frame, probe, frame]) as run:
                cache = FrameCache()
                cache.frame(path, 5)
                path.write_bytes(b'new-media')
                cache.frame(path, 5)
                self.assertEqual(run.call_count, 4)

    def test_failures_keep_poster(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'movie.mp4'
            path.touch()
            for error in [FileNotFoundError(), subprocess.TimeoutExpired('ffprobe', 4)]:
                with patch('omarchy_file_picker.hover_scrub.subprocess.run', side_effect=error):
                    self.assertIsNone(FrameCache().frame(path, 0))
            for duration in ['nan', 'inf', '-1', '0']:
                output = subprocess.CompletedProcess([], 0, ('{"format":{"duration":"' + duration + '"}}').encode())
                with patch('omarchy_file_picker.hover_scrub.subprocess.run', return_value=output) as run:
                    self.assertIsNone(FrameCache().frame(path, 0))
                    self.assertEqual(run.call_count, 1)

    def test_one_worker_without_queued_requests(self):
        worker = ScrubWorker()
        started = threading.Event()
        release = threading.Event()
        completed = threading.Event()
        def frame(*_):
            started.set()
            release.wait(2)
        def idle(*_):
            completed.set()
        with patch.object(worker.cache, 'frame', side_effect=frame), \
                patch('omarchy_file_picker.hover_scrub.GLib.idle_add', side_effect=idle):
            self.assertTrue(worker.request(Path('/unused'), 0, lambda *_: None))
            self.assertTrue(started.wait(1))
            for _ in range(100):
                self.assertFalse(worker.request(Path('/unused'), 1, lambda *_: None))
            release.set()
            self.assertTrue(completed.wait(2))


if __name__ == '__main__':
    unittest.main()
