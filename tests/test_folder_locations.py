import concurrent.futures
from pathlib import Path
import sqlite3
import tempfile
import unittest

from omarchy_file_picker.folder_locations import FolderLocations


class FolderLocationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = FolderLocations(self.root / 'folders.sqlite3')

    def test_mru_limit_deduplication_and_reopen(self):
        folders = [self.root / str(i) for i in range(8)]
        self.assertEqual(self.store.read(), ([], []))
        for folder in folders:
            self.store.touch([folder])
        self.store.touch([folders[4], folders[4]])
        self.assertEqual(FolderLocations(self.store.database).read()[1],
                         [folders[4], folders[7], folders[6], folders[5], folders[3]])

    def test_favorites_removal_preserves_folder_contents_and_recents(self):
        folder = self.root / 'Folder'; folder.mkdir()
        original = folder / 'keep.txt'; original.write_text('original')
        self.store.set_favorite(folder, True)
        self.store.set_favorite(folder / '..' / folder.name, True)
        self.store.touch([folder])
        self.assertEqual(self.store.read(), ([folder], [folder]))
        self.store.set_favorite(folder, False)
        self.store.set_favorite(folder, False)
        self.assertEqual(self.store.read(), ([], [folder]))
        self.assertEqual(original.read_text(), 'original')
        self.assertEqual(self.store.database.stat().st_mode & 0o777, 0o600)

    def test_recent_removal_persists_without_removing_favorite_or_folder(self):
        folder = self.root / 'Folder'; folder.mkdir()
        original = folder / 'keep.txt'; original.write_text('original')
        other = self.root / 'Other'
        self.store.set_favorite(folder, True)
        self.store.touch([folder, other])
        self.store.remove_recent(folder)
        self.store.remove_recent(folder)
        reopened = FolderLocations(self.store.database)
        self.assertEqual(reopened.read(), ([folder], [other]))
        self.assertEqual(original.read_text(), 'original')
        # Removal forgets the past visit, rather than permanently blacklisting it.
        reopened.touch([folder])
        self.assertEqual(reopened.read()[1], [folder, other])

    def test_multiple_connections_preserve_each_others_changes(self):
        self.store.touch([self.root])
        folders = [self.root / str(i) for i in range(12)]
        def add(folder):
            store = FolderLocations(self.store.database)
            store.set_favorite(folder, True)
            store.touch([folder])
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(add, folders))
        favorites, recents = self.store.read()
        self.assertEqual(set(favorites), set(folders))
        self.assertEqual(len(recents), 5)
        self.assertEqual(len(set(recents)), 5)

    def test_corruption_and_locked_writes_preserve_saved_state(self):
        self.store.set_favorite(self.root, True)
        self.store.touch([self.root])
        with sqlite3.connect(self.store.database) as lock:
            lock.execute('BEGIN IMMEDIATE')
            with self.assertRaises(sqlite3.OperationalError):
                self.store.set_favorite(self.root, False)
            with self.assertRaises(sqlite3.OperationalError):
                self.store.remove_recent(self.root)
        self.assertEqual(self.store.read(), ([self.root], [self.root]))
        self.store.database.write_bytes(b'corrupt fixture')
        with self.assertRaises(sqlite3.DatabaseError):
            self.store.set_favorite(self.root, False)
        self.assertEqual(self.store.database.read_bytes(), b'corrupt fixture')
