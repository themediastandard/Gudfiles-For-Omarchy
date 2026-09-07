import json
from pathlib import Path
import tempfile
import unittest

from omarchy_file_picker.picker import parse_args


class SelectionDefaultsTests(unittest.TestCase):
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
                parsed = parse_args(['--request', str(request), '--multiple'])[0]
                self.assertEqual(parsed.multiple, multiple)
                self.assertFalse(parsed.explorer)
