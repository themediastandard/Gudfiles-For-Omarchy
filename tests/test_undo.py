import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from omarchy_file_picker.undo import UndoHistory, capture_receipt


class UndoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.history = UndoHistory()

    def renamed(self, original, target, label='Rename'):
        original.rename(target)
        receipt = capture_receipt({original: target}, label)
        self.assertIsNotNone(receipt)
        self.history.record(receipt)
        return receipt

    def test_rename_then_move_undo_chain(self):
        a, b = self.root / 'a', self.root / 'b'
        destination = self.root / 'destination'
        destination.mkdir()
        a.write_bytes(b'footage')
        self.renamed(a, b)
        self.renamed(b, destination / 'b', 'Move')
        first = self.history.undo()
        self.assertIsNone(first.error)
        self.assertEqual(first.completed, {destination / 'b': b})
        second = self.history.undo()
        self.assertIsNone(second.error)
        self.assertEqual(a.read_bytes(), b'footage')
        self.assertIsNone(self.history.peek())

    def test_collision_never_overwrites_and_retry_succeeds(self):
        a, b = self.root / 'a', self.root / 'b'
        a.write_text('original')
        self.renamed(a, b)
        a.write_text('new file')
        self.assertIn('overwrite', self.history.undo().error)
        self.assertEqual(a.read_text(), 'new file')
        self.assertEqual(b.read_text(), 'original')
        a.unlink()
        self.assertIsNone(self.history.undo().error)

    def test_changed_bytes_same_size_and_mtime_refused(self):
        a, b = self.root / 'a', self.root / 'b'
        a.write_text('one')
        self.renamed(a, b)
        before = b.stat()
        b.write_text('two')
        os.utime(b, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assertIn('changed', self.history.undo().error)
        self.assertEqual(b.read_text(), 'two')
        self.assertFalse(a.exists())

    def test_replaced_file_identity_refused(self):
        a, b, held = self.root / 'a', self.root / 'b', self.root / 'held'
        a.write_text('one')
        self.renamed(a, b)
        b.rename(held)
        b.write_text('one')
        self.assertIn('changed', self.history.undo().error)
        self.assertEqual(held.read_text(), 'one')

    def test_directory_child_modification_and_addition_refused(self):
        for change in ('modify', 'add'):
            with self.subTest(change=change):
                a, b = self.root / ('a'+change), self.root / ('b'+change)
                a.mkdir()
                (a / 'clip').write_text('data')
                self.renamed(a, b)
                (b / ('clip' if change == 'modify' else 'new')).write_text('edit')
                self.assertIn('changed', self.history.undo().error)
                self.assertFalse(a.exists())

    def test_symlink_moves_link_without_touching_target(self):
        actual, a, b = self.root / 'actual', self.root / 'a', self.root / 'b'
        actual.write_text('real')
        a.symlink_to(actual)
        self.renamed(a, b)
        self.assertIsNone(self.history.undo().error)
        self.assertTrue(a.is_symlink())
        self.assertEqual(actual.read_text(), 'real')

    def test_parent_replacement_refused(self):
        source, target = self.root / 'source', self.root / 'target'
        source.mkdir(); target.mkdir()
        a, b = source / 'a', target / 'a'
        a.write_text('data')
        self.renamed(a, b)
        source.rename(self.root / 'oldsource')
        source.mkdir()
        self.assertIn('folder changed', self.history.undo().error)
        self.assertTrue(b.exists())

    def test_batch_preflight_and_partial_failure_receipts(self):
        mapping = {}
        for name in ('a', 'b'):
            original, target = self.root / name, self.root / (name + '-new')
            original.write_text(name)
            original.rename(target)
            mapping[original] = target
        self.history.record(capture_receipt(mapping, 'Batch Rename'))
        from omarchy_file_picker.undo import _rename_no_replace
        calls = []
        def fail_second(source, target):
            calls.append(source)
            if len(calls) == 2:
                raise PermissionError('fixture failure')
            _rename_no_replace(source, target)
        with patch('omarchy_file_picker.undo._rename_no_replace', side_effect=fail_second):
            result = self.history.undo()
        self.assertEqual(result.completed, {self.root / 'b-new': self.root / 'b'})
        self.assertIn('fixture failure', result.error)
        self.assertEqual(len(self.history.peek().items), 1)
        self.assertIsNone(self.history.undo().error)
        self.assertIsNone(self.history.peek())

    def test_collision_racing_preflight_is_atomic(self):
        a, b = self.root / 'a', self.root / 'b'
        a.write_text('original')
        self.renamed(a, b)
        from omarchy_file_picker.undo import _rename_no_replace
        def collision(source, target):
            target.write_text('racing file')
            _rename_no_replace(source, target)
        with patch('omarchy_file_picker.undo._rename_no_replace', side_effect=collision):
            result = self.history.undo()
        self.assertTrue(result.error)
        self.assertEqual(result.completed, {})
        self.assertEqual(a.read_text(), 'racing file')
        self.assertEqual(b.read_text(), 'original')

    def test_capture_mismatched_identity_and_bound_refuse(self):
        a, b = self.root / 'a', self.root / 'b'
        b.mkdir(); (b / 'child').write_text('x')
        self.assertIsNone(capture_receipt({a: b}, expected_identity=(0, 0, 0)))
        with patch('omarchy_file_picker.undo.MAX_ENTRIES', 1):
            self.assertIsNone(capture_receipt({a: b}))

    def test_history_is_bounded(self):
        history = UndoHistory(limit=2)
        for index in range(3):
            a, b = self.root / str(index), self.root / f'{index}-new'
            a.write_text(str(index)); a.rename(b)
            history.record(capture_receipt({a: b}))
        self.assertEqual(len(history._receipts), 2)


if __name__ == '__main__':
    unittest.main()
