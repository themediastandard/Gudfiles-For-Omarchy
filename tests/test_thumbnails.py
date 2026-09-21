"""Real decoder/cache checks plus deadline and process-tree cancellation."""
import os
from pathlib import Path
import subprocess
import shutil
import struct
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from omarchy_file_picker import thumbnails
import gi
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import GdkPixbuf


class ThumbnailsTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='thumbnails-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.home = patch.object(Path, 'home', return_value=self.root)
        self.home.start()
        self.addCleanup(self.home.stop)
        self.source = self.root / 'photo.png'
        self.write_image(1200, 800, 0xcc3322ff)

    def write_image(self, w, h, color):
        image = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, w, h)
        image.fill(color)
        image.savev(str(self.source), 'png', [], [])

    def test_real_decoder_cache_and_source_version(self):
        original = self.source.read_bytes()
        result = thumbnails.thumbnail_file(self.source)
        image = GdkPixbuf.Pixbuf.new_from_file(str(result))
        self.assertEqual((image.get_width(), image.get_height()), (360, 240))
        self.assertEqual(image.get_option('tEXt::SourceWidth'), '1200')
        with patch.object(thumbnails.subprocess, 'Popen', side_effect=AssertionError('cache miss')):
            self.assertEqual(thumbnails.thumbnail_file(self.source), result)
        self.assertEqual(original, self.source.read_bytes())
        self.write_image(600, 1200, 0x2233ccff)
        changed = thumbnails.thumbnail_file(self.source)
        self.assertNotEqual(result, changed)
        image = GdkPixbuf.Pixbuf.new_from_file(str(changed))
        self.assertEqual((image.get_width(), image.get_height()), (180, 360))

    def test_corrupt_cache_is_regenerated(self):
        result = thumbnails.thumbnail_file(self.source)
        data = bytearray(result.read_bytes())
        data[len(data) // 2] ^= 0xff
        result.write_bytes(data)
        self.assertEqual(thumbnails.thumbnail_file(self.source), result)
        image = GdkPixbuf.Pixbuf.new_from_file(str(result))
        self.assertEqual(image.get_width(), 360)

    def test_camera_jpeg_decoder(self):
        self.source = self.root / 'camera.jpg'
        image = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 6000, 4000)
        image.fill(0x558833ff)
        image.savev(str(self.source), 'jpeg', [], [])
        del image
        original = self.source.read_bytes()
        result = thumbnails.thumbnail_file(self.source)
        self.assertIsNotNone(result)
        image = GdkPixbuf.Pixbuf.new_from_file(str(result))
        self.assertEqual((image.get_width(), image.get_height()), (360, 240))
        self.assertEqual(image.get_option('tEXt::SourceWidth'), '6000')
        self.assertEqual(self.source.read_bytes(), original)

    def test_failed_decoder_logs_bounded_diagnostics_and_recovers(self):
        real_popen = subprocess.Popen
        def failed(_command, **kwargs):
            return real_popen([sys.executable, '-c',
                              'import sys; sys.stderr.write("decoder broke\\n" + "x" * 100000); sys.exit(7)'],
                             **kwargs)
        with patch.object(thumbnails.subprocess, 'Popen', side_effect=failed), \
                self.assertLogs(thumbnails.__name__, level='WARNING') as logs:
            self.assertIsNone(thumbnails.thumbnail_file(self.source))
        self.assertIn('exit 7', logs.output[0])
        self.assertIn('decoder broke', logs.output[0])
        self.assertLess(len(logs.output[0]), 4600)
        self.assertFalse(list((self.root / '.cache/omarchy-file-picker/thumbnails-v2').iterdir()))
        self.assertIsNotNone(thumbnails.thumbnail_file(self.source))

    def test_jpeg_embedded_orientation_and_original_dimensions(self):
        self.source = self.root / 'rotated.jpg'
        image = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 1200, 800)
        image.fill(0x558833ff)
        image.savev(str(self.source), 'jpeg', [], [])
        # Minimal EXIF IFD: orientation 6 (90 degrees clockwise).
        exif = (b'Exif\0\0II' + struct.pack('<HIH', 42, 8, 1) +
                struct.pack('<HHIHHI', 0x112, 3, 1, 6, 0, 0))
        jpeg = self.source.read_bytes()
        self.source.write_bytes(jpeg[:2] + b'\xff\xe1' + struct.pack('>H', len(exif) + 2) + exif + jpeg[2:])
        original = self.source.read_bytes()
        result = thumbnails.thumbnail_file(self.source)
        self.assertIsNotNone(result)
        image = GdkPixbuf.Pixbuf.new_from_file(str(result))
        self.assertEqual((image.get_width(), image.get_height()), (240, 360))
        self.assertEqual(image.get_option('tEXt::SourceWidth'), '1200')
        self.assertEqual(image.get_option('tEXt::SourceHeight'), '800')
        self.assertEqual(self.source.read_bytes(), original)

    def test_source_changed_during_decode_is_not_published(self):
        real_popen = subprocess.Popen
        def changed(command, **kwargs):
            process = real_popen(command, **kwargs)
            os.utime(self.source, ns=(1, 1))
            return process
        with patch.object(thumbnails.subprocess, 'Popen', side_effect=changed):
            self.assertIsNone(thumbnails.thumbnail_file(self.source))
        self.assertFalse(list((self.root / '.cache/omarchy-file-picker/thumbnails-v2').iterdir()))
        self.assertIsNotNone(thumbnails.thumbnail_file(self.source))

    def test_unsupported_missing_and_broken(self):
        self.assertIsNone(thumbnails.thumbnail_file(self.root / 'missing.nef'))
        self.assertIsNone(thumbnails.thumbnail_file(self.root / 'document.txt'))
        self.source.write_bytes(b'broken image')
        self.assertIsNone(thumbnails.thumbnail_file(self.source))
        self.assertEqual(list((self.root / '.cache/omarchy-file-picker/thumbnails-v2').iterdir()), [])

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffmpegthumbnailer'), 'video helpers missing')
    def test_real_video_thumbnail(self):
        video = self.root / 'video.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=640x360:d=1',
                        '-threads', '1', '-pix_fmt', 'yuv420p', str(video)], check=True)
        original = video.read_bytes()
        result = thumbnails.thumbnail_file(video)
        self.assertIsNotNone(result)
        image = GdkPixbuf.Pixbuf.new_from_file(str(result))
        self.assertLessEqual(max(image.get_width(), image.get_height()), 360)
        self.assertEqual(video.read_bytes(), original)

    def test_timeout_and_cancellation_reap_descendants(self):
        real_popen = subprocess.Popen
        child_id = self.root / 'child.pid'
        script = ('import subprocess,sys,time; from pathlib import Path; '
                  'p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"]); '
                  f'Path({str(child_id)!r}).write_text(str(p.pid)); time.sleep(60)')
        processes = []
        def fake_decoder(_command, **kwargs):
            process = real_popen([sys.executable, '-c', script], **kwargs)
            processes.append(process)
            return process
        for cancel in (False, True):
            child_id.unlink(missing_ok=True)
            event = threading.Event()
            result = []
            with patch.object(thumbnails.subprocess, 'Popen', side_effect=fake_decoder), \
                    patch.object(thumbnails, 'DECODE_TIMEOUT', .4 if not cancel else 10):
                thread = threading.Thread(target=lambda: result.append(
                    thumbnails.thumbnail_file(self.source, event.is_set)))
                thread.start()
                deadline = time.monotonic() + 3
                while not child_id.exists() and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue(child_id.exists())
                if cancel:
                    event.set()
                thread.join(3)
                self.assertFalse(thread.is_alive())
            self.assertEqual(result, [None])
            self.assertIsNotNone(processes[-1].poll())
            pid = child_id.read_text()
            deadline = time.monotonic() + 2
            state = Path(f'/proc/{pid}/stat')
            while state.exists() and state.read_text().split()[2] != 'Z' and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue(not state.exists() or state.read_text().split()[2] == 'Z')
            self.assertEqual(list((self.root / '.cache/omarchy-file-picker/thumbnails-v2').iterdir()), [])


if __name__ == '__main__':
    unittest.main()
