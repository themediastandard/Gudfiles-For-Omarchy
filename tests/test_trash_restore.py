import unittest
from unittest.mock import Mock, patch

from omarchy_file_picker.trash import TrashItem, restore_item


class RestoreSafetyTests(unittest.TestCase):
    def setUp(self):
        self.item = TrashItem('trash:///fixture', 'fixture', '/tmp/original', '2026-09-19T12:00:00')
        self.source = Mock()
        self.info = self.source.query_info.return_value
        self.info.get_attribute_byte_string.return_value = self.item.original
        self.info.get_attribute_string.return_value = self.item.deleted
        self.files = patch('omarchy_file_picker.trash.Gio.File.new_for_uri', return_value=self.source)
        self.files.start()
        self.addCleanup(self.files.stop)

    def test_refuses_non_trash_source(self):
        self.source.has_parent.return_value = False
        with self.assertRaisesRegex(ValueError, 'no longer in Trash'):
            restore_item(self.item)
        self.source.move.assert_not_called()

    def test_refuses_replaced_trashed_item(self):
        self.info.get_attribute_string.return_value = '2026-09-19T13:00:00'
        with self.assertRaisesRegex(ValueError, 'changed'):
            restore_item(self.item)
        self.source.move.assert_not_called()

    def test_refuses_missing_and_relative_original(self):
        for original in ('', 'relative/file'):
            with self.subTest(original=original):
                item = TrashItem(self.item.uri, 'fixture', original, self.item.deleted)
                self.info.get_attribute_byte_string.return_value = original
                with self.assertRaisesRegex(ValueError, 'unavailable'):
                    restore_item(item)
        self.source.move.assert_not_called()

    def test_false_move_is_not_reported_as_restored(self):
        self.source.move.return_value = False
        with self.assertRaisesRegex(OSError, 'could not be restored'):
            restore_item(self.item)
