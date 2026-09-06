import tempfile
import unittest
from pathlib import Path

from omarchy_file_picker.actions import (
    ActionError,
    image_convert_command,
    image_resize_command,
    normalize_nas_uri,
    unique_output,
    video_convert_command,
)
from omarchy_file_picker.model import FileFilter, PickerRequest, format_size, list_directory, portal_request
from omarchy_file_picker.theme import DEFAULT_COLORS, build_css, load_colors


class FileFilterTests(unittest.TestCase):
    def test_glob_and_mime_filters(self):
        image_filter = FileFilter("Images", ((0, "*.png"), (1, "image/jpeg")))
        self.assertTrue(image_filter.matches(Path("frame.png")))
        self.assertTrue(image_filter.matches(Path("frame.jpg")))
        self.assertFalse(image_filter.matches(Path("notes.txt")))

    def test_directory_is_always_navigable(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertTrue(FileFilter("Text", ((0, "*.txt"),)).matches(Path(root)))


class DirectoryTests(unittest.TestCase):
    def test_folders_first_hidden_and_query(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            (base / "z-folder").mkdir()
            (base / "alpha.txt").write_text("a")
            (base / ".hidden.txt").write_text("h")
            result = list_directory(base)
            self.assertEqual([item.name for item in result], ["z-folder", "alpha.txt"])
            queried = list_directory(base, query="ALPHA")
            self.assertEqual([item.name for item in queried], ["alpha.txt"])

    def test_directory_only(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            (base / "folder").mkdir()
            (base / "file.txt").write_text("x")
            self.assertEqual([item.name for item in list_directory(base, directories_only=True)], ["folder"])


class PortalRequestTests(unittest.TestCase):
    def test_open_request(self):
        request = portal_request(
            "OpenFile",
            "org.example.App",
            "Choose",
            {"multiple": True, "filters": [("Images", [(0, "*.png")])]},
        )
        self.assertEqual(request.title, "Choose")
        self.assertTrue(request.multiple)
        self.assertEqual(request.filters[0].name, "Images")

    def test_save_request_name(self):
        request = portal_request("SaveFile", "", "Save", {"current_name": "image.png"})
        self.assertEqual(request.mode, "save")
        self.assertEqual(request.current_name, "image.png")
        self.assertEqual(request.accept_label, "Save")


class FormattingTests(unittest.TestCase):
    def test_size(self):
        self.assertEqual(format_size(1024), "1.0 KB")


class FileActionTests(unittest.TestCase):
    def test_unique_output_never_replaces_original(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "photo.jpg"
            source.touch()
            first = Path(root) / "photo-small.jpg"
            first.touch()
            self.assertEqual(unique_output(source, "small", "jpg").name, "photo-small-2.jpg")

    def test_image_resize_preserves_format_and_uses_bounding_box(self):
        command, output = image_resize_command(Path("/tmp/photo.webp"), "medium")
        self.assertEqual(command[:2], ["magick", "/tmp/photo.webp"])
        self.assertIn("2160x2160>", command)
        self.assertEqual(output.name, "photo-medium.webp")

    def test_image_format_commands(self):
        command, output = image_convert_command(Path("/tmp/photo.png"), "jpeg")
        self.assertEqual(command[0], "magick")
        self.assertEqual(output.name, "photo-converted-jpg.jpg")

    def test_video_format_commands(self):
        command, output = video_convert_command(Path("/tmp/clip.mov"), "webm")
        self.assertEqual(command[0], "ffmpeg")
        self.assertIn("libvpx-vp9", command)
        self.assertEqual(output.name, "clip-converted-webm.webm")

    def test_nas_uri_validation_and_smb_default(self):
        self.assertEqual(normalize_nas_uri("nas/media"), "smb://nas/media")
        self.assertEqual(normalize_nas_uri("nfs://vault/archive"), "nfs://vault/archive")
        with self.assertRaises(ActionError):
            normalize_nas_uri("https://example.com/file")


class ThemeTests(unittest.TestCase):
    def test_missing_theme_uses_omarchy_fallback(self):
        colors = load_colors(Path("/definitely/missing/colors.toml"))
        self.assertEqual(colors["accent"], DEFAULT_COLORS["accent"])

    def test_css_uses_supplied_palette(self):
        colors = DEFAULT_COLORS | {"accent": "#123456"}
        self.assertIn("#123456", build_css(colors))


if __name__ == "__main__":
    unittest.main()
