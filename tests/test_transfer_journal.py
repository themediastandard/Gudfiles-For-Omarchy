"""Real process termination/relaunch and private transfer recovery receipts."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from omarchy_file_picker.transfer_journal import TransferJournal, _encode
from omarchy_file_picker.transfers import TransferEngine, TransferJob, TransferQueue


def wait_for(predicate):
    deadline = time.monotonic() + 10
    while not predicate() and time.monotonic() < deadline:
        time.sleep(.01)
    if not predicate():
        raise AssertionError('Transfer did not settle')


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.source.write_bytes(b'abcdefgh' * 300000)
        self.destination = self.root / 'destination'
        self.destination.mkdir()
        self.state = self.root / 'state'
        self.queues = []

    def tearDown(self):
        for queue in self.queues:
            queue.close()
            wait_for(lambda: not queue.active_jobs)

    def queue(self):
        queue = TransferQueue(journal_dir=self.state)
        self.queues.append(queue)
        return queue

    def crash(self, point):
        script = r'''
import os, sys
from pathlib import Path
from omarchy_file_picker.transfers import TransferEngine, TransferJob
from omarchy_file_picker.transfer_journal import TransferJournal
from unittest.mock import patch
root=Path(sys.argv[1]); point=sys.argv[2]
journal=TransferJournal(root/'state')
job=TransferJob([root/'source'], root/'destination')
def checkpoint(job):
    journal.save(job)
    if point == 'receipt' and job.completed:
        os._exit(33)
job.on_checkpoint=checkpoint
journal.save(job)
class Engine(TransferEngine):
    def _write(self, fd, data):
        super()._write(fd, data)
        if point == 'partial':
            os.fsync(fd)
            os._exit(31)
    def _record_completed(self, job, item):
        if point == 'published':
            os._exit(32)
        super()._record_completed(job,item)
Engine().run(job)
raise RuntimeError('Crash point was not reached')
'''
        result = subprocess.run([sys.executable, '-c', script, str(self.root), point], capture_output=True, text=True)
        self.assertEqual(result.returncode, {'partial': 31, 'published': 32, 'receipt': 33}[point], result.stderr)

    def test_crash_mid_copy_reloads_paused_then_verifies_and_resumes(self):
        self.crash('partial')
        queue = self.queue()
        self.assertEqual(queue.recovery_errors, [])
        job, = queue.jobs
        self.assertEqual(job.state, 'paused')
        self.assertTrue(queue.held)
        self.assertTrue(job.owned)
        self.assertFalse((self.destination / 'source').exists())
        queue.start(job)
        wait_for(lambda: not queue.active_jobs)
        self.assertEqual(job.state, 'completed', job.error)
        self.assertEqual((self.destination/'source').read_bytes(), self.source.read_bytes())
        self.assertGreater(job.verified_bytes, 0)

    def test_crash_after_rename_before_receipt_never_recopies(self):
        self.crash('published')
        inode = (self.destination/'source').stat().st_ino
        queue = self.queue()
        job, = queue.jobs
        queue.start(job)
        wait_for(lambda: not queue.active_jobs)
        self.assertEqual(job.state, 'completed', job.error)
        self.assertEqual((self.destination/'source').stat().st_ino, inode)
        self.assertEqual(len(job.completed), 1)
        self.assertEqual(len(queue.completed_events()), 1)

    def test_crash_after_completion_receipt_does_not_repeat_event(self):
        self.crash('receipt')
        queue = self.queue()
        job, = queue.jobs
        self.assertEqual(len(job.completed), 1)
        queue.start(job)
        wait_for(lambda: not queue.active_jobs)
        self.assertEqual(job.state, 'completed', job.error)
        self.assertEqual(queue.completed_events(), [])

    def test_changed_source_or_partial_refuses_resume(self):
        self.crash('partial')
        self.source.write_bytes(b'changed')
        queue = self.queue()
        job, = queue.jobs
        queue.start(job)
        wait_for(lambda: not queue.active_jobs)
        self.assertEqual(job.state, 'failed')
        self.assertTrue(job.restart_required)
        self.assertFalse((self.destination/'source').exists())

    def test_one_window_claims_recovery_until_close(self):
        first = self.queue()
        job = first.add([self.source], self.destination)
        second = self.queue()
        self.assertEqual(second.jobs, [])
        script = 'from omarchy_file_picker.transfers import TransferQueue; import sys; q=TransferQueue(journal_dir=sys.argv[1]); print(len(q.jobs)); q.close()'
        result = subprocess.check_output([sys.executable, '-c', script, str(self.state)], text=True)
        self.assertEqual(result.strip(), '0')
        first.close()
        third = self.queue()
        self.assertEqual([j.id for j in third.jobs], [job.id])
        self.assertEqual(third.jobs[0].state, 'paused')

    def test_corrupt_receipt_is_visible_and_left_untouched(self):
        self.state.mkdir(mode=0o700)
        path = self.state / ('a'*32 + '.json')
        path.write_bytes(b'{broken')
        queue = self.queue()
        self.assertEqual(queue.jobs, [])
        self.assertEqual(len(queue.recovery_errors), 1)
        self.assertEqual(path.read_bytes(), b'{broken')

    def test_completed_event_survives_one_shot_final_checkpoint_failure(self):
        queue = self.queue()
        job = queue.add([self.source], self.destination, cut=True)
        checkpoint = job.on_checkpoint
        failed = False
        def fail_final_once(current):
            nonlocal failed
            if current.completed and not failed:
                failed = True
                raise OSError('Transient receipt storage failure')
            checkpoint(current)
        job.on_checkpoint = fail_final_once
        queue.start(job)
        wait_for(lambda: not queue.active_jobs)
        self.assertEqual(job.state, 'failed')
        self.assertTrue(job.completed)
        self.assertEqual(len(queue.completed_events()), 1)
        inode = (self.destination/self.source.name).stat().st_ino
        queue.start(job)
        wait_for(lambda: not queue.active_jobs)
        self.assertEqual(job.state, 'completed', job.error)
        self.assertEqual(queue.completed_events(), [])
        self.assertEqual((self.destination/self.source.name).stat().st_ino, inode)
        self.assertFalse(self.source.exists())

    def test_atomic_failure_keeps_previous_receipt(self):
        queue = self.queue()
        job = queue.add([self.source], self.destination)
        path = self.state / (job.id + '.json')
        previous = path.read_bytes()
        with patch('omarchy_file_picker.transfer_journal.os.rename', side_effect=OSError('disk fault')):
            with self.assertRaises(OSError):
                queue.journal.save(job)
        self.assertEqual(path.read_bytes(), previous)
        self.assertFalse(list(self.state.glob('*.tmp')))

    def test_path_traversal_receipt_rejected(self):
        queue = self.queue()
        job = queue.add([self.source], self.destination)
        path = self.state / (job.id + '.json')
        queue.close()
        raw = json.loads(path.read_text())
        raw['job']['fields']['stage_name'] = '../unrelated'
        path.write_text(json.dumps(raw))
        recovered = self.queue()
        self.assertEqual(recovered.jobs, [])
        self.assertTrue(recovered.recovery_errors)

    def test_nonprivate_state_folder_prevents_unrecoverable_job(self):
        self.state.mkdir(mode=0o755)
        queue = self.queue()
        self.assertTrue(queue.recovery_errors)
        with self.assertRaises(OSError):
            queue.add([self.source], self.destination)
        self.assertEqual(queue.jobs, [])

    def test_clear_finished_removes_durable_history(self):
        queue = self.queue()
        job = queue.add([self.source], self.destination, start=True)
        wait_for(lambda: not queue.active_jobs)
        self.assertEqual(job.state, 'completed', job.error)
        queue.clear_finished()
        self.assertFalse(list(self.state.glob('*.json')))



    def test_cross_volume_crashes_recover_quarantine_and_unlink_intent(self):
        if not Path('/dev/shm').is_dir() or self.root.stat().st_dev == Path('/dev/shm').stat().st_dev:
            self.skipTest('A separate disposable filesystem is required')
        script = r'''import os,sys
from pathlib import Path
from unittest.mock import patch
from omarchy_file_picker.transfers import TransferEngine,TransferJob
from omarchy_file_picker.transfer_journal import TransferJournal
from omarchy_file_picker import move_cleanup
root=Path(sys.argv[1]); destination=Path(sys.argv[2]); point=sys.argv[3]
journal=TransferJournal(root/'state')
job=TransferJob([root/'folder'],destination,True)
job.on_checkpoint=journal.save
journal.save(job)
rename=move_cleanup.rename_noreplace
unlink=os.unlink
def crash_rename(*args):
    rename(*args)
    if point=='quarantine': os._exit(34)
def crash_unlink(name,**kwargs):
    unlink(name,**kwargs)
    if point=='unlink' and str(name)=='second.bin': os._exit(35)
with patch.object(move_cleanup,'rename_noreplace',side_effect=crash_rename), patch.object(move_cleanup.os,'unlink',side_effect=crash_unlink):
    TransferEngine().run(job)
raise RuntimeError('Crash point not reached')
'''
        for point, code in [('quarantine', 34), ('unlink', 35)]:
            with self.subTest(point=point), tempfile.TemporaryDirectory(dir='/dev/shm', prefix='gudfiles-journal-') as dest:
                folder = self.root / 'folder'
                folder.mkdir()
                (folder/'first.bin').write_bytes(b'first-data')
                (folder/'second.bin').write_bytes(b'second-data')
                result = subprocess.run([sys.executable, '-c', script, str(self.root), dest, point], capture_output=True, text=True)
                self.assertEqual(result.returncode, code, result.stderr)
                queue = self.queue()
                job = next(job for job in queue.jobs if job.state not in {'completed', 'cancelled'})
                self.assertEqual(job.state, 'paused')
                self.assertTrue(job.items[0].copied)
                self.assertFalse(folder.exists())
                inode = (Path(dest)/'folder').stat().st_ino
                queue.start(job)
                wait_for(lambda: not queue.active_jobs)
                self.assertEqual(job.state, 'completed', job.error)
                self.assertEqual((Path(dest)/'folder').stat().st_ino, inode)
                self.assertEqual((Path(dest)/'folder'/'first.bin').read_bytes(), b'first-data')
                self.assertEqual((Path(dest)/'folder'/'second.bin').read_bytes(), b'second-data')
                self.assertFalse(list(self.root.glob('.omarchy-move-*')))
                queue.clear_finished()
                queue.close()

    def test_move_annotation_crash_replay_is_transactionally_idempotent(self):
        from omarchy_file_picker.ratings import RatingStore, EMPTY
        script = r'''import os,sys
from pathlib import Path
from omarchy_file_picker.transfers import TransferEngine,TransferJob
from omarchy_file_picker.transfer_journal import TransferJournal
from omarchy_file_picker.ratings import RatingStore
root=Path(sys.argv[1]); point=sys.argv[2]
source=root/'source'; target=root/'destination'/'source'
store=RatingStore(root/'ratings.sqlite3')
store.set_many([source], stars=4, color='blue')
journal=TransferJournal(root/'state')
job=TransferJob([source],root/'destination',True)
job.on_checkpoint=journal.save
journal.save(job)
TransferEngine().run(job)
if point=='after': store.move(job.completed, receipt=job.id)
os._exit(36)
'''
        for point in ['before', 'after']:
            with self.subTest(point=point):
                result = subprocess.run([sys.executable, '-c', script, str(self.root), point], capture_output=True, text=True)
                self.assertEqual(result.returncode, 36, result.stderr)
                queue = self.queue()
                job, = queue.jobs
                events = queue.completed_events()
                self.assertEqual(len(events), 1)
                store = RatingStore(self.root/'ratings.sqlite3')
                mapping = {source: target for _, source, target in events}
                store.move(mapping, receipt=job.id)
                store.refresh([self.source, self.destination/'source'])
                self.assertEqual(store.get(self.source), EMPTY)
                self.assertEqual(store.get(self.destination/'source'), (4, 'blue', False))
                # A second receipt replay after later target edits must also be harmless.
                store.set_many([self.destination/'source'], stars=5)
                store.move(mapping, receipt=job.id)
                store.refresh([self.destination/'source'])
                self.assertEqual(store.get(self.destination/'source')[0], 5)
                queue.start(job)
                wait_for(lambda: not queue.active_jobs)
                queue.clear_finished()
                queue.close()
                (self.destination/'source').rename(self.source)



    def test_interrupted_cancel_finishes_cleanup_without_resuming_copy(self):
        script = r'''import os,sys
from pathlib import Path
from unittest.mock import patch
from omarchy_file_picker.transfers import TransferEngine,TransferJob,Interrupted
from omarchy_file_picker.transfer_journal import TransferJournal
root=Path(sys.argv[1]); journal=TransferJournal(root/'state')
job=TransferJob([root/'source'],root/'destination'); job.on_checkpoint=journal.save
class Partial(TransferEngine):
    def _write(self,fd,data):
        super()._write(fd,data)
        raise Interrupted()
try: Partial().run(job)
except Interrupted: pass
job.state='cancelling'; job.cancel_requested=True; job.recovery_operation='cancel'
journal.save(job)
unlink=os.unlink
def crash_unlink(name,**kwargs):
    unlink(name,**kwargs)
    if str(name)=='0': os._exit(37)
with patch('omarchy_file_picker.transfers.os.unlink',side_effect=crash_unlink):
    TransferEngine().cleanup(job)
raise RuntimeError('Crash point not reached')
'''
        result = subprocess.run([sys.executable, '-c', script, str(self.root)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 37, result.stderr)
        queue = self.queue()
        job, = queue.jobs
        self.assertEqual(job.state, 'paused')
        self.assertTrue(job.cancel_requested)
        self.assertIn('cancellation', job.phase)
        queue.start(job)
        wait_for(lambda: not queue.active_jobs)
        self.assertEqual(job.state, 'cancelled', job.error)
        self.assertTrue(self.source.exists())
        self.assertEqual(list(self.destination.iterdir()), [])

    def test_annotation_receipt_without_existing_database_does_not_move_future_ratings(self):
        from omarchy_file_picker.ratings import RatingStore, EMPTY
        store = RatingStore(self.root/'new-ratings.sqlite3')
        target = self.destination/self.source.name
        mapping = {self.source: target}
        store.move(mapping, receipt='finished-move')
        store.set_many([self.source], stars=2)
        store.move(mapping, receipt='finished-move')
        store.refresh([self.source, target])
        self.assertEqual(store.get(self.source)[0], 2)
        self.assertEqual(store.get(target), EMPTY)

    def test_recovered_annotation_events_keep_actual_completion_order(self):
        from omarchy_file_picker.ratings import RatingStore
        first = TransferJob([self.source], self.destination, True, id='f'*32)
        middle = self.destination/'source'
        final = self.root/'final'
        final.mkdir()
        second = TransferJob([middle], final, True, id='a'*32)
        journal = TransferJournal(self.state)
        store = RatingStore(self.root/'ratings.sqlite3')
        store.set_many([self.source], stars=3)
        for job in [first, second]:
            job.on_checkpoint = journal.save
            TransferEngine().run(job)
        # Restart replans the unfinished subset and discards Item manifests.
        # Historical completion ordering must survive independently of them.
        TransferEngine().restart(second)
        second.persist()
        journal.close()
        queue = self.queue()
        events = queue.completed_events()
        self.assertEqual([job.id for job, _, _ in events], [first.id, second.id])
        for job, source, target in events:
            store.move({source: target}, receipt=job.id)
        store.refresh([final/'source'])
        self.assertEqual(store.get(final/'source')[0], 3)


if __name__ == '__main__':
    unittest.main()
