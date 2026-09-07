"""Readable light palettes, including monochrome and pastel accent themes."""
import unittest

from omarchy_file_picker.theme import (
    DEFAULT_COLORS, button_foreground, contrast_ratio, label_colors, prepare_colors,
)


LIGHT_PALETTES = {
    'latte': DEFAULT_COLORS,
    'white': {**DEFAULT_COLORS, 'background': '#ffffff', 'foreground': '#000000',
              'bright_foreground': '#000000', 'accent': '#6e6e6e', 'red': '#2a2a2a', 'dark_foreground': '#c0c0c0'},
    'lupine': {**DEFAULT_COLORS, 'background': '#fafafa', 'foreground': '#212121',
               'bright_foreground': '#000000', 'accent': '#3264eb', 'red': '#c900c4'},
    'flexoki': {**DEFAULT_COLORS, 'background': '#fffcf0', 'foreground': '#100f0f',
                'bright_foreground': '#100f0f', 'accent': '#205ea6', 'red': '#d14d41'},
    'rose': {**DEFAULT_COLORS, 'background': '#faf4ed', 'foreground': '#575279',
             'bright_foreground': '#575279', 'accent': '#56949f', 'red': '#b4637a', 'muted': '#cecacd'},
}


class ThemeTests(unittest.TestCase):
    def test_small_text_is_readable_on_light_surfaces(self):
        for name, source in LIGHT_PALETTES.items():
            with self.subTest(palette=name):
                c = prepare_colors(source)
                for surface in ('background', 'selection', 'dark_background', 'lighter_background'):
                    for ink in ('dark_foreground', 'light_foreground', 'muted', 'accent_ink'):
                        self.assertGreaterEqual(contrast_ratio(c[ink], c[surface]), 4.5, (ink, surface))
                    for ink in label_colors(c).values():
                        self.assertGreaterEqual(contrast_ratio(ink, c[surface]), 4.5)
                self.assertGreaterEqual(contrast_ratio(c['error_ink'], c['background']), 4.5)

    def test_desktop_identity_is_preserved_and_preparation_is_idempotent(self):
        for source in LIGHT_PALETTES.values():
            original = source.copy()
            c = prepare_colors(source)
            self.assertEqual(source, original)
            self.assertEqual(prepare_colors(c), c)
            for key in ('background', 'foreground', 'accent', 'red'):
                self.assertEqual(c[key], source[key])

    def test_dark_palette_is_preserved(self):
        source = {**DEFAULT_COLORS, 'mode': 'dark', 'background': '#1e1e2e',
                  'foreground': '#cdd6f4', 'accent': '#89b4fa'}
        c = prepare_colors(source)
        for key, value in source.items():
            self.assertEqual(c[key], value)
        self.assertEqual(label_colors(c)['orange'], '#c68b37')

    def test_button_ink_chooses_the_more_legible_foreground(self):
        for fill in ('#56949f', '#6e6e6e', '#1e66f5', '#89b4fa', '#b4637a', '#767676'):
            chosen = button_foreground(fill)
            other = '#ffffff' if chosen == '#111318' else '#111318'
            self.assertGreaterEqual(contrast_ratio(chosen, fill), contrast_ratio(other, fill))


if __name__ == '__main__':
    unittest.main()
