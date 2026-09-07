import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from omarchy_file_picker.batch_rename import RenameOptions, execute_rename, plan_rename, _rename_no_replace


class BatchRenameTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.paths = [self.root / 'CAM_B.MOV', self.root / 'CAM_A.MOV']
        for index, path in enumerate(self.paths):
            path.write_text(str(index))

    def test_preserve_order_extensions_and_contents(self):
        plan = plan_rename(self.paths, RenameOptions(pattern='Project_{n}', start=7, padding=4))
        self.assertEqual([i.target.name for i in plan], ['Project_0007.MOV', 'Project_0008.MOV'])
        result = execute_rename(plan)
        self.assertIsNone(result.error)
        self.assertEqual(len(result.completed), 2)
        self.assertEqual([p.read_text() for p in result.completed.values()], ['0', '1'])

    def test_date_and_name_tokens(self):
        plan = plan_rename(self.paths, RenameOptions(pattern='{date}_{name}_{n}'))
        self.assertRegex(plan[0].target.name, r'^\d{4}-\d{2}-\d{2}_CAM_B_001.MOV$')

    def test_replace_excludes_extension(self):
        plan = plan_rename(self.paths, RenameOptions(mode='replace', find='CAM', replace='Interview'))
        self.assertEqual(plan[0].target.name, 'Interview_B.MOV')
        unchanged = plan_rename(self.paths, RenameOptions(mode='replace', find='MOV', replace='mp4'))
        self.assertTrue(all(i.source == i.target for i in unchanged))

    def test_duplicate_and_existing_targets_prevent_whole_batch(self):
        with self.assertRaises(ValueError):
            plan_rename(self.paths, RenameOptions(pattern='same'))
        existing = self.root / 'Project_002.MOV'
        existing.write_text('must survive')
        with self.assertRaises(FileExistsError):
            plan_rename(self.paths, RenameOptions(pattern='Project_{n}'))
        self.assertEqual(existing.read_text(), 'must survive')
        self.assertTrue(all(p.exists() for p in self.paths))

    def test_invalid_tokens_and_names(self):
        for pattern in ('{camera}', '{name.__class__}', '{n:>3}', '{name!r}', '{', '/', '', '..', '\0'):
            with self.subTest(pattern=pattern), self.assertRaises(ValueError):
                plan_rename(self.paths, RenameOptions(pattern=pattern))

    def test_directory_and_dangling_symlink_are_renamed_not_followed(self):
        folder = self.root / 'assets.v1'
        folder.mkdir()
        (folder / 'inside').write_text('safe')
        link = self.root / 'missing.png'
        link.symlink_to('does-not-exist')
        result = execute_rename(plan_rename([folder, link], RenameOptions(pattern='{name}_{n}')))
        self.assertIsNone(result.error)
        self.assertEqual((self.root / 'assets.v1_001/inside').read_text(), 'safe')
        self.assertTrue((self.root / 'missing_002.png').is_symlink())
        self.assertEqual(os.readlink(self.root / 'missing_002.png'), 'does-not-exist')

    def test_dangling_destination_collision(self):
        (self.root / 'CAM_B_001.MOV').symlink_to('missing')
        with self.assertRaises(FileExistsError):
            plan_rename(self.paths, RenameOptions())

    def test_parent_child_batch_rejected(self):
        with self.assertRaises(ValueError):
            plan_rename([self.root, self.paths[0]], RenameOptions())

    def test_source_changed_after_preview(self):
        plan = plan_rename(self.paths, RenameOptions())
        replacement = self.root / 'replacement'
        replacement.write_text('new')
        replacement.replace(self.paths[0])
        result = execute_rename(plan)
        self.assertIsNotNone(result.error)
        self.assertFalse(result.completed)

    def test_racing_destination_never_overwritten_partial_result_retained(self):
        plan = plan_rename(self.paths, RenameOptions())
        def race(source, target):
            if source == self.paths[1]:
                target.write_text('racing file')
            _rename_no_replace(source, target)
        with patch('omarchy_file_picker.batch_rename._rename_no_replace', side_effect=race):
            result = execute_rename(plan)
        self.assertEqual(result.completed, {self.paths[0]: plan[0].target})
        self.assertIsNotNone(result.error)
        self.assertEqual(plan[1].target.read_text(), 'racing file')
        self.assertEqual(self.paths[1].read_text(), '1')

    def test_cancellation_keeps_every_original(self):
        cancel = threading.Event()
        cancel.set()
        result = execute_rename(plan_rename(self.paths, RenameOptions()), cancel)
        self.assertTrue(result.cancelled)
        self.assertFalse(result.completed)
        self.assertTrue(all(p.exists() for p in self.paths))

    def test_cancellation_after_first_item_reports_partial_mapping(self):
        cancel = threading.Event()
        plan = plan_rename(self.paths, RenameOptions())
        def stop_after_first(source, target):
            _rename_no_replace(source, target)
            cancel.set()
        with patch('omarchy_file_picker.batch_rename._rename_no_replace', side_effect=stop_after_first):
            result = execute_rename(plan, cancel)
        self.assertTrue(result.cancelled)
        self.assertEqual(result.completed, {self.paths[0]: plan[0].target})
        self.assertEqual(self.paths[1].read_text(), '1')


if __name__ == '__main__':
    unittest.main()
