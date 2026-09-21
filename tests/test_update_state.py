import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from omarchy_file_picker import updates, update_state


def available(version='2.0.0'):
    return updates.UpdateResult('available', f'Gudfiles {version} is available.',
                                f'{updates.releases_url()}/tag/v{version}')


class UpdateHistory(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = 1000000
        self.state = update_state.UpdateState(self.temp.name, clock=lambda: self.now)

    def test_cache_retry_force_clock_and_installed_version(self):
        with patch.object(updates, 'check_for_updates', return_value=available()) as check:
            self.assertEqual(self.state.check().status, 'available')
            other = update_state.UpdateState(self.temp.name, clock=lambda: self.now)
            self.assertEqual(other.check().status, 'available')
            self.assertEqual(check.call_count, 1)
            self.state.check(force=True)
            self.assertEqual(check.call_count, 2)
            self.now += update_state.DAY
            self.state.check()
            self.assertEqual(check.call_count, 3)
            self.now -= 10  # Future timestamps are never fresh after clock rollback.
            self.state.check()
            self.assertEqual(check.call_count, 4)
            with patch.object(update_state, '__version__', '1.0.0'):
                self.state.check()
            self.assertEqual(check.call_count, 5)
            check.return_value = updates.UpdateResult('error', 'Offline')
            self.state.check(force=True)
            self.now += update_state.RETRY - 1
            self.assertEqual(self.state.check().status, 'error')
            self.assertEqual(check.call_count, 6)
            self.now += 1
            self.state.check()
            self.assertEqual(check.call_count, 7)

    def test_cross_window_claim_dismissal_new_version_and_channel(self):
        result = available()
        self.assertTrue(self.state.claim_notice(result))
        other = update_state.UpdateState(self.temp.name, clock=lambda: self.now)
        self.assertFalse(other.claim_notice(result))
        self.now += update_state.DAY
        self.assertTrue(other.claim_notice(result))
        other.dismiss(result)
        self.now += update_state.DAY
        self.assertFalse(self.state.claim_notice(result))
        self.assertTrue(self.state.claim_notice(available('2.0.1')))
        with patch.object(updates, 'repository', return_value='another/channel'):
            self.assertTrue(self.state.claim_notice(available()))
        self.assertFalse(self.state.claim_notice(updates.UpdateResult('available', 'bad', 'https://evil.test')))

    def test_corrupt_readonly_and_concurrent_state(self):
        Path(self.temp.name, 'state.json').write_text('broken')
        with patch.object(updates, 'check_for_updates', return_value=available()) as check:
            self.assertEqual(self.state.check().status, 'available')
            with self.state.locked('check.lock'):
                self.assertEqual(self.state.check(force=True).status, 'busy')
                self.state.dismiss(available())
            self.assertFalse(self.state.claim_notice(available()))
            self.assertEqual(check.call_count, 1)
            with patch.object(self.state, 'write', side_effect=PermissionError):
                self.assertEqual(self.state.check(force=True).status, 'error')
                self.assertFalse(self.state.claim_notice(available()))
                self.state.dismiss(available())

    def test_malformed_cache_and_checker_failure_recover(self):
        with patch.object(updates, 'check_for_updates', return_value=available()) as check:
            for result in ({'status': 'available', 'message': 3, 'url': available().url},
                           {'status': 'current', 'message': 'bad', 'url': 'https://evil.test'},
                           {'status': 'unexpected', 'message': 'bad', 'url': ''}):
                self.state.write({'repository': updates.repository(), 'installed': update_state.__version__,
                                  'checked': self.now, 'result': result})
                self.assertEqual(self.state.check(), available())
            self.assertEqual(check.call_count, 3)
        with patch.object(updates, 'check_for_updates', side_effect=RuntimeError):
            self.assertEqual(self.state.check(force=True).status, 'error')

    def test_deadline_ignores_late_reply_and_allows_retry(self):
        gate = threading.Event()
        finished = threading.Event()
        def late():
            gate.wait(2)
            finished.set()
            return available()
        with patch.object(update_state, 'CHECK_TIMEOUT', .02), patch.object(updates, 'check_for_updates', side_effect=late):
            self.assertEqual(self.state.check().status, 'error')
            gate.set()
            self.assertTrue(finished.wait(1))
        self.assertEqual(json.loads(Path(self.temp.name, 'state.json').read_text())['result']['status'], 'error')
        with patch.object(updates, 'check_for_updates', return_value=available()):
            self.assertEqual(self.state.check(force=True).status, 'available')


if __name__ == '__main__':
    unittest.main()
