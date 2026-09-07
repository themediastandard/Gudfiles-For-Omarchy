from pathlib import Path
from types import SimpleNamespace
import stat
import tempfile
import unittest
from unittest.mock import Mock

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from omarchy_file_picker.selection_summary import selection_totals


class SelectionTotalsTests(unittest.TestCase):
    def test_combines_files_without_folder_contents(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first, second, empty = root / 'a', root / 'b', root / 'empty'
            first.write_bytes(b'a' * 1024)
            second.write_bytes(b'b' * 2048)
            empty.touch()
            folder = root / 'folder'
            folder.mkdir()
            (folder / 'excluded').write_bytes(b'c' * 4096)
            self.assertEqual(selection_totals([first, second, empty, folder]), (1, 3, 3072, 0))
            self.assertEqual(selection_totals([empty, empty]), (0, 2, 0, 0))
            self.assertEqual(selection_totals([folder]), (1, 0, 0, 0))
            self.assertEqual(selection_totals([]), (0, 0, 0, 0))

    def test_unavailable_does_not_look_like_a_complete_total(self):
        known = Mock()
        known.stat.return_value = SimpleNamespace(st_mode=stat.S_IFREG, st_size=512)
        missing, denied = Mock(), Mock()
        missing.stat.side_effect = FileNotFoundError()
        denied.stat.side_effect = PermissionError()
        self.assertEqual(selection_totals([known, missing, denied]), (0, 3, 512, 2))

    def test_special_files_are_not_counted_as_normal_payload(self):
        pipe = Mock()
        pipe.stat.return_value = SimpleNamespace(st_mode=stat.S_IFIFO, st_size=999)
        self.assertEqual(selection_totals([pipe]), (0, 1, 0, 1))
