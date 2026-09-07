import errno
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from omarchy_file_picker.transfers import (
    Interrupted, RestartRequired, TransferEngine, TransferJob, TransferQueue, rename_noreplace,
)


class DuplicateTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='duplicate-fixture-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root / 'Clip.mov'
        self.data = b'original footage' * 10_000
        self.source.write_bytes(self.data)
        self.engine = TransferEngine()

    def job(self, sources=None, destination=None):
        return TransferJob(sources or [self.source], destination or self.root, duplicate=True)

    def test_same_folder_numbering_keeps_originals_and_broken_links(self):
        first = self.root / 'Clip copy.mov'
        second = self.root / 'Clip copy 2.mov'
        first.write_text('earlier copy')
        second.symlink_to('missing')
        job = self.job()
        self.engine.run(job)
        self.assertEqual(job.completed, {self.source: self.root / 'Clip copy 3.mov'})
        self.assertEqual(job.completed[self.source].read_bytes(), self.data)
        self.assertEqual(self.source.read_bytes(), self.data)
        self.assertEqual(first.read_text(), 'earlier copy')
        self.assertTrue(second.is_symlink())
        self.assertFalse(job.stage_name)

    def test_folder_names_with_dots_and_links_are_preserved(self):
        folder = self.root / 'Project.v2'
        folder.mkdir()
        (folder / 'take.txt').write_text('take')
        (folder / 'link.txt').symlink_to('take.txt')
        job = self.job([folder])
        self.engine.run(job)
        target = self.root / 'Project.v2 copy'
        self.assertEqual(job.completed[folder], target)
        self.assertEqual((target / 'take.txt').read_text(), 'take')
        self.assertTrue((target / 'link.txt').is_symlink())
        self.assertEqual(os.readlink(target / 'link.txt'), 'take.txt')

    def test_hidden_and_long_multibyte_names_fit_destination(self):
        hidden, long = self.root / '.notes', self.root / ('é' * 125 + '.txt')
        hidden.write_text('hidden')
        long.write_text('long')
        job = self.job([hidden, long])
        self.engine.run(job)
        self.assertEqual(job.completed[hidden].name, '.notes copy')
        target = job.completed[long]
        self.assertLessEqual(len(os.fsencode(target.name)), 255)
        self.assertTrue(target.name.endswith(' copy.txt'))
        self.assertEqual(target.read_text(), 'long')

    def test_different_folder_uses_original_name_and_keeps_both_on_collision(self):
        dest = self.root / 'destination'
        dest.mkdir()
        for expected in ('Clip.mov', 'Clip copy.mov'):
            job = self.job(destination=dest)
            self.engine.run(job)
            self.assertEqual(job.completed[self.source], dest / expected)
            self.assertEqual((dest / expected).read_bytes(), self.data)

    def test_batch_reserves_names_for_identical_basenames(self):
        other = self.root / 'other'
        other.mkdir()
        second = other / self.source.name
        second.write_bytes(b'second')
        job = self.job([self.source, second])
        self.engine.run(job)
        self.assertEqual(job.completed[self.source].name, 'Clip copy.mov')
        self.assertEqual(job.completed[second].name, 'Clip copy 2.mov')
        self.assertEqual(job.completed[second].read_bytes(), b'second')

    def test_publication_race_chooses_another_name_without_overwrite(self):
        raced = self.root / 'Clip copy.mov'
        def publish(srcfd, source, dstfd, target):
            if not raced.exists():
                raced.write_text('arrived while copying')
            rename_noreplace(srcfd, source, dstfd, target)
        job = self.job()
        with patch('omarchy_file_picker.transfers.rename_noreplace', side_effect=publish):
            self.engine.run(job)
        self.assertEqual(raced.read_text(), 'arrived while copying')
        self.assertEqual(job.completed[self.source].name, 'Clip copy 2.mov')
        self.assertEqual(job.completed[self.source].read_bytes(), self.data)

    def test_ambiguous_publication_reconciles_the_renamed_copy(self):
        job = self.job()
        def publish(srcfd, source, dstfd, target):
            rename_noreplace(srcfd, source, dstfd, target)
            raise OSError(errno.EIO, 'reply lost after commit')
        with patch('omarchy_file_picker.transfers.rename_noreplace', side_effect=publish):
            self.engine.run(job)
        self.assertEqual(job.completed[self.source].name, 'Clip copy.mov')
        self.assertEqual(job.completed[self.source].read_bytes(), self.data)
        self.assertEqual(len(list(self.root.iterdir())), 2)

    def pause(self, job):
        write = self.engine._write
        def pause(fd, data):
            write(fd, data[:16384])
            raise Interrupted()
        with patch.object(self.engine, '_write', side_effect=pause):
            with self.assertRaises(Interrupted):
                self.engine.run(job)
        return self.root / job.stage_name / '0'

    def test_resume_reuses_verified_bytes_and_handles_new_name_collision(self):
        job = self.job()
        stage = self.pause(job)
        inode = stage.stat().st_ino
        (self.root / 'Clip copy.mov').write_text('created while paused')
        self.engine.run(job)
        target = job.completed[self.source]
        self.assertEqual(target.name, 'Clip copy 2.mov')
        self.assertEqual(target.stat().st_ino, inode)
        self.assertEqual(job.verified_bytes, 16384)
        self.assertEqual(job.written_bytes, len(self.data) - 16384)
        self.assertEqual(target.read_bytes(), self.data)

    def test_changed_source_requires_restart_and_cancel_preserves_source(self):
        job = self.job()
        stage = self.pause(job)
        self.source.write_text('updated')
        with self.assertRaises(RestartRequired):
            self.engine.run(job)
        self.engine.restart(job)
        self.assertFalse(stage.exists())
        self.engine.run(job)
        self.assertEqual(job.completed[self.source].read_text(), 'updated')
        again = self.job()
        self.pause(again)
        self.engine.cleanup(again)
        self.assertEqual(self.source.read_text(), 'updated')
        self.assertEqual(set(self.root.iterdir()), {self.source, job.completed[self.source]})

    def test_self_descendant_duplicate_and_duplicate_move_are_rejected(self):
        folder = self.root / 'folder'
        folder.mkdir()
        for job in (self.job([folder], folder), self.job([self.source, self.source]),
                    TransferJob([self.source], self.root, cut=True, duplicate=True)):
            with self.assertRaises(ValueError):
                self.engine.run(job)
        self.assertEqual(self.source.read_bytes(), self.data)
        self.assertEqual(list(folder.iterdir()), [])

    def test_all_mode_serializes_dynamic_names_then_copies_each_batch(self):
        queue = TransferQueue(mode='all')
        jobs = [queue.add([self.source], self.root, duplicate=True) for _ in range(3)]
        self.assertTrue(queue._conflicts(jobs[0], jobs[1]))
        queue.start()
        deadline = time.monotonic() + 5
        while queue.unfinished and time.monotonic() < deadline:
            time.sleep(.005)
        self.assertTrue(all(job.state == 'completed' for job in jobs), [j.error for j in jobs])
        self.assertEqual({j.completed[self.source].name for j in jobs},
                         {'Clip copy.mov', 'Clip copy 2.mov', 'Clip copy 3.mov'})


if __name__ == '__main__':
    unittest.main()
