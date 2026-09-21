"""Guide discovery must describe the capabilities actually shipped in a build."""
import unittest
from omarchy_file_picker.help_catalog import available_features, matching_features


class HelpDiscovery(unittest.TestCase):
    def test_optional_features_do_not_advertise_missing_controls(self):
        basic = available_features(set())
        current = available_features({'folder_sizes', 'empty_trash', 'launch_updates'})
        for phrase, title in [('recursive bytes', 'Folder sizes'), ('empty trash', 'Empty Trash'),
                              ('automatic updater', 'Update notices')]:
            self.assertNotIn(title, [f.title for f in matching_features(phrase, features=basic)])
            self.assertIn(title, [f.title for f in matching_features(phrase, features=current)])

    def test_shortcuts_and_recent_controls_are_findable(self):
        features = available_features(set())
        self.assertEqual([f.title for f in matching_features('Ctrl+Shift+V', features=features)],
                         ['Stage work for later'])
        for phrase, title in [('fit columns', 'Resize and fit list columns'),
                              ('grid slider', 'Thumbnail size'), ('choose folder', 'Choose a folder'),
                              ('media details', 'Media details at a glance')]:
            self.assertIn(title, [f.title for f in matching_features(phrase, features=features)])
        self.assertFalse(matching_features('automatic updater', 'preview', features=features))


if __name__ == '__main__':
    unittest.main()
