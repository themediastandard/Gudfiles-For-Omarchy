import unittest
from pathlib import Path

from omarchy_file_picker.file_manager import path_for_show_request, show_request_commands


class FileManagerRequestTests(unittest.TestCase):
    def test_show_item_keeps_the_file_target_for_gudfiles(self):
        target = path_for_show_request([
            'file:///home/tommy/Videos/clip.mp4',
            'https://example.com/not-local.mp4',
        ])
        self.assertEqual(target, Path('/home/tommy/Videos/clip.mp4'))

    def test_show_folder_accepts_escaped_local_uri(self):
        target = path_for_show_request(['file:///home/tommy/My%20Videos'])
        self.assertEqual(target, Path('/home/tommy/My Videos'))

    def test_nonlocal_and_empty_requests_are_ignored(self):
        self.assertIsNone(path_for_show_request([]))
        self.assertIsNone(path_for_show_request(['https://example.com/video.mp4']))

    def test_show_items_groups_siblings_and_retains_folder_items(self):
        self.assertEqual(show_request_commands('gudfiles', 'ShowItems', [
            'file:///tmp/a/one%20file.txt', 'file:///tmp/a/folder',
            'file:///tmp/b/two.txt', 'file:///tmp/a/folder',
        ]), [
            ['gudfiles', '--external', '--demo', '/tmp/a', '--multiple',
             '--select', '/tmp/a/one file.txt', '--select', '/tmp/a/folder'],
            ['gudfiles', '--external', '--demo', '/tmp/b', '--multiple', '--select', '/tmp/b/two.txt'],
        ])

    def test_show_folders_enters_the_folder_in_an_external_window(self):
        self.assertEqual(show_request_commands('gudfiles', 'ShowFolders', ['file:///tmp/a']),
                         [['gudfiles', '--external', '--demo', '/tmp/a', '--multiple']])

    def test_remote_relative_and_invalid_uris_are_ignored(self):
        self.assertEqual(show_request_commands('gudfiles', 'ShowItems', [
            'file://server/tmp/file', 'file:relative', 'file:///tmp/bad%00name',
        ]), [])


if __name__ == '__main__':
    unittest.main()
