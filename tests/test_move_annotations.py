import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import GLib
from omarchy_file_picker.file_actions import transfer_items
from omarchy_file_picker.file_management import FileManagement
from omarchy_file_picker.ratings import RatingStore, EMPTY


class MoveAnnotationsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.destination = self.root / 'destination'
        self.source.mkdir()
        self.destination.mkdir()
        self.paths = [self.source / 'A.mov', self.source / 'B.mov']
        for path in self.paths:
            path.write_bytes(b'original')
        self.store = RatingStore(self.root / 'ratings.sqlite3')
        self.store.set_many(self.paths, stars=4, color='blue')
        self.owner = FileManagement()
        self.owner.action_sounds = Mock()
        self.calls = []
        def migrate(mapping):
            self.calls.append((mapping.copy(), threading.get_ident()))
            self.store.move(mapping)
        self.owner._creative_paths_renamed = migrate

    def perform(self, cut=True):
        errors = []
        def worker():
            try:
                self.owner._transfer_files(self.paths, self.destination, cut)
            except Exception as error:
                errors.append(error)
        thread = threading.Thread(target=worker)
        thread.start()
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(self.calls, [])  # Metadata never mutated on the worker.
        context = GLib.MainContext.default()
        while context.pending():
            context.iteration(False)
        self.store.refresh(self.paths + [self.destination / path.name for path in self.paths])
        return errors

    def test_cut_moves_annotations_on_main_thread(self):
        self.assertFalse(self.perform())
        self.assertEqual(self.calls, [(dict((p, self.destination / p.name) for p in self.paths), threading.get_ident())])
        for path in self.paths:
            self.assertEqual(self.store.get(path), EMPTY)
            self.assertEqual(self.store.get(self.destination / path.name), (4, 'blue', False))

    def test_copy_keeps_original_annotations(self):
        self.assertFalse(self.perform(cut=False))
        self.assertEqual(self.calls, [])
        for path in self.paths:
            self.assertEqual(self.store.get(path), (4, 'blue', False))
            self.assertEqual(self.store.get(self.destination / path.name), EMPTY)

    def test_later_failure_migrates_only_confirmed_completed_move(self):
        def transfer_then_fail(sources, directory, cut, *, moved):
            def first_moved(source, target):
                moved(source, target)
                # Create a racing destination after global preflight; Gio refuses it.
                (directory / self.paths[1].name).write_text('racing file')
            return transfer_items(sources, directory, cut, moved=first_moved)
        with patch('omarchy_file_picker.file_management.transfer_items', side_effect=transfer_then_fail):
            self.assertTrue(self.perform())
        first, second = self.paths
        self.assertEqual(self.calls[0][0], {first: self.destination / first.name})
        self.assertEqual(self.store.get(first), EMPTY)
        self.assertEqual(self.store.get(self.destination / first.name), (4, 'blue', False))
        self.assertEqual(self.store.get(second), (4, 'blue', False))
        self.assertEqual(self.store.get(self.destination / second.name), EMPTY)
        self.assertEqual((self.destination / second.name).read_text(), 'racing file')

    def test_global_preflight_failure_does_not_move_any_annotation(self):
        (self.destination / self.paths[1].name).write_text('existing')
        self.assertTrue(self.perform())
        self.assertEqual(self.calls, [])
        self.assertTrue(all(path.exists() for path in self.paths))
        self.assertTrue(all(self.store.get(path) == (4, 'blue', False) for path in self.paths))

    def test_queue_migrates_in_actual_commit_order_when_jobs_start_out_of_order(self):
        self.owner._init_transfers()
        self.owner.current_dir = self.root
        self.owner._refresh_files = lambda: None
        queue = self.owner.transfer_queue
        middle = self.root / 'middle'
        middle.mkdir()
        source = self.paths[0]
        onward = queue.add([middle / source.name], self.destination, cut=True)
        initial = queue.add([source], middle, cut=True)
        for job in (initial, onward):
            queue.start(job)
            deadline = time.monotonic() + 4
            while queue.active is not None and time.monotonic() < deadline:
                time.sleep(.005)
            self.assertEqual(job.state, 'completed', job.error)
        # Both events arrive before the GTK loop gets to process them.
        self.assertFalse(self.owner._guard_transfer_close(lambda: None))
        self.assertEqual([call[0] for call in self.calls], [
            {source: middle / source.name},
            {middle / source.name: self.destination / source.name},
        ])
        self.store.refresh([source, middle / source.name, self.destination / source.name])
        self.assertEqual(self.store.get(self.destination / source.name), (4, 'blue', False))
        self.assertEqual(self.store.get(middle / source.name), EMPTY)


if __name__ == '__main__':
    unittest.main()
