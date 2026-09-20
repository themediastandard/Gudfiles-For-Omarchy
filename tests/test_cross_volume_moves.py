import errno
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from omarchy_file_picker import move_cleanup
from omarchy_file_picker.transfers import Interrupted, RestartRequired, TransferEngine, TransferJob


@unittest.skipUnless(Path('/dev/shm').is_dir(), 'Requires a disposable second filesystem')
class CrossVolumeMoveTests(unittest.TestCase):
    def setUp(self):
        source = tempfile.TemporaryDirectory(prefix='gudfiles-move-source-')
        target = tempfile.TemporaryDirectory(prefix='gudfiles-move-target-', dir='/dev/shm')
        self.addCleanup(source.cleanup)
        self.addCleanup(target.cleanup)
        self.source, self.target = Path(source.name), Path(target.name)
        if self.source.stat().st_dev == self.target.stat().st_dev:
            self.skipTest('Fixture filesystems must differ')
        self.engine = TransferEngine()
        self.file = self.source / 'clip.mov'
        self.data = bytes(range(256)) * 4096
        self.file.write_bytes(self.data)

    def job(self, path=None):
        return TransferJob([path or self.file], self.target, cut=True)

    def test_tree_links_and_empty_directories_move_and_notify_once(self):
        folder = self.source / 'footage'
        folder.mkdir()
        (folder / 'empty').mkdir()
        (folder / 'nested').mkdir()
        (folder / 'nested/clip.mov').write_bytes(self.data)
        (folder / 'external').symlink_to(self.file)
        (folder / 'broken').symlink_to('missing')
        job = self.job(folder)
        receipts = []
        job.on_completed = lambda *pair: receipts.append(pair)
        self.engine.run(job)
        self.assertFalse(folder.exists())
        self.assertEqual((self.target / 'footage/nested/clip.mov').read_bytes(), self.data)
        self.assertTrue((self.target / 'footage/empty').is_dir())
        self.assertEqual(os.readlink(self.target / 'footage/broken'), 'missing')
        self.assertEqual(self.file.read_bytes(), self.data)
        self.assertEqual(receipts, [(folder, self.target / folder.name)])
        self.engine.run(job)
        self.assertEqual(len(receipts), 1)
        self.assertEqual(list(self.source.iterdir()), [self.file])

    def test_destination_collision_keeps_both_unchanged(self):
        (self.target / self.file.name).write_bytes(b'existing')
        with self.assertRaises(FileExistsError):
            self.engine.run(self.job())
        self.assertEqual(self.file.read_bytes(), self.data)
        self.assertEqual((self.target / self.file.name).read_bytes(), b'existing')

    def test_changed_source_after_publish_is_retained(self):
        publish = self.engine._record_published
        def changed(job, item, identity):
            publish(job, item, identity)
            self.file.write_bytes(b'new edit')
        with patch.object(self.engine, '_record_published', side_effect=changed):
            with self.assertRaisesRegex(RestartRequired, 'source changed'):
                self.engine.run(self.job())
        self.assertEqual(self.file.read_bytes(), b'new edit')
        self.assertEqual((self.target / self.file.name).read_bytes(), self.data)

    def test_changed_published_copy_never_deletes_original(self):
        publish = self.engine._record_published
        def changed(job, item, identity):
            publish(job, item, identity)
            (self.target / self.file.name).write_bytes(b'changed')
        with patch.object(self.engine, '_record_published', side_effect=changed):
            with self.assertRaises(RestartRequired):
                self.engine.run(self.job())
        self.assertEqual(self.file.read_bytes(), self.data)

    def test_pause_after_publish_retains_recovery_and_resumes(self):
        job = self.job()
        def pause(job):
            if job.items and job.items[0].copied:
                job.stop.set()
        job.on_checkpoint = pause
        with self.assertRaises(Interrupted):
            self.engine.run(job)
        self.assertTrue(self.file.exists())
        self.assertFalse(job.completed)
        with self.assertRaisesRegex(ValueError, 'Resume this move'):
            self.engine.cleanup(job)
        with self.assertRaisesRegex(ValueError, 'Resume this move'):
            self.engine.restart(job)
        job.on_checkpoint = None
        job.stop.clear()
        self.engine.run(job)
        self.assertFalse(self.file.exists())
        self.assertEqual((self.target / self.file.name).read_bytes(), self.data)

    def test_interrupted_unlink_reconciles_without_recopying(self):
        folder = self.source / 'folder'
        folder.mkdir()
        (folder / 'a.mov').write_bytes(self.data)
        (folder / 'b.mov').write_bytes(b'other')
        job = self.job(folder)
        unlink = os.unlink
        failed = False
        def fail_after_delete(name, **kwargs):
            nonlocal failed
            unlink(name, **kwargs)
            if not failed and name == 'b.mov':
                failed = True
                raise OSError(errno.EIO, 'Lost deletion acknowledgement')
        with patch.object(move_cleanup.os, 'unlink', side_effect=fail_after_delete):
            with self.assertRaises(OSError):
                self.engine.run(job)
        self.assertFalse(job.completed)
        self.assertEqual(job.items[0].removing, Path('folder/b.mov'))
        self.engine.run(job)
        self.assertFalse(folder.exists())
        self.assertFalse(any(self.source.glob('.omarchy-move-*')))
        self.assertEqual((self.target / 'folder/a.mov').read_bytes(), self.data)
        self.assertEqual((self.target / 'folder/b.mov').read_bytes(), b'other')
        self.assertEqual(job.written_bytes, 0)

    def test_new_original_at_old_name_is_never_removed(self):
        rename = move_cleanup.rename_noreplace
        def replacement(*args):
            rename(*args)
            self.file.write_bytes(b'new recording')
        with patch.object(move_cleanup, 'rename_noreplace', side_effect=replacement):
            self.engine.run(self.job())
        self.assertEqual(self.file.read_bytes(), b'new recording')
        self.assertEqual((self.target / self.file.name).read_bytes(), self.data)

    def test_added_file_inside_held_original_is_preserved(self):
        folder = self.source / 'folder'
        folder.mkdir()
        (folder / 'clip').write_bytes(self.data)
        job = self.job(folder)
        rename = move_cleanup.rename_noreplace
        def replacement(*args):
            rename(*args)
            (self.source / args[3] / 'new-recording').write_bytes(b'new')
        with patch.object(move_cleanup, 'rename_noreplace', side_effect=replacement):
            with self.assertRaises(RestartRequired):
                self.engine.run(job)
        self.assertEqual((self.source / job.items[0].quarantine_name / 'new-recording').read_bytes(), b'new')
        self.assertEqual((self.target / 'folder/clip').read_bytes(), self.data)

    def test_preexisting_quarantine_hardlink_cannot_report_move_complete(self):
        job = self.job()
        def duplicate_at_intent(current):
            if current.items and current.items[0].quarantining:
                item = current.items[0]
                held = self.source / item.quarantine_name
                if not held.exists() and self.file.exists():
                    os.link(self.file, held)
        job.on_checkpoint = duplicate_at_intent
        with self.assertRaises(RestartRequired):
            self.engine.run(job)
        self.assertFalse(job.completed)
        self.assertEqual(self.file.read_bytes(), self.data)
        self.assertEqual((self.target / self.file.name).read_bytes(), self.data)


if __name__ == '__main__':
    unittest.main()
