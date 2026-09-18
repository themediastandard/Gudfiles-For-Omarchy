import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from omarchy_file_picker.search import SearchResult, SearchService, run_search, scan


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='gudfiles-search-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.first = self.root / 'first'
        self.second = self.root / 'second'
        self.first.mkdir()
        self.second.mkdir()
        self.options = dict(roots=[str(self.root)], query='NEEDLE')
        self.files = [self.first / 'needle.txt', self.second / 'needle.txt',
                      self.second / 'a needle\nwith newline.txt']
        for path in self.files:
            path.touch()

    def test_recursive_names_and_duplicate_basenames(self):
        result = run_search(self.options, threading.Event())
        self.assertEqual(set(result.paths), set(self.files))
        self.assertFalse(result.error or result.limited or result.timed_out or result.skipped)

    def test_hidden_paths_follow_toggle(self):
        hidden = self.root / '.hidden'
        hidden.mkdir()
        nested = hidden / 'needle.txt'
        nested.touch()
        dotfile = self.root / '.needle.txt'
        dotfile.touch()
        self.assertEqual(set(run_search(self.options, threading.Event()).paths), set(self.files))
        self.assertEqual(set(run_search(dict(self.options, hidden=True), threading.Event()).paths),
                         {*self.files, nested, dotfile})

    def test_symlink_loops_and_overlapping_roots(self):
        (self.second / 'loop').symlink_to(self.root, target_is_directory=True)
        options = dict(self.options, roots=[str(self.first), str(self.root)])
        result = run_search(options, threading.Event())
        self.assertEqual(set(result.paths), set(self.files))
        self.assertEqual(len(result.paths), len(self.files))
        self.assertFalse(result.timed_out)

    def test_filters_and_folder_only(self):
        folder = self.root / 'needle folder'
        folder.mkdir()
        result = run_search(dict(self.options, directories_only=True), threading.Event())
        self.assertEqual(result.paths, [folder])
        result = run_search(dict(self.options, filter=['Images', [[1, 'image/*']]]), threading.Event())
        self.assertEqual(result.paths, [folder])

    def test_limit_and_deadline_report_partial(self):
        result = run_search(dict(self.options, limit=2), threading.Event())
        self.assertEqual(len(result.paths), 2)
        self.assertTrue(result.limited)
        records = []
        scan(dict(self.options, seconds=0), records.append)
        self.assertTrue(records[-1]['timed_out'])

    def test_unreadable_directory_is_reported(self):
        original = os.scandir
        def read(path):
            if path == self.second:
                raise PermissionError('Fixture permission denial')
            return original(path)
        records = []
        with patch('omarchy_file_picker.search.os.scandir', side_effect=read):
            scan(self.options, records.append)
        self.assertEqual([r['path'] for r in records if 'path' in r], [str(self.files[0])])
        self.assertEqual(records[-1]['skipped'], 1)

    def test_hung_worker_retains_streamed_results_and_exits(self):
        command = [sys.executable, '-c',
                   'import json,time; print(json.dumps({"path":"/fixture"}),flush=True); time.sleep(60)']
        start = time.monotonic()
        result = run_search(dict(self.options, seconds=.05), threading.Event(), command=command)
        self.assertLess(time.monotonic() - start, 3)
        self.assertEqual(result.paths, [Path('/fixture')])
        self.assertTrue(result.timed_out)

    def test_cancel_kills_worker(self):
        cancelled = threading.Event()
        timer = threading.Timer(.1, cancelled.set)
        timer.start()
        start = time.monotonic()
        run_search(self.options, cancelled, command=[sys.executable, '-c', 'import time; time.sleep(60)'])
        timer.join()
        self.assertLess(time.monotonic() - start, 2)

    def test_failed_worker_and_launch_error_are_not_empty_success(self):
        result = run_search(self.options, threading.Event(), command=['/missing/gudfiles-test-command'])
        self.assertTrue(result.error)
        result = run_search(self.options, threading.Event(), command=[sys.executable, '-c', 'raise SystemExit(1)'])
        self.assertTrue(result.error)

    def test_latest_pending_request_replaces_older_work(self):
        started, release, completed = threading.Event(), threading.Event(), threading.Event()
        calls, delivered = [], []
        def run(options, cancel):
            calls.append(options)
            if options == 'first':
                started.set()
                release.wait(3)
            return SearchResult()
        def callback(result):
            delivered.append(result)
            completed.set()
        with patch('omarchy_file_picker.search.run_search', side_effect=run):
            service = SearchService()
            try:
                service.submit('first', callback)
                self.assertTrue(started.wait(2))
                service.submit('discarded', callback)
                service.submit('latest', callback)
                release.set()
                self.assertTrue(completed.wait(2))
                self.assertEqual(calls, ['first', 'latest'])
                self.assertEqual(len(delivered), 1)
            finally:
                service.close()
                service.worker.join(2)
                self.assertFalse(service.worker.is_alive())


if __name__ == '__main__':
    unittest.main()
