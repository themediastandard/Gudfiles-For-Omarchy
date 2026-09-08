from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gi.repository import Gio, GLib
from omarchy_file_picker.file_actions import (
    RemovalError, TrashUnavailable, delete_after_trash_failure, remove_items,
)


def io_error(code):
    return GLib.Error.new_literal(Gio.io_error_quark(), code.value_nick, code)


class TrashTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.paths = [self.root / name for name in ('first.txt', 'second.txt', 'third.txt')]
        for path in self.paths:
            path.write_text(path.name)

    def unsupported(self, paths):
        with patch.object(Gio.File, 'trash', side_effect=io_error(Gio.IOErrorEnum.NOT_SUPPORTED)):
            with self.assertRaises(TrashUnavailable) as caught:
                remove_items(paths)
        return caught.exception

    def test_unsupported_trash_preserves_files_until_explicit_delete(self):
        failure = self.unsupported(self.paths)
        self.assertEqual(failure.completed, ())
        self.assertEqual(failure.remaining, tuple(self.paths))
        self.assertTrue(all(path.exists() for path in self.paths))
        delete_after_trash_failure(failure)
        self.assertFalse(any(path.exists() for path in self.paths))

    def test_mixed_locations_offer_only_unsupported_items(self):
        index = iter(range(3))
        def trash(_cancellable):
            i = next(index)
            if i != 1:
                raise io_error(Gio.IOErrorEnum.NOT_SUPPORTED)
            self.paths[i].unlink()  # disposable stand-in for a successful Trash
            return True
        with patch.object(Gio.File, 'trash', side_effect=trash):
            with self.assertRaises(TrashUnavailable) as caught:
                remove_items(self.paths)
        failure = caught.exception
        self.assertEqual(failure.completed, (self.paths[1],))
        self.assertEqual(failure.remaining, (self.paths[0], self.paths[2]))
        # A file recreated at the successfully trashed path must not be deleted
        # by the separate confirmation for unsupported items.
        self.paths[1].write_text('new unrelated file')
        delete_after_trash_failure(failure)
        self.assertEqual(self.paths[1].read_text(), 'new unrelated file')

    def test_permission_io_and_readonly_errors_never_offer_delete(self):
        for code in (Gio.IOErrorEnum.PERMISSION_DENIED, Gio.IOErrorEnum.FAILED,
                     Gio.IOErrorEnum.READ_ONLY, Gio.IOErrorEnum.NOT_FOUND):
            with self.subTest(code=code), patch.object(Gio.File, 'trash', side_effect=io_error(code)) as trash:
                with self.assertRaises(RemovalError) as caught:
                    remove_items(self.paths)
                self.assertNotIsInstance(caught.exception, TrashUnavailable)
                self.assertEqual(caught.exception.remaining, tuple(self.paths))
                self.assertEqual(trash.call_count, 1)
                self.assertTrue(all(path.exists() for path in self.paths))

    def test_partial_failure_records_completed_and_unattempted_paths(self):
        def trash(_cancellable):
            if self.paths[0].exists():
                self.paths[0].unlink()
                return True
            raise io_error(Gio.IOErrorEnum.PERMISSION_DENIED)
        with patch.object(Gio.File, 'trash', side_effect=trash):
            with self.assertRaises(RemovalError) as caught:
                remove_items(self.paths)
        self.assertEqual(caught.exception.completed, (self.paths[0],))
        self.assertEqual(caught.exception.remaining, tuple(self.paths[1:]))

    def test_changed_file_rejects_whole_delete_confirmation(self):
        failure = self.unsupported(self.paths)
        self.paths[-1].write_text('changed contents')
        with self.assertRaisesRegex(ValueError, 'changed'):
            delete_after_trash_failure(failure)
        self.assertTrue(all(path.exists() for path in self.paths))

    def test_replaced_symlink_rejects_delete_and_preserves_target(self):
        failure = self.unsupported([self.paths[0]])
        self.paths[0].unlink()
        self.paths[0].symlink_to(self.paths[1])
        with self.assertRaisesRegex(ValueError, 'changed'):
            delete_after_trash_failure(failure)
        self.assertTrue(self.paths[0].is_symlink())
        self.assertEqual(self.paths[1].read_text(), 'second.txt')

    def test_unsupported_symlink_delete_does_not_follow_target(self):
        link = self.root / 'link'
        link.symlink_to(self.paths[0])
        delete_after_trash_failure(self.unsupported([link]))
        self.assertFalse(link.is_symlink())
        self.assertEqual(self.paths[0].read_text(), 'first.txt')

    def test_delete_failure_has_no_trash_fallback(self):
        with patch.object(Path, 'unlink', side_effect=PermissionError('denied')):
            with self.assertRaises(RemovalError) as caught:
                remove_items(self.paths, permanent=True)
        self.assertNotIsInstance(caught.exception, TrashUnavailable)
        self.assertEqual(caught.exception.completed, ())
        self.assertEqual(caught.exception.remaining, tuple(self.paths))

    def test_false_trash_receipt_is_a_failure(self):
        with patch.object(Gio.File, 'trash', return_value=False):
            with self.assertRaises(RemovalError) as caught:
                remove_items(self.paths)
        self.assertNotIsInstance(caught.exception, TrashUnavailable)
        self.assertEqual(caught.exception.completed, ())
        self.assertTrue(all(path.exists() for path in self.paths))


if __name__ == '__main__':
    unittest.main()
