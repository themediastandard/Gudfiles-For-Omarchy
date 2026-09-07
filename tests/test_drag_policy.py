import os
from pathlib import Path
import tempfile
import unittest

from omarchy_file_picker.drag_policy import plan_drop
from omarchy_file_picker.transfers import TransferEngine, TransferJob


class DragPolicyTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='file-drag-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root / 'original.txt'
        self.source.write_bytes(b'keep every byte\0' * 2048)
        self.destination = self.root / 'destination'
        self.destination.mkdir()

    def transfer(self, sources, destination, **options):
        jobs = []
        for group, cut in plan_drop(sources, destination, **options):
            job = TransferJob(group, destination, cut=cut, duplicate=not cut)
            TransferEngine().run(job)
            jobs.append(job)
        return jobs

    def test_same_disk_moves_without_recopying(self):
        inode = self.source.stat().st_ino
        job, = self.transfer([self.source], self.destination)
        self.assertTrue(job.cut)
        self.assertFalse(self.source.exists())
        self.assertEqual(job.completed[self.source].stat().st_ino, inode)

    def test_alt_copies_even_on_same_disk(self):
        data = self.source.read_bytes()
        job, = self.transfer([self.source], self.destination, force_copy=True)
        self.assertFalse(job.cut)
        self.assertEqual(self.source.read_bytes(), data)
        self.assertEqual(job.completed[self.source].read_bytes(), data)

    def test_current_folder_is_noop_and_alt_duplicates(self):
        self.assertEqual(plan_drop([self.source], self.root), [])
        alias = self.root / 'alias'
        alias.symlink_to(self.root, target_is_directory=True)
        self.assertEqual(plan_drop([alias / self.source.name], self.root), [])
        job, = self.transfer([self.source], self.root, force_copy=True)
        self.assertEqual(job.completed[self.source].name, 'original copy.txt')
        self.assertTrue(self.source.exists())

    def test_recursive_missing_and_nested_sources_are_rejected(self):
        for sources, destination in (([self.root], self.destination),
                                     ([self.root, self.source], self.destination),
                                     ([self.root / 'missing'], self.destination)):
            with self.assertRaises((OSError, ValueError)):
                plan_drop(sources, destination)
        self.assertTrue(self.source.exists())
        self.assertEqual(list(self.destination.iterdir()), [])

    def test_move_collision_preserves_both_originals(self):
        target = self.destination / self.source.name
        target.write_text('already here')
        with self.assertRaises(FileExistsError):
            self.transfer([self.source], self.destination)
        self.assertTrue(self.source.exists())
        self.assertEqual(target.read_text(), 'already here')

    def test_cross_disk_mixed_sources_and_symlinks(self):
        if not os.access('/dev/shm', os.W_OK):
            self.skipTest('No second writable filesystem')
        with tempfile.TemporaryDirectory(prefix='file-drag-', dir='/dev/shm') as remote:
            remote = Path(remote)
            if remote.stat().st_dev == self.root.stat().st_dev:
                self.skipTest('Fixture filesystems are the same')
            data = self.source.read_bytes()
            job, = self.transfer([self.source], remote)
            self.assertFalse(job.cut)
            self.assertEqual(self.source.read_bytes(), data)
            self.assertEqual(job.completed[self.source].read_bytes(), data)
            foreign = remote / 'foreign.txt'
            foreign.write_bytes(b'foreign')
            link = self.root / 'foreign-link'
            link.symlink_to(foreign)
            jobs = self.transfer([self.source, foreign, link], self.destination)
            self.assertEqual([j.cut for j in jobs], [True, False])
            self.assertFalse(self.source.exists())
            self.assertFalse(link.is_symlink())
            self.assertTrue((self.destination / link.name).is_symlink())
            self.assertEqual(os.readlink(self.destination / link.name), str(foreign))
            self.assertEqual(foreign.read_bytes(), b'foreign')
            self.assertEqual((self.destination / foreign.name).read_bytes(), b'foreign')


if __name__ == '__main__':
    unittest.main()
