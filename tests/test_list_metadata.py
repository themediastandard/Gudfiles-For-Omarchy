from pathlib import Path
import queue
import tempfile
import threading
import unittest
from unittest.mock import patch

from omarchy_file_picker.file_actions import sort_entries
from omarchy_file_picker.list_metadata import (ListMetadataWorker, annotation_values,
    media_values, read_values, format_value, normalize_columns)
from omarchy_file_picker.media_details import details_from_probe


class ListMetadataTests(unittest.TestCase):
    def test_column_order_roundtrip_and_invalid_saved_entries(self):
        columns = ['color', 'rating', 'name', 'size']
        self.assertEqual(normalize_columns(columns), ['name', 'color', 'rating', 'size'])
        self.assertEqual(normalize_columns(['rating', {}, 'rating', 'obsolete', 'color']),
                         ['name', 'rating', 'color'])
        self.assertEqual(normalize_columns([]), ['name'])

    def test_annotations_sort_saved_values_and_keep_unrated_last(self):
        a, b, empty = map(Path, ['a.txt', 'b.txt', 'empty.txt'])
        data = {a: annotation_values((2, 'red', False)),
                b: annotation_values((5, 'blue', True)),
                empty: annotation_values((0, '', False))}
        self.assertEqual(format_value('rating', data[b]), '★★★★★')
        self.assertEqual(format_value('rating', data[empty]), '—')
        self.assertEqual(format_value('color', data[b]), '● Blue')
        self.assertEqual(format_value('rejected', data[b]), 'Yes')
        for key, descending, expected in [('rating', True, [b, a, empty]),
                                          ('rating', False, [a, b, empty]),
                                          ('color', False, [b, a, empty]),
                                          ('rejected', True, [b, a, empty])]:
            self.assertEqual(sort_entries([empty, a, b], key, descending, False, metadata=data), expected)

    def test_busy_worker_replaces_pending_batch_and_closes(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = [Path(temp) / str(i) for i in range(40)]
            for path in paths:
                path.touch()
            started, release, queued, calls = threading.Event(), threading.Event(), queue.Queue(), []
            def read(path, media):
                calls.append(path)
                if path == paths[0]:
                    started.set()
                    release.wait(2)
                return {'_media': media}
            worker = ListMetadataWorker(queued.put, reader=read)
            results = []
            try:
                worker.submit(paths, True, lambda *args: results.append(args))
                self.assertTrue(started.wait(2))
                worker.submit(paths[16:32], True, lambda *args: results.append(args))
                worker.submit([paths[-1]], False, lambda *args: results.append(args))
                release.set()
                queued.get(timeout=2)()
                self.assertEqual(calls, [paths[0], paths[-1]])
                self.assertEqual([r[0] for r in results], [paths[-1]])
            finally:
                release.set()
                worker.close()

    def test_numeric_media_and_missing_sorts(self):
        a, b, absent, directory = map(Path, ['a.mp4', 'b.mp4', 'c.txt', 'folder'])
        data = {a: {'fps': 120., 'resolution': (1920*1080, 1920, 1080)},
                b: {'fps': 24., 'resolution': (3840*2160, 3840, 2160)},
                absent: {}, directory: {'directory': True}}
        for key, forward in [('fps', [b, a]), ('resolution', [a, b])]:
            for descending in (False, True):
                expected = list(reversed(forward)) if descending else forward
                self.assertEqual(sort_entries([a, b, absent, directory], key, descending, True,
                                             metadata=data), [directory, *expected, absent])
        values = media_values(details_from_probe({'streams': [{'codec_type': 'video',
            'width': 1920, 'height': 1080, 'avg_frame_rate': '24000/1001', 'codec_name': 'h264'}],
            'format': {'duration': '65'}}))
        self.assertEqual(values['fps'], 23.976)
        self.assertEqual(format_value('duration', values), '1:05')
        self.assertEqual(format_value('resolution', values), '1920 × 1080')
        self.assertEqual(format_value('created', {}), '—')

    def test_created_does_not_substitute_ctime(self):
        from gi.repository import Gio
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'file.txt'
            path.touch()
            with patch.object(Gio.File, 'new_for_path') as file:
                file.return_value.query_info.return_value.has_attribute.return_value = False
                result = read_values(path)
            self.assertIsNone(result['created'])
            self.assertEqual(result['size'], 0)

    def test_cache_versions_failures_and_main_thread_delivery(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'file.txt'
            path.touch()
            calls, results, queued = [], [], queue.Queue()
            def read(path, media):
                calls.append((threading.get_ident(), media))
                return {'size': path.stat().st_size, '_media': media}
            worker = ListMetadataWorker(queued.put, reader=read)
            def collect(path, values, last):
                results.append((values, last, threading.get_ident()))
            try:
                for media in (False, False, True, True):
                    worker.submit([path], media, collect)
                    queued.get(timeout=2)()
                self.assertEqual(len(calls), 2)
                path.write_text('new version')
                worker.submit([path], True, collect)
                queued.get(timeout=2)()
                self.assertEqual(results[-1][0]['size'], 11)
                self.assertEqual(len(calls), 3)
                self.assertTrue(all(t != threading.get_ident() for t, _ in calls))
                self.assertTrue(all(t == threading.get_ident() and last for _, last, t in results))
                path.unlink()
                worker.submit([path], True, collect)
                queued.get(timeout=2)()
                self.assertEqual(results[-1][0], {'_media': True})
            finally:
                worker.close()

    def test_late_reply_cancel_and_changed_source(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'file.txt'
            path.touch()
            queued, results = queue.Queue(), []
            def read(path, media):
                path.write_text(path.read_text() + 'changed')
                return {'fps': 24, '_media': True}
            worker = ListMetadataWorker(queued.put, reader=read)
            try:
                worker.submit([path], True, lambda *args: results.append(args))
                callback = queued.get(timeout=2)
                worker.cancel()
                callback()
                self.assertEqual(results, [])
                worker.submit([path], True, lambda *args: results.append(args))
                queued.get(timeout=2)()
                self.assertNotIn('fps', results[-1][1])
                self.assertEqual(len(worker.cache), 0)
                worker.submit([path], True, lambda *args: results.append(args))
                callback = queued.get(timeout=2)
                worker.close()
                callback()
                self.assertEqual(len(results), 1)
            finally:
                worker.close()
