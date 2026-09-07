import errno
import os
import stat
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from omarchy_file_picker import transfers

from omarchy_file_picker.transfers import (
    Interrupted, RestartRequired, TransferEngine, TransferJob, TransferQueue, rename_noreplace,
)


class TransferTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='transfer-fixture-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source, self.dest = self.root / 'source', self.root / 'destination'
        self.source.mkdir()
        self.dest.mkdir()
        self.file = self.source / 'footage.mov'
        self.data = bytes(range(256)) * 1024
        self.file.write_bytes(self.data)
        self.engine = TransferEngine()

    def job(self, sources=None, cut=False):
        return TransferJob(sources or [self.file], self.dest, cut)

    def partial(self, job):
        original = self.engine._write
        def fail(fd, data):
            original(fd, data[:65536])
            raise OSError(errno.ENOSPC, 'fixture disk full')
        with patch.object(self.engine, '_write', side_effect=fail):
            with self.assertRaises(OSError):
                self.engine.run(job)
        stage = self.dest / job.stage_name / '0'
        self.assertEqual(stage.stat().st_size, 65536)
        self.assertFalse((self.dest / self.file.name).exists())
        self.assertEqual(self.file.read_bytes(), self.data)
        return stage

    def test_verified_copy_is_published_and_staging_removed(self):
        job = self.job()
        self.engine.run(job)
        self.assertEqual((self.dest / self.file.name).read_bytes(), self.data)
        self.assertEqual(self.file.read_bytes(), self.data)
        self.assertEqual(list(self.dest.iterdir()), [self.dest / self.file.name])
        self.assertEqual(job.completed, {self.file: self.dest / self.file.name})

    def test_partial_failure_resumes_actual_bytes(self):
        job = self.job()
        stage = self.partial(job)
        inode = stage.stat().st_ino
        self.engine.run(job)
        target = self.dest / self.file.name
        self.assertEqual(target.read_bytes(), self.data)
        self.assertEqual(target.stat().st_ino, inode)
        self.assertEqual(job.written_bytes, len(self.data) - 65536)
        self.assertEqual(job.verified_bytes, 65536)

    def test_corrupt_partial_refuses_resume_then_explicit_restart_works(self):
        job = self.job()
        stage = self.partial(job)
        with stage.open('r+b') as handle:
            handle.write(b'WRONG')
        with self.assertRaisesRegex(RestartRequired, 'Saved bytes'):
            self.engine.run(job)
        self.assertFalse((self.dest / self.file.name).exists())
        self.engine.restart(job)
        self.engine.run(job)
        self.assertEqual(job.written_bytes, len(self.data))
        self.assertEqual((self.dest / self.file.name).read_bytes(), self.data)

    def test_changed_source_refuses_resume(self):
        job = self.job()
        self.partial(job)
        self.file.write_bytes(b'new contents')
        with self.assertRaisesRegex(RestartRequired, 'source changed'):
            self.engine.run(job)
        self.assertFalse((self.dest / self.file.name).exists())

    def test_replaced_source_with_same_size_and_mtime_is_rejected(self):
        job = self.job()
        self.partial(job)
        stamp = self.file.stat()
        self.file.unlink()
        self.file.write_bytes(self.data)
        os.utime(self.file, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        with self.assertRaises(RestartRequired):
            self.engine.run(job)

    def test_source_edit_during_copy_never_publishes(self):
        job = self.job()
        original = self.engine._write
        def changed(fd, data):
            original(fd, data)
            self.file.write_bytes(b'changed')
        with patch.object(self.engine, '_write', side_effect=changed):
            with self.assertRaises(RestartRequired):
                self.engine.run(job)
        self.assertFalse((self.dest / self.file.name).exists())

    def test_verify_catches_corruption_after_write(self):
        job = self.job()
        original = self.engine._write
        def corrupt(fd, data):
            original(fd, data)
            os.pwrite(fd, b'corrupt', 0)
        with patch.object(self.engine, '_write', side_effect=corrupt):
            with self.assertRaisesRegex(RestartRequired, 'verification failed'):
                self.engine.run(job)

    def test_nested_folder_symlinks_and_empty_files(self):
        folder = self.source / 'project'
        folder.mkdir()
        (folder / 'empty').mkdir()
        (folder / 'clip.mov').write_bytes(self.data)
        (folder / 'zero.txt').touch()
        (folder / 'outside').symlink_to(self.file)
        (folder / 'missing').symlink_to('unavailable')
        job = self.job([folder])
        self.engine.run(job)
        copied = self.dest / folder.name
        self.assertTrue((copied / 'empty').is_dir())
        self.assertEqual((copied / 'clip.mov').read_bytes(), self.data)
        self.assertTrue((copied / 'outside').is_symlink())
        self.assertEqual(os.readlink(copied / 'missing'), 'unavailable')
        self.assertEqual((copied / 'zero.txt').stat().st_size, 0)

    def test_special_files_rejected_without_blocking(self):
        fifo = self.source / 'pipe'
        os.mkfifo(fifo)
        with self.assertRaisesRegex(ValueError, 'only files'):
            self.engine.run(self.job([fifo]))

    def test_global_collision_prevents_any_transfer(self):
        other = self.source / 'other'
        other.write_text('source')
        (self.dest / other.name).write_text('unrelated')
        with self.assertRaises(FileExistsError):
            self.engine.run(self.job([self.file, other]))
        self.assertFalse((self.dest / self.file.name).exists())
        self.assertEqual((self.dest / other.name).read_text(), 'unrelated')

    def test_late_collision_never_overwrites_and_resume_after_resolution(self):
        job = self.job()
        def racing(srcfd, source, dstfd, target):
            (self.dest / target).write_text('unrelated')
            rename_noreplace(srcfd, source, dstfd, target)
        with patch('omarchy_file_picker.transfers.rename_noreplace', side_effect=racing):
            with self.assertRaises(FileExistsError):
                self.engine.run(job)
        self.assertEqual((self.dest / self.file.name).read_text(), 'unrelated')
        (self.dest / self.file.name).unlink()
        self.engine.run(job)
        self.assertEqual(job.written_bytes, 0)
        self.assertEqual((self.dest / self.file.name).read_bytes(), self.data)

    def test_error_after_committed_rename_is_reconciled(self):
        def committed(srcfd, source, dstfd, target):
            rename_noreplace(srcfd, source, dstfd, target)
            raise OSError(errno.EIO, 'fixture lost reply')
        with patch('omarchy_file_picker.transfers.rename_noreplace', side_effect=committed):
            job = self.job()
            self.engine.run(job)
        self.assertIn(self.file, job.completed)
        self.assertFalse(job.stage_name)

    def test_unreadable_commit_receipt_reconciles_on_resume_or_cancel(self):
        for cut in (False, True):
            for cancel in (False, True):
                with self.subTest(cut=cut, cancel=cancel):
                    self.file.write_bytes(self.data)
                    target = self.dest / self.file.name
                    if target.exists():
                        target.unlink()
                    job = self.job(cut=cut)
                    with patch.object(self.engine, '_record_completed', side_effect=OSError(errno.EIO, 'fixture receipt unavailable')):
                        with self.assertRaises(OSError):
                            self.engine.run(job)
                    self.assertTrue(job.items[0].publishing)
                    self.assertEqual(job.completed, {})
                    if cancel:
                        self.engine.cleanup(job)
                    else:
                        self.engine.run(job)
                    self.assertEqual(job.completed, {self.file: target})
                    self.assertEqual(target.read_bytes(), self.data)
                    self.assertFalse(job.stage_name)

    def test_move_source_replacement_race_is_restored_without_wrong_mapping(self):
        job = self.job(cut=True)
        original = self.source / 'kept-original'
        def race(srcfd, name, dstfd, target):
            if target == self.file.name and not original.exists():
                self.file.rename(original)
                self.file.write_text('replacement')
            rename_noreplace(srcfd, name, dstfd, target)
        with patch('omarchy_file_picker.transfers.rename_noreplace', side_effect=race):
            with self.assertRaises(RestartRequired):
                self.engine.run(job)
        self.assertEqual(original.read_bytes(), self.data)
        self.assertEqual(self.file.read_text(), 'replacement')
        self.assertEqual(job.completed, {})
        self.assertFalse((self.dest / self.file.name).exists())

    def test_alias_paths_retain_original_completed_mapping(self):
        alias = self.root / 'source alias'
        alias.symlink_to(self.source)
        requested = alias / self.file.name
        job = self.job([requested], cut=True)
        self.engine.run(job)
        self.assertEqual(job.completed, {requested: self.dest / self.file.name})

    def test_cancel_removes_only_partials(self):
        job = self.job()
        self.partial(job)
        unrelated = self.dest / 'keep.txt'
        unrelated.write_text('keep')
        self.engine.cleanup(job)
        self.assertEqual(list(self.dest.iterdir()), [unrelated])
        self.assertEqual(self.file.read_bytes(), self.data)

    def test_cleanup_rejects_replaced_partial_and_hardlink(self):
        job = self.job()
        stage = self.partial(job)
        stage.unlink()
        stage.symlink_to(self.file)
        with self.assertRaises(RestartRequired):
            self.engine.cleanup(job)
        self.assertEqual(self.file.read_bytes(), self.data)
        stage.unlink()
        os.link(self.file, stage)
        with self.assertRaises(RestartRequired):
            self.engine.run(job)
        self.assertEqual(self.file.read_bytes(), self.data)

    def test_unexpected_file_prevents_cleanup(self):
        job = self.job()
        stage = self.partial(job)
        surprise = stage.parent / 'keep'
        surprise.write_text('unexpected')
        with self.assertRaises(RestartRequired):
            self.engine.cleanup(job)
        self.assertTrue(stage.exists())
        self.assertEqual(surprise.read_text(), 'unexpected')

    def test_cleanup_rejects_reused_inode_with_different_type(self):
        job = self.job()
        stage = self.partial(job)
        original = stage.stat()
        stage.unlink()
        stage.symlink_to(self.file)
        real_stat = transfers.entry_stat

        def reused_inode(fd, name):
            info = real_stat(fd, name)
            if stat.S_ISLNK(info.st_mode):
                values = list(info)
                values[1], values[2] = original.st_ino, original.st_dev
                return os.stat_result(values)
            return info

        with patch.object(transfers, 'entry_stat', side_effect=reused_inode):
            with self.assertRaises(RestartRequired):
                self.engine.cleanup(job)
        self.assertTrue(stage.is_symlink())
        self.assertEqual(self.file.read_bytes(), self.data)

    def test_replaced_destination_cannot_receive_resumed_data(self):
        job = self.job()
        self.partial(job)
        self.dest.rename(self.root / 'original-destination')
        self.dest.mkdir()
        with self.assertRaises(RestartRequired):
            self.engine.run(job)
        self.assertEqual(list(self.dest.iterdir()), [])

    def test_copy_inside_self_and_overlapping_sources_rejected(self):
        nested = self.source / 'nested'
        nested.mkdir()
        with self.assertRaises(ValueError):
            self.engine.run(TransferJob([self.source], nested))
        with self.assertRaises(ValueError):
            self.engine.run(self.job([self.source, self.file]))

    def test_pause_in_copy_retains_bytes(self):
        job = self.job()
        original = self.engine._write
        def pause(fd, data):
            original(fd, data)
            job.stop.set()
        with patch.object(self.engine, '_write', side_effect=pause):
            with self.assertRaises(Interrupted):
                self.engine.run(job)
        self.assertFalse((self.dest / self.file.name).exists())
        job.stop.clear()
        self.engine.run(job)
        self.assertEqual(job.written_bytes, 0)

    def test_same_volume_move_and_partial_success(self):
        other = self.source / 'second'
        other.write_text('second')
        job = self.job([self.file, other], cut=True)
        def fail_second(srcfd, source, dstfd, target):
            if target == other.name:
                raise OSError(errno.EIO, 'fixture failure')
            rename_noreplace(srcfd, source, dstfd, target)
        with patch('omarchy_file_picker.transfers.rename_noreplace', side_effect=fail_second):
            with self.assertRaises(OSError):
                self.engine.run(job)
        self.assertFalse(self.file.exists())
        self.assertTrue(other.exists())
        self.assertEqual(job.completed, {self.file: self.dest / self.file.name})
        self.engine.run(job)
        self.assertEqual(len(job.completed), 2)
        self.assertEqual((self.dest / other.name).read_text(), 'second')

    def test_cross_volume_move_never_copies_or_deletes_source(self):
        with patch('omarchy_file_picker.transfers.rename_noreplace', side_effect=OSError(errno.EXDEV, 'cross device')):
            with self.assertRaisesRegex(ValueError, 'Moving between volumes'):
                self.engine.run(self.job(cut=True))
        self.assertEqual(self.file.read_bytes(), self.data)
        self.assertEqual(list(self.dest.iterdir()), [])

    @unittest.skipUnless(Path('/dev/shm').is_dir(), 'A second disposable filesystem is unavailable')
    def test_real_cross_volume_copy_and_move_boundary(self):
        with tempfile.TemporaryDirectory(prefix='picker-transfer-', dir='/dev/shm') as temp:
            destination = Path(temp)
            if destination.stat().st_dev == self.source.stat().st_dev:
                self.skipTest('Fixture locations share a filesystem')
            self.engine.run(TransferJob([self.file], destination))
            target = destination / self.file.name
            self.assertEqual(target.read_bytes(), self.data)
            target.unlink()
            with self.assertRaisesRegex(ValueError, 'Moving between volumes'):
                self.engine.run(TransferJob([self.file], destination, cut=True))
            self.assertEqual(self.file.read_bytes(), self.data)
            self.assertEqual(list(destination.iterdir()), [])

    def test_restart_keeps_completed_files_and_continues_remaining(self):
        other = self.source / 'second'
        other.write_text('second')
        job = self.job([self.file, other])
        def fail_second(srcfd, source, dstfd, target):
            if target == other.name:
                raise OSError(errno.EIO, 'fixture failure')
            rename_noreplace(srcfd, source, dstfd, target)
        with patch('omarchy_file_picker.transfers.rename_noreplace', side_effect=fail_second):
            with self.assertRaises(OSError):
                self.engine.run(job)
        self.engine.restart(job)
        self.engine.run(job)
        self.assertEqual(len(job.completed), 2)
        self.assertEqual((self.dest / self.file.name).read_bytes(), self.data)


def wait_for(predicate):
    deadline = time.monotonic() + 4
    while not predicate() and time.monotonic() < deadline:
        time.sleep(.005)
    if not predicate():
        raise AssertionError('Worker did not reach the expected state')


class ControlledEngine:
    def __init__(self):
        self.calls = []
        self.release = threading.Event()

    def run(self, job):
        self.calls.append(job.id)
        while not self.release.wait(.01):
            job.checkpoint()

    def cleanup(self, job):
        pass


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.engine = ControlledEngine()
        self.queue = TransferQueue(self.engine)
        self.addCleanup(self.engine.release.set)

    def add(self, start=False):
        return self.queue.add([Path('/fixture/source')], Path('/fixture/dest'), start=start)

    def test_staging_never_starts_until_requested(self):
        first = self.add()
        second = self.add()
        self.assertEqual(self.engine.calls, [])
        self.queue.start(first)
        wait_for(lambda: self.engine.calls == [first.id])
        self.engine.release.set()
        wait_for(lambda: self.queue.active is None)
        self.assertEqual(second.state, 'queued')

    def test_sequential_queue_and_new_staged_job_stays_queued(self):
        first, second = self.add(), self.add()
        self.queue.start()
        wait_for(lambda: len(self.engine.calls) == 1)
        third = self.add()
        self.assertEqual(second.state, 'waiting')
        self.engine.release.set()
        wait_for(lambda: self.queue.active is None)
        self.assertEqual(self.engine.calls, [first.id, second.id])
        self.assertEqual(third.state, 'queued')

    def test_pause_holds_following_jobs_and_resume_continues(self):
        first, second = self.add(), self.add()
        self.queue.start()
        wait_for(lambda: len(self.engine.calls) == 1)
        self.queue.pause()
        wait_for(lambda: self.queue.active is None)
        self.assertEqual(first.state, 'paused')
        self.assertEqual(second.state, 'waiting')
        third = self.add(start=True)
        self.assertEqual(third.state, 'waiting')
        self.queue.start(first)
        self.engine.release.set()
        wait_for(lambda: self.queue.active is None)
        self.assertEqual(self.engine.calls, [first.id, first.id, second.id, third.id])

    def test_failure_holds_the_queue(self):
        def fail(job):
            raise OSError('fixture unavailable')
        with patch.object(self.engine, 'run', side_effect=fail):
            first, second = self.add(), self.add()
            self.queue.start()
            wait_for(lambda: self.queue.active is None)
        self.assertEqual(first.state, 'failed')
        self.assertEqual(second.state, 'waiting')
        self.assertTrue(self.queue.held)

    def test_cancel_queued_does_not_start_it(self):
        job = self.add()
        self.queue.cancel(job)
        wait_for(lambda: self.queue.active is None)
        self.assertEqual(job.state, 'cancelled')
        self.assertEqual(self.engine.calls, [])
        self.queue.clear_finished()
        self.assertEqual(self.queue.jobs, [])

    def test_cancel_active_and_clear_do_not_touch_unfinished(self):
        first = self.add(start=True)
        second = self.add()
        self.queue.cancel(first)
        wait_for(lambda: self.queue.active is None)
        self.assertEqual(first.state, 'cancelled')
        self.queue.clear_finished()
        self.assertEqual(self.queue.jobs, [second])


class ParallelEngine:
    """Keep workers inside real threads until their individual gates open."""
    def __init__(self):
        self.calls = []
        self.gates = {}
        self.fail = set()
        self.running = set()
        self.max_running = 0
        self.lock = threading.Lock()
        self.release_all = threading.Event()
        self.cleaned = []

    def run(self, job):
        with self.lock:
            gate = self.gates.setdefault(job.id, threading.Event())
            self.calls.append(job.id)
            self.running.add(job.id)
            self.max_running = max(self.max_running, len(self.running))
        try:
            while not gate.wait(.005) and not self.release_all.is_set():
                job.checkpoint()
            if job.id in self.fail:
                raise OSError('fixture failure')
        finally:
            with self.lock:
                self.running.remove(job.id)

    def cleanup(self, job):
        self.cleaned.append(job.id)

    def release(self, job):
        self.gates[job.id].set()


class TransferModeTests(unittest.TestCase):
    def setUp(self):
        self.engine = ParallelEngine()
        self.queue = TransferQueue(self.engine)
        def stop():
            self.queue.pause()
            self.engine.release_all.set()
            wait_for(lambda: not self.queue.active_jobs)
        self.addCleanup(stop)

    def add(self, count=1):
        return [self.queue.add([Path(f'/fixture/source/clip-{len(self.queue.jobs)}')], Path('/fixture/dest'))
                for _ in range(count)]

    def test_all_mode_still_requires_start_and_bounds_parallel_workers(self):
        jobs = self.add(5)
        self.queue.set_mode('all')
        self.assertEqual(self.engine.calls, [])
        self.queue.start()
        wait_for(lambda: len(self.engine.calls) == 3)
        staged = self.add()[0]
        self.engine.release(jobs[0])
        wait_for(lambda: len(self.engine.calls) == 4)
        self.assertEqual(staged.state, 'queued')
        self.assertEqual(self.engine.max_running, 3)
        self.engine.release_all.set()
        wait_for(lambda: not self.queue.active_jobs)
        self.assertTrue(all(job.state == 'completed' for job in jobs))
        self.assertEqual(staged.state, 'queued')

    def test_live_mode_switch_drains_existing_workers_before_queue_starts_more(self):
        jobs = self.add(5)
        self.queue.start()
        wait_for(lambda: len(self.engine.calls) == 1)
        self.queue.set_mode('all')
        wait_for(lambda: len(self.engine.calls) == 3)
        self.queue.set_mode('queue')
        self.assertEqual(len(self.queue.active_jobs), 3)
        for job in jobs[:2]:
            self.engine.release(job)
        wait_for(lambda: len(self.queue.active_jobs) == 1)
        self.assertEqual(len(self.engine.calls), 3)
        self.engine.release(jobs[2])
        wait_for(lambda: len(self.engine.calls) == 4)
        self.assertEqual(len(self.queue.active_jobs), 1)
        self.assertEqual(jobs[4].state, 'waiting')

    def test_individual_pause_and_pause_all_are_distinct(self):
        jobs = self.add(4)
        self.queue.set_mode('all')
        self.queue.start()
        wait_for(lambda: len(self.engine.calls) == 3)
        self.queue.pause(jobs[0])
        wait_for(lambda: jobs[0].state == 'paused' and len(self.engine.calls) == 4)
        self.assertFalse(self.queue.held)
        self.assertTrue(all(job.state == 'running' for job in jobs[1:]))
        self.queue.pause()
        wait_for(lambda: not self.queue.active_jobs)
        self.assertTrue(self.queue.held)
        self.assertTrue(all(job.state == 'paused' for job in jobs))
        self.queue.set_mode('queue')
        self.queue.set_mode('all')
        self.assertEqual(len(self.engine.calls), 4)
        self.queue.start(jobs[0])
        wait_for(lambda: len(self.engine.calls) == 5)
        self.assertTrue(all(job.state == 'paused' for job in jobs[1:]))

    def test_independent_failure_in_all_mode_does_not_stop_other_transfers(self):
        jobs = self.add(4)
        self.queue.set_mode('all')
        self.queue.start()
        wait_for(lambda: len(self.engine.calls) == 3)
        self.engine.fail.add(jobs[0].id)
        self.engine.release(jobs[0])
        wait_for(lambda: jobs[0].state == 'failed' and len(self.engine.calls) == 4)
        self.assertFalse(self.queue.held)
        self.assertTrue(all(job.state == 'running' for job in jobs[1:]))

    def test_cancel_saved_partial_waits_for_a_cleanup_slot(self):
        jobs = self.add(4)
        self.queue.set_mode('all')
        self.queue.start()
        wait_for(lambda: len(self.engine.calls) == 3)
        jobs[0].stage_name = 'fixture-partial'
        self.queue.pause(jobs[0])
        wait_for(lambda: jobs[0].state == 'paused' and len(self.engine.calls) == 4)
        self.queue.cancel(jobs[0])
        self.assertEqual(jobs[0].state, 'cancelling')
        self.assertEqual(self.engine.cleaned, [])
        self.engine.release(jobs[1])
        wait_for(lambda: jobs[0].state == 'cancelled')
        self.assertEqual(self.engine.cleaned, [jobs[0].id])

    def test_conflicting_destinations_wait_while_independent_work_can_start(self):
        first = self.queue.add([Path('/source-one/clip.mov')], Path('/target'))
        second = self.queue.add([Path('/source-two/clip.mov')], Path('/target'))
        third = self.queue.add([Path('/source-three/other.mov')], Path('/target'))
        self.queue.set_mode('all')
        self.queue.start()
        wait_for(lambda: len(self.engine.calls) == 2)
        self.assertEqual(set(self.engine.calls), {first.id, third.id})
        self.assertEqual(second.phase, 'Waiting for a related transfer')
        self.engine.release(first)
        wait_for(lambda: second.id in self.engine.calls)

    def test_pending_dependencies_cannot_overtake_a_blocked_transfer(self):
        first = self.queue.add([Path('/a/clip.mov')], Path('/b'), cut=True)
        second = self.queue.add([Path('/b/clip.mov')], Path('/c'), cut=True)
        third = self.queue.add([Path('/c/clip.mov')], Path('/d'), cut=True)
        self.queue.set_mode('all')
        self.queue.start()
        wait_for(lambda: len(self.engine.calls) == 1)
        self.assertEqual(self.engine.calls, [first.id])
        self.engine.release(first)
        wait_for(lambda: len(self.engine.calls) == 2)
        self.assertEqual(self.engine.calls, [first.id, second.id])
        self.engine.release(second)
        wait_for(lambda: len(self.engine.calls) == 3)
        self.assertEqual(self.engine.calls, [first.id, second.id, third.id])

    def test_nested_move_waits_for_a_copy_reading_its_contents(self):
        first = self.queue.add([Path('/source/folder/clip.mov')], Path('/copy'))
        second = self.queue.add([Path('/source/folder')], Path('/moved'), cut=True)
        self.queue.set_mode('all')
        self.queue.start()
        wait_for(lambda: len(self.engine.calls) == 1)
        self.assertEqual(self.engine.calls, [first.id])
        self.engine.release(first)
        wait_for(lambda: second.id in self.engine.calls)

    def test_same_source_copies_to_different_destinations_can_run_together(self):
        first = self.queue.add([Path('/source/clip.mov')], Path('/dest-one'))
        second = self.queue.add([Path('/source/clip.mov')], Path('/dest-two'))
        self.queue.set_mode('all')
        self.queue.start()
        wait_for(lambda: len(self.engine.calls) == 2)
        self.assertEqual(set(self.engine.calls), {first.id, second.id})

    def test_invalid_mode_is_rejected_without_starting_work(self):
        self.add()
        with self.assertRaises(ValueError):
            self.queue.set_mode('anything')
        self.assertEqual(self.queue.mode, 'queue')
        self.assertEqual(self.engine.calls, [])


if __name__ == '__main__':
    unittest.main()
