import tempfile
import unittest
from pathlib import Path

from gi.repository import GLib
from omarchy_file_picker.file_actions import (
    parse_file_clipboard, remove_items, rename_item, sort_entries, transfer_items,
)


class FileActionsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_rename_and_collision_preserve_existing_content(self):
        a, b = self.root / 'a.txt', self.root / 'b.txt'
        a.write_text('first')
        b.write_text('second')
        with self.assertRaises(GLib.Error): rename_item(a, b.name)
        self.assertEqual(b.read_text(), 'second')
        target = rename_item(a, 'new.txt')
        self.assertEqual(target.read_text(), 'first')
        self.assertFalse(a.exists())
        with self.assertRaises(ValueError): rename_item(target, '../escape.txt')

    def test_copy_folder_keeps_symlinks_and_original(self):
        source = self.root / 'folder'
        source.mkdir()
        (source / 'data.txt').write_text('data')
        (source / 'link').symlink_to('data.txt')
        dest = self.root / 'destination'
        dest.mkdir()
        result = transfer_items([source], dest)
        self.assertEqual((result[0] / 'data.txt').read_text(), 'data')
        self.assertTrue((result[0] / 'link').is_symlink())
        self.assertTrue(source.exists())
        with self.assertRaises(FileExistsError): transfer_items([source], dest)

    def test_move_and_paste_inside_self(self):
        source = self.root / 'folder'
        source.mkdir()
        nested = source / 'nested'
        nested.mkdir()
        with self.assertRaises(ValueError): transfer_items([source], nested)
        dest = self.root / 'destination'
        dest.mkdir()
        transfer_items([source], dest, cut=True)
        self.assertFalse(source.exists())
        self.assertTrue((dest / 'folder/nested').is_dir())

    def test_delete_symlink_does_not_follow_target(self):
        target = self.root / 'target'
        target.mkdir()
        (target / 'keep.txt').write_text('keep')
        link = self.root / 'link'
        link.symlink_to(target)
        remove_items([link], permanent=True)
        self.assertEqual((target / 'keep.txt').read_text(), 'keep')
        self.assertFalse(link.is_symlink())

    def test_file_clipboard_uri_decoding(self):
        paths, cut = parse_file_clipboard('cut\nfile:///tmp/my%20file.txt\nhttps://example.com',
                                          'x-special/gnome-copied-files')
        self.assertTrue(cut)
        self.assertEqual(paths, [Path('/tmp/my file.txt')])

    def test_sort_order_and_folder_grouping(self):
        folder = self.root / 'z-dir'
        folder.mkdir()
        small, large = self.root / 'a', self.root / 'b'
        small.write_text('a')
        large.write_text('abcdef')
        self.assertEqual(sort_entries([small, folder, large], 'size', True, True),
                         [folder, large, small])
