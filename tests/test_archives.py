import errno
from pathlib import Path
import stat
import struct
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

from omarchy_file_picker.archives import extract_zip
from omarchy_file_picker.batch_rename import _rename_no_replace


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'Camera files.ZIP'

    def archive(self, entries):
        with warnings.catch_warnings(), zipfile.ZipFile(self.source, 'w', zipfile.ZIP_DEFLATED) as archive:
            warnings.simplefilter('ignore', UserWarning)
            for name, data in entries:
                archive.writestr(name, data)
        return self.source.read_bytes()

    def assert_clean_failure(self, error=Exception):
        original = self.source.read_bytes()
        with self.assertRaises(error):
            extract_zip(self.source)
        self.assertEqual(list(self.root.iterdir()), [self.source])
        self.assertEqual(self.source.read_bytes(), original)

    def test_nested_unicode_empty_directories_and_original(self):
        original = self.archive([('a.txt', 'a'), ('Footage/é.txt', 'media'), ('Empty/', ''), ('zero', '')])
        result = extract_zip(self.source)
        self.assertEqual(result, self.root / 'Camera files')
        self.assertEqual((result / 'Footage/é.txt').read_text(), 'media')
        self.assertEqual((result / 'zero').read_bytes(), b'')
        self.assertTrue((result / 'Empty').is_dir())
        self.assertEqual(self.source.read_bytes(), original)
        self.assertFalse(list(self.root.glob('.gudfiles-extract-*')))

    def test_empty_zip_creates_empty_folder(self):
        self.archive([])
        self.assertEqual(list(extract_zip(self.source).iterdir()), [])

    def test_collisions_skip_files_folders_and_dangling_links(self):
        self.archive([('a.txt', 'a')])
        (self.root / 'Camera files').write_text('keep')
        (self.root / 'Camera files (1)').mkdir()
        (self.root / 'Camera files (2)').symlink_to('missing')
        self.assertEqual(extract_zip(self.source).name, 'Camera files (3)')
        self.assertEqual(extract_zip(self.source).name, 'Camera files (4)')
        self.assertEqual((self.root / 'Camera files').read_text(), 'keep')
        self.assertTrue((self.root / 'Camera files (2)').is_symlink())

    def test_destination_race_preserves_other_output(self):
        self.archive([('a.txt', 'a')])
        def race(source, target):
            if target.name == 'Camera files':
                target.mkdir()
                (target / 'keep').write_text('other process')
            return _rename_no_replace(source, target)
        with patch('omarchy_file_picker.archives._rename_no_replace', side_effect=race):
            self.assertEqual(extract_zip(self.source).name, 'Camera files (1)')
        self.assertEqual((self.root / 'Camera files/keep').read_text(), 'other process')

    def test_traversal_absolute_and_windows_paths_rejected(self):
        for name in ('../escape', 'folder/../../escape', '/absolute', 'C:/drive', 'C:drive', r'..\escape'):
            with self.subTest(name=name):
                self.archive([(name, 'bad')])
                self.assert_clean_failure(ValueError)

    def test_symlinks_and_special_files_rejected(self):
        for mode in (stat.S_IFLNK, stat.S_IFIFO, stat.S_IFSOCK, stat.S_IFCHR, stat.S_IFBLK):
            with self.subTest(mode=mode):
                info = zipfile.ZipInfo('link')
                info.create_system = 3
                info.external_attr = (mode | 0o777) << 16
                self.archive([(info, '../escape')])
                self.assert_clean_failure(ValueError)

    def test_duplicate_or_conflicting_entries_leave_no_partial_folder(self):
        for entries in ([('file', 'a'), ('file', 'b')], [('file', 'a'), ('file/child', 'b')]):
            with self.subTest(entries=entries):
                self.archive(entries)
                self.assert_clean_failure(OSError)

    def test_bad_zip_and_crc_failure_leave_no_partial_folder(self):
        self.source.write_text('not a ZIP')
        self.assert_clean_failure(zipfile.BadZipFile)
        data = bytearray(self.archive([('good', 'good'), ('bad', 'bad')]))
        central = data.rindex(b'PK\x01\x02')
        struct.pack_into('<I', data, central + 16, 0)
        self.source.write_bytes(data)
        self.assert_clean_failure(zipfile.BadZipFile)

    def test_encrypted_zip_reports_unsupported(self):
        data = bytearray(self.archive([('secret', 'data')]))
        central = data.index(b'PK\x01\x02')
        struct.pack_into('<H', data, central + 8, 1)
        self.source.write_bytes(data)
        self.assert_clean_failure(ValueError)

    def test_disk_and_publication_errors_clean_up(self):
        self.archive([('file', 'contents')])
        with patch('omarchy_file_picker.archives.shutil.copyfileobj', side_effect=OSError(errno.ENOSPC, 'Disk full')):
            self.assert_clean_failure(OSError)
        with patch('omarchy_file_picker.archives._rename_no_replace', side_effect=OSError(errno.ENOTSUP, 'Unsupported')):
            self.assert_clean_failure(OSError)

    def test_entry_limit_leaves_no_partial_folder(self):
        self.archive([('a', 'a'), ('b', 'b')])
        with patch('omarchy_file_picker.archives.MAX_ENTRIES', 1):
            self.assert_clean_failure(ValueError)

    def test_dot_directory_entries_and_explicit_parent_after_child(self):
        self.archive([('./', ''), ('./dir/file', 'content'), ('dir/', '')])
        result = extract_zip(self.source)
        self.assertEqual((result / 'dir/file').read_text(), 'content')


if __name__ == '__main__':
    unittest.main()
