import errno
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from omarchy_file_picker import move_cleanup
from omarchy_file_picker.transfers import Interrupted, RestartRequired, TransferEngine, TransferJob


@unittest.skipUnless(Path('/dev/shm').is_dir(), 'Requires a disposable second filesystem')
class RetainOriginalTests(unittest.TestCase):
    def setUp(self):
        self.source_temp = tempfile.TemporaryDirectory(prefix='gudfiles-retain-source-')
        self.target_temp = tempfile.TemporaryDirectory(prefix='gudfiles-retain-target-', dir='/dev/shm')
        self.addCleanup(self.source_temp.cleanup)
        self.addCleanup(self.target_temp.cleanup)
        self.source, self.target = Path(self.source_temp.name), Path(self.target_temp.name)
        if self.source.stat().st_dev == self.target.stat().st_dev:
            self.skipTest('Fixture filesystems must differ')
        self.engine = TransferEngine()
        self.file = self.source / 'clip.mov'
        self.file.write_bytes(b'footage')

    def held_job(self, path=None, partial=False):
        job = TransferJob([path or self.file], self.target, cut=True)
        def pause(current):
            if not current.items:
                return
            item = current.items[0]
            if (item.removed if partial else item.quarantine_id):
                current.stop.set()
        job.on_checkpoint = pause
        with self.assertRaises(Interrupted):
            self.engine.run(job)
        job.on_checkpoint = None
        job.stop.clear()
        return job

    def retain(self, job):
        return move_cleanup.retain_original(self.engine, job, job.items[0], 0)

    def test_changed_source_before_quarantine_can_keep_both(self):
        publish = self.engine._record_published
        def changed(job, item, identity):
            publish(job, item, identity)
            self.file.write_bytes(b'new edit')
        job = TransferJob([self.file], self.target, cut=True)
        with patch.object(self.engine, '_record_published', side_effect=changed):
            with self.assertRaises(RestartRequired):
                self.engine.run(job)
        self.assertEqual(self.retain(job), self.file)
        self.assertTrue(job.items[0].abandoned)
        self.assertFalse(job.completed)
        self.assertEqual(self.file.read_bytes(), b'new edit')
        self.assertEqual((self.target / self.file.name).read_bytes(), b'footage')

    def test_partial_folder_cleanup_restores_only_remaining_originals(self):
        folder = self.source / 'folder'
        folder.mkdir()
        (folder / 'a').write_bytes(b'a')
        (folder / 'b').write_bytes(b'b')
        job = self.held_job(folder, partial=True)
        self.assertEqual(len(job.items[0].removed), 1)
        self.assertEqual(self.retain(job), folder)
        self.assertEqual([p.name for p in folder.iterdir()], ['a'])
        self.assertEqual((self.target / 'folder/a').read_bytes(), b'a')
        self.assertEqual((self.target / 'folder/b').read_bytes(), b'b')
        self.assertFalse(any(self.source.glob('.omarchy-move-*')))

    def test_original_name_collision_and_racing_collision_keep_all_data(self):
        job = self.held_job()
        self.file.write_bytes(b'new recording')
        rename = move_cleanup.rename_noreplace
        raced = False
        def race(source_fd, source, target_fd, target):
            nonlocal raced
            if not raced:
                raced = True
                (self.source / target).write_bytes(b'racing recording')
            return rename(source_fd, source, target_fd, target)
        with patch.object(move_cleanup, 'rename_noreplace', side_effect=race):
            retained = self.retain(job)
        self.assertEqual(retained, self.source / 'clip (remaining 2).mov')
        self.assertEqual(retained.read_bytes(), b'footage')
        self.assertEqual(self.file.read_bytes(), b'new recording')
        self.assertEqual((self.source / 'clip (remaining 1).mov').read_bytes(), b'racing recording')

    def test_restore_lost_acknowledgement_is_reconciled(self):
        job = self.held_job()
        rename = move_cleanup.rename_noreplace
        def lost(*args):
            rename(*args)
            raise OSError(errno.EIO, 'lost acknowledgement')
        with patch.object(move_cleanup, 'rename_noreplace', side_effect=lost):
            self.assertEqual(self.retain(job), self.file)
        self.assertEqual(self.retain(job), self.file)
        self.assertEqual(self.file.read_bytes(), b'footage')
        self.assertEqual(list(self.source.iterdir()), [self.file])

    def test_crash_after_restore_before_receipt_reconciles(self):
        job = self.held_job()
        sync = self.engine._sync_directory
        def crash(fd):
            raise RuntimeError('simulated process death')
        with patch.object(self.engine, '_sync_directory', side_effect=crash):
            with self.assertRaisesRegex(RuntimeError, 'process death'):
                self.retain(job)
        self.assertTrue(job.items[0].restoring)
        self.assertEqual(self.file.read_bytes(), b'footage')
        self.assertEqual(self.retain(job), self.file)
        self.assertTrue(job.items[0].abandoned)

    def test_replaced_held_source_is_not_renamed_or_deleted(self):
        job = self.held_job()
        held = self.source / job.items[0].quarantine_name
        held.rename(self.source / 'actual-original')
        held.write_bytes(b'unrelated')
        with self.assertRaisesRegex(RestartRequired, 'replaced'):
            self.retain(job)
        self.assertEqual(held.read_bytes(), b'unrelated')
        self.assertEqual((self.source / 'actual-original').read_bytes(), b'footage')
        self.assertFalse(job.items[0].abandoned)

    def test_completed_unlink_does_not_touch_unrelated_held_replacement(self):
        job = self.held_job()
        item = job.items[0]
        held = self.source / item.quarantine_name
        held.unlink()
        item.removed.append(item.entries[0].relative)
        held.write_bytes(b'unrelated')
        self.assertIsNone(self.retain(job))
        self.assertTrue(item.abandoned)
        self.assertEqual(held.read_bytes(), b'unrelated')

    def test_long_collision_name_stays_within_filesystem_limit(self):
        long = self.source / ('x' * 245 + '.mov')
        self.file.rename(long)
        job = self.held_job(long)
        long.write_bytes(b'new recording')
        retained = self.retain(job)
        self.assertLessEqual(len(os.fsencode(retained.name)), os.pathconf(self.source, 'PC_NAME_MAX'))
        self.assertTrue(retained.name.endswith(' (remaining 1).mov'))
        self.assertEqual(retained.read_bytes(), b'footage')
        self.assertEqual(long.read_bytes(), b'new recording')


if __name__ == '__main__':
    unittest.main()
