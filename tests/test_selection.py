import json
from pathlib import Path
import tempfile
import unittest

from omarchy_file_picker.picker import application_id_for, parse_args


class SelectionDefaultsTests(unittest.TestCase):
    def test_file_launch_selects_the_item_and_uses_external_window_class(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'clip.mp4'
            path.touch()
            request = parse_args(['--demo', str(path)])[0]
            self.assertEqual(request.current_folder, path.parent)
            self.assertEqual(request.selected_paths, [path])
            self.assertEqual(application_id_for(request), 'org.omarchy.FilePicker.External')

    def test_explicit_reveal_selects_a_folder_in_its_parent(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'folder'
            path.mkdir()
            request = parse_args(['--select', str(path)])[0]
            self.assertEqual(request.current_folder, path.parent)
            self.assertEqual(request.selected_paths, [path])
            self.assertTrue(request.external)
            ordinary = parse_args(['--demo', str(path)])[0]
            self.assertFalse(ordinary.external)
            self.assertEqual(ordinary.current_folder, path)
            self.assertEqual(application_id_for(parse_args(['--external', '--demo', str(path)])[0]),
                             'org.omarchy.FilePicker.External')

    def test_reveal_preserves_symlink_entry_and_missing_filename(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / 'target.txt'
            target.touch()
            link = root / 'link.txt'
            link.symlink_to(target)
            for path in (link, root / 'missing.txt'):
                request = parse_args(['--demo', str(path)])[0]
                self.assertEqual(request.selected_paths, [path])

    def test_picker_and_explorer_have_distinct_window_classes(self):
        self.assertEqual(application_id_for(parse_args([])[0]), 'org.omarchy.FilePicker')
        self.assertEqual(application_id_for(parse_args(['--mode', 'save'])[0]),
                         'org.omarchy.FilePicker.Picker')

    def test_explorer_only_for_standalone_browsing(self):
        self.assertTrue(parse_args([])[0].explorer)
        self.assertTrue(parse_args(['--demo'])[0].explorer)
        for args in (['--mode', 'save'], ['--mode', 'save_files'], ['--directory'], ['--result', '/tmp/result.json']):
            self.assertFalse(parse_args(args)[0].explorer)

    def test_standalone_open_defaults_to_multiple(self):
        self.assertTrue(parse_args([])[0].multiple)
        self.assertTrue(parse_args(['--demo'])[0].multiple)
        self.assertTrue(parse_args(['--demo', '--multiple'])[0].multiple)
        self.assertFalse(parse_args(['--demo', '--single'])[0].multiple)

    def test_save_is_single_destination(self):
        self.assertFalse(parse_args(['--mode', 'save'])[0].multiple)
        self.assertFalse(parse_args(['--mode', 'save_files', '--multiple'])[0].multiple)

    def test_portal_request_is_authoritative(self):
        with tempfile.TemporaryDirectory() as temp:
            request = Path(temp) / 'request.json'
            for multiple in (False, True):
                request.write_text(json.dumps({'multiple': multiple, 'current_folder': temp}))
                parsed = parse_args(['--request', str(request), '--multiple', '--external', '--select', '/tmp/file'])[0]
                self.assertEqual(parsed.multiple, multiple)
                self.assertFalse(parsed.explorer)
                self.assertFalse(parsed.external)
                self.assertEqual(parsed.selected_paths, [])
