import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gio, GLib

from omarchy_file_picker.folder_watch import FolderWatch


def settle(ms=550):
    loop = GLib.MainLoop()
    GLib.timeout_add(ms, lambda: loop.quit() or False)
    loop.run()


class FolderWatchTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.owner = SimpleNamespace(current_dir=self.root, special_mode=None,
            view_mode='list', show_hidden=False, tabs=SimpleNamespace(generation=0),
            path_stack=SimpleNamespace(get_visible_child_name=lambda: 'crumbs'),
            _computer_search_active=lambda: False, connect=Mock())
        self.watch = FolderWatch(self.owner)
        self.watch._busy = lambda: False
        self.watch._refresh_standard = Mock()

    def tearDown(self):
        self.watch.close()
        self.directory.cleanup()

    def test_native_changes_are_coalesced_and_hidden_noise_is_ignored(self):
        for index in range(30):
            (self.root / str(index)).write_text('external change')
        settle()
        self.watch._refresh_standard.assert_called_once()
        (self.root / '.hidden').write_text('hidden')
        settle()
        self.watch._refresh_standard.assert_called_once()
        (self.root / '.hidden').rename(self.root / 'visible')
        settle()
        self.assertEqual(self.watch._refresh_standard.call_count, 2)

    def test_pending_changes_wait_for_interaction_and_navigation_invalidates(self):
        self.watch._busy = lambda: True
        (self.root / 'old').touch()
        settle()
        self.watch._refresh_standard.assert_not_called()
        self.watch._busy = lambda: False
        settle()
        self.watch._refresh_standard.assert_called_once()
        (self.root / 'new').touch()
        settle(50)
        other = self.root / 'next'
        other.mkdir()
        self.owner.current_dir = other
        self.watch.sync()
        settle()
        self.watch._refresh_standard.assert_called_once()
        self.assertEqual(set(self.watch.monitors), {other})

    def test_close_and_special_locations_cancel_monitor_callbacks(self):
        monitor = next(iter(self.watch.monitors.values()))
        self.owner.special_mode = 'recent'
        self.watch.sync()
        self.assertTrue(monitor.is_cancelled())
        self.assertFalse(self.watch.monitors)
        self.owner.special_mode = None
        self.watch.sync()
        (self.root / 'pending').touch()
        settle(50)
        self.watch.close()
        settle()
        self.watch._refresh_standard.assert_not_called()
        self.assertFalse(self.watch.timer)

    def test_deleted_directory_is_monitored_again_when_recreated(self):
        self.root.rmdir()
        settle()
        self.assertIn(self.root, self.watch.missing)
        self.watch._refresh_standard.assert_called_once()
        self.root.mkdir()
        settle(1800)
        self.assertIn(self.root, self.watch.monitors)
        self.assertFalse(self.watch.missing)
        self.assertEqual(self.watch._refresh_standard.call_count, 2)
        (self.root / 'after-reconnect').touch()
        settle()
        self.assertEqual(self.watch._refresh_standard.call_count, 3)

    def test_slow_reconnect_query_is_bounded_cancelled_and_scoped(self):
        monitor = self.watch.monitors.pop(self.root)
        monitor.cancel()
        self.watch.missing.add(self.root)
        file = Mock()
        file.query_info_finish.return_value = SimpleNamespace(get_file_type=lambda: Gio.FileType.DIRECTORY)
        with patch.object(Gio.File, 'new_for_path', return_value=file):
            self.watch._retry_missing()
            self.watch._retry_missing()
            file.query_info_async.assert_called_once()
            args = file.query_info_async.call_args.args
            callback, data = args[-2:]
            probe = self.watch.probes[self.root]
            # Simulate the deadline without waiting four wall-clock seconds.
            GLib.source_remove(probe['deadline'])
            self.watch._timeout_probe(self.root, probe)
            self.assertTrue(probe['cancel'].is_cancelled())
            self.watch._retry_missing()
            file.query_info_async.assert_called_once()
            # A late successful result cannot treat timeout as reconnection.
            callback(file, None, data)
            self.assertIn(self.root, self.watch.missing)
            self.assertFalse(self.watch.pending)
            self.watch._retry_missing()
            self.assertEqual(file.query_info_async.call_count, 2)
            callback, data = file.query_info_async.call_args.args[-2:]
        self.owner.special_mode = 'recent'
        self.watch.sync()
        self.assertTrue(data[1]['cancel'].is_cancelled())
        self.assertFalse(self.watch.probes)
        callback(file, None, data)
        self.assertFalse(self.watch.pending)
        self.watch._refresh_standard.assert_not_called()

    def test_close_cancels_unresponsive_reconnect_query(self):
        self.watch.missing.add(self.root)
        file = Mock()
        file.query_info_finish.return_value = SimpleNamespace(get_file_type=lambda: Gio.FileType.DIRECTORY)
        with patch.object(Gio.File, 'new_for_path', return_value=file):
            self.watch._retry_missing()
        callback, data = file.query_info_async.call_args.args[-2:]
        self.watch.close()
        self.assertTrue(data[1]['cancel'].is_cancelled())
        callback(file, None, data)
        self.assertFalse(self.watch.probes)
        self.assertFalse(self.watch.pending)
        self.assertFalse(self.watch.timer)


if __name__ == '__main__':
    unittest.main()
