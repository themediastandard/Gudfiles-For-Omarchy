import unittest
from pathlib import Path

from omarchy_file_picker.file_manager import path_for_show_request


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


if __name__ == '__main__':
    unittest.main()
