"""Private annotation persistence, filtering and rename safety regression tests."""
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from omarchy_file_picker.ratings import COLORS, EMPTY, RatingStore, matches


class RatingStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='rating-store-qa-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.database = self.root / 'app-state' / 'ratings.sqlite3'
        self.store = RatingStore(self.database)
        self.first = self.root / 'media' / 'A.mov'
        self.second = self.root / 'media' / 'B.mov'

    def load(self, *paths):
        result = RatingStore(self.database)
        result.refresh(paths)
        return result

    def test_empty_store_is_read_only_and_defaults(self):
        self.store.refresh([self.first])
        self.assertEqual(self.store.get(self.first), EMPTY)
        self.assertFalse(self.database.exists())

    def test_persistence_partial_updates_and_clear(self):
        self.store.set_many([self.first, self.second], stars=4, color='purple', rejected=True)
        fresh = self.load(self.first, self.second)
        self.assertEqual(fresh.get(self.first), (4, 'purple', True))
        fresh.set_many([self.first], stars=0)
        self.assertEqual(fresh.get(self.first), (0, 'purple', True))
        fresh.set_many([self.first], color='', rejected=False)
        self.assertEqual(self.load(self.first).get(self.first), EMPTY)
        self.assertEqual(self.load(self.second).get(self.second), (4, 'purple', True))

    def test_stale_window_does_not_overwrite_unedited_fields(self):
        self.store.set_many([self.first], stars=2)
        second_window = self.load(self.first)
        self.store.set_many([self.first], color='blue', rejected=True)
        second_window.set_many([self.first], stars=5)
        self.assertEqual(self.load(self.first).get(self.first), (5, 'blue', True))

    def test_lock_precedes_read_modify_write(self):
        # A deferred transaction starts at INSERT, allowing two windows' SELECTs
        # to both observe the old row. Reserve the writer before reading it.
        self.store.set_many([self.first], stars=1)
        queries = []
        connect = sqlite3.connect
        def traced(*args, **kwargs):
            db = connect(*args, **kwargs)
            db.set_trace_callback(queries.append)
            return db
        with patch('omarchy_file_picker.ratings.sqlite3.connect', side_effect=traced):
            self.store.set_many([self.first], color='green')
        first_select = next(index for index, query in enumerate(queries) if query.startswith('SELECT'))
        self.assertTrue(any(query.upper().startswith('BEGIN IMMEDIATE') for query in queries[:first_select]), queries)

    def test_invalid_annotations_rejected_before_creating_database(self):
        for key, values in [('stars', [-1, 6, 1.5, '3', True]),
                            ('color', ['yellow', 'RED', 1, ['red']]),
                            ('rejected', [0, 1, 'false'])]:
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    self.store.set_many([self.first], **{key: value})
        self.assertFalse(self.database.exists())

    def test_media_and_folder_contents_are_not_written(self):
        self.first.parent.mkdir()
        self.first.write_bytes(b'unchanged-media\0\1')
        before = self.first.stat()
        self.store.set_many([self.first], stars=5, color='red', rejected=True)
        after = self.first.stat()
        self.assertEqual(self.first.read_bytes(), b'unchanged-media\0\1')
        self.assertEqual((before.st_mtime_ns, before.st_size), (after.st_mtime_ns, after.st_size))
        self.assertEqual(list(self.first.parent.iterdir()), [self.first])

    def test_refresh_large_chunked_selection_and_cache_scope(self):
        paths = [self.root / f'clip-{number}.mov' for number in range(905)]
        self.store.set_many(paths, stars=3)
        fresh = self.load(*paths)
        self.assertTrue(all(fresh.get(path) == (3, '', False) for path in paths))
        fresh.refresh([paths[0]])
        self.assertEqual(fresh.get(paths[-1]), EMPTY)

    def test_multi_update_rolls_back_database_and_cache_on_error(self):
        self.store.set_many([self.first, self.second], stars=2)
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute("CREATE TRIGGER reject_second BEFORE INSERT ON ratings WHEN NEW.path = "
                       + "'" + self.store.key(self.second).replace("'", "''") + "' "
                       "BEGIN SELECT RAISE(ABORT, 'simulated failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.set_many([self.first, self.second], color='blue')
        for store in (self.store, self.load(self.first, self.second)):
            self.assertEqual(store.get(self.first), (2, '', False))
            self.assertEqual(store.get(self.second), (2, '', False))

    def test_rename_swap_preserves_each_annotation_and_removes_old_target(self):
        self.store.set_many([self.first], stars=2, color='red')
        self.store.set_many([self.second], stars=5, rejected=True)
        self.store.move({self.first: self.second, self.second: self.first})
        fresh = self.load(self.first, self.second)
        self.assertEqual(fresh.get(self.first), (5, '', True))
        self.assertEqual(fresh.get(self.second), (2, 'red', False))
        third = self.first.with_name('C.mov')
        self.store.move({self.second: third})
        fresh = self.load(self.second, third)
        self.assertEqual(fresh.get(self.second), EMPTY)
        self.assertEqual(fresh.get(third), (2, 'red', False))

    def test_folder_rename_moves_descendants_without_prefix_false_matches(self):
        # Percent/underscore are literal path characters, not SQL LIKE patterns.
        source = self.root / 'Shoot_%'
        target = self.root / 'Delivery'
        child = source / 'camera' / 'clip.mov'
        unrelated = self.root / 'Shoot_%_other' / 'clip.mov'
        self.store.set_many([source, child], stars=4, color='green')
        self.store.set_many([unrelated], stars=1)
        self.store.move({source: target})
        moved_child = target / 'camera' / 'clip.mov'
        fresh = self.load(source, child, target, moved_child, unrelated)
        self.assertEqual(fresh.get(source), EMPTY)
        self.assertEqual(fresh.get(child), EMPTY)
        self.assertEqual(fresh.get(target), (4, 'green', False))
        self.assertEqual(fresh.get(moved_child), (4, 'green', False))
        self.assertEqual(fresh.get(unrelated), (1, '', False))

    def test_move_failure_rolls_back_cache_and_database(self):
        self.store.set_many([self.first], stars=4, color='orange')
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute("CREATE TRIGGER reject_move BEFORE INSERT ON ratings "
                       "BEGIN SELECT RAISE(ABORT, 'simulated failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.move({self.first: self.second})
        for store in (self.store, self.load(self.first, self.second)):
            self.assertEqual(store.get(self.first), (4, 'orange', False))
            self.assertEqual(store.get(self.second), EMPTY)


class RatingFilterTests(unittest.TestCase):
    def test_all_includes_unrated_and_rejected(self):
        self.assertTrue(matches(EMPTY))
        self.assertTrue(matches((0, '', True)))

    def test_rated_excludes_unrated_and_rejects(self):
        self.assertFalse(matches(EMPTY, 'rated'))
        self.assertTrue(matches((1, '', False), 'rated'))
        self.assertFalse(matches((5, 'blue', True), 'rated'))

    def test_rejected_and_combined_minimum_color(self):
        self.assertTrue(matches((0, '', True), 'rejected'))
        self.assertFalse(matches((5, 'red', False), 'rejected'))
        for color in COLORS:
            self.assertTrue(matches((4, color, False), 'rated', 4, color))
            self.assertFalse(matches((3, color, False), 'rated', 4, color))
            self.assertFalse(matches((5, '', False), 'rated', 4, color))


if __name__ == '__main__':
    unittest.main()
