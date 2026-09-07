from pathlib import Path
import queue
import shutil
import subprocess
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch

from omarchy_file_picker.media_details import (
    MediaDetails, MediaDetailsService, details_from_probe, probe_media,
)


class MediaDetailsTests(unittest.TestCase):
    def test_video_and_audio_fields(self):
        result = details_from_probe({'streams': [
            {'codec_type': 'video', 'width': 3840, 'height': 2160,
             'codec_name': 'hevc', 'avg_frame_rate': '24000/1001',
             'pix_fmt': 'yuv420p10le'},
            {'codec_type': 'audio', 'codec_name': 'aac', 'channels': 2,
             'channel_layout': 'stereo', 'sample_rate': '48000'},
        ], 'format': {'duration': '65.25', 'tags': {'com.apple.quicktime.model': 'Camera X'}}})
        fields = dict(result.fields)
        self.assertEqual(fields['Resolution'], '3840 × 2160')
        self.assertEqual(fields['Frame rate'], '23.976 fps')
        self.assertEqual(fields['Video depth'], '10-bit')
        self.assertEqual(fields['Duration'], '1:05')
        self.assertEqual(fields['Audio channels'], '2 channels · stereo')
        self.assertEqual(fields['Sample rate'], '48 kHz')
        self.assertEqual(fields['Camera model'], 'Camera X')
        self.assertNotIn('Audio depth', fields)  # AAC does not imply PCM bit depth.

    def test_absent_invalid_and_attached_cover_fields(self):
        result = details_from_probe({'streams': [
            {'codec_type': 'video', 'width': 500, 'height': 500,
             'disposition': {'attached_pic': 1}},
            {'codec_type': 'audio', 'codec_name': 'flac', 'bits_per_raw_sample': '24'},
        ], 'format': {'duration': 'NaN'}})
        fields = dict(result.fields)
        self.assertNotIn('Resolution', fields)
        self.assertNotIn('Duration', fields)
        self.assertEqual(fields['Audio depth'], '24-bit')
        self.assertEqual(details_from_probe({'streams': 'bad'}), MediaDetails())

    def test_missing_tool_and_corrupt_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'bad.mp4'
            path.write_bytes(b'not a movie')
            self.assertEqual(probe_media(path), MediaDetails())
            with patch('shutil.which', return_value=None):
                self.assertEqual(probe_media(path), MediaDetails())
            self.assertEqual(probe_media(path.parent), MediaDetails())

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
    def test_generated_video_and_audio(self):
        with tempfile.TemporaryDirectory() as temporary:
            movie = Path(temporary) / 'test.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                            'testsrc2=size=160x96:rate=24', '-f', 'lavfi', '-i',
                            'anullsrc=r=48000:cl=stereo', '-t', '1', '-c:v', 'libx264',
                            '-threads', '1', '-c:a', 'aac', str(movie)],
                           check=True, timeout=20)
            fields = dict(probe_media(movie).fields)
            self.assertEqual(fields['Resolution'], '160 × 96')
            self.assertEqual(fields['Frame rate'], '24 fps')
            self.assertEqual(fields['Video depth'], '8-bit')
            self.assertEqual(fields['Audio codec'], 'AAC')
            self.assertEqual(fields['Duration'], '0:01')
            wav = Path(temporary) / 'test.wav'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                            'anullsrc=r=48000:cl=mono', '-t', '1', '-c:a', 'pcm_s24le', str(wav)],
                           check=True, timeout=20)
            fields = dict(probe_media(wav).fields)
            self.assertEqual(fields['Audio depth'], '24-bit')
            self.assertEqual(fields['Audio channels'], '1 channel · mono')

    @unittest.skipUnless(shutil.which('magick'), 'ImageMagick required')
    def test_generated_image(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'test image.png'
            subprocess.run(['magick', '-size', '320x180', 'xc:blue', str(path)],
                           check=True, timeout=10)
            result = probe_media(path)
            self.assertEqual(dict(result.fields)['Resolution'], '320 × 180')
            self.assertNotIn('Camera model', dict(result.fields))

    @unittest.skipUnless(shutil.which('magick'), 'ImageMagick required')
    def test_real_exif_image(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'camera.jpg'
            subprocess.run(['magick', '-size', '64x48', 'xc:blue', str(path)],
                           check=True, timeout=10)
            # Add a standards-shaped TIFF IFD to a generated JPEG, not user media.
            make, model = b'Test Camera Co\0', b'Fixture 01\0'
            offset = 8 + 2 + 2 * 12 + 4
            tiff = b'II' + struct.pack('<HIH', 42, 8, 2)
            tiff += struct.pack('<HHII', 0x010F, 2, len(make), offset)
            tiff += struct.pack('<HHII', 0x0110, 2, len(model), offset + len(make))
            tiff += struct.pack('<I', 0) + make + model
            exif = b'Exif\0\0' + tiff
            jpeg = path.read_bytes()
            path.write_bytes(jpeg[:2] + b'\xff\xe1' + struct.pack('>H', len(exif) + 2) + exif + jpeg[2:])
            fields = dict(probe_media(path).fields)
            self.assertEqual(fields['Resolution'], '64 × 48')
            self.assertEqual(fields['Camera make'], 'Test Camera Co')
            self.assertEqual(fields['Camera model'], 'Fixture 01')

    def test_exif_fields_only_when_available(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'camera.jpg'
            path.touch()
            values = ['6000', '4000', '8', 'JPEG', 'Make', 'Camera',
                      '35mm lens', '400', '1/125', '28/10', '2026:09:06 12:00:00']
            with patch('omarchy_file_picker.media_details._run', return_value='\x1e'.join(values)):
                result = probe_media(path)
            self.assertEqual(dict(result.fields)['Camera model'], 'Camera')
            self.assertEqual(dict(result.fields)['Lens'], '35mm lens')
            self.assertEqual(dict(result.fields)['Aperture'], 'f/2.8')
            self.assertEqual(dict(result.fields)['Exposure'], '1/125 s')


class MediaDetailsServiceTests(unittest.TestCase):
    def test_cache_invalidation_and_main_thread_dispatch(self):
        queued = queue.Queue()
        probes = []
        main_thread = threading.get_ident()
        def probe(path):
            self.assertNotEqual(threading.get_ident(), main_thread)
            probes.append(path)
            return MediaDetails(path.read_text(), (('Value', path.read_text()),))
        service = MediaDetailsService(dispatch=queued.put, probe=probe)
        try:
            with tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / 'media.mp4'
                path.write_text('one')
                results = []
                service.request(path, results.append)
                queued.get(timeout=2)()
                service.request(path, results.append)
                queued.get(timeout=2)()
                self.assertEqual(len(probes), 1)
                path.write_text('changed content')
                service.request(path, results.append)
                queued.get(timeout=2)()
                self.assertEqual(len(probes), 2)
                self.assertEqual(results[-1].summary, 'changed content')
        finally:
            service.close()

    def test_stale_callbacks_and_coalesced_pending_requests(self):
        queued = queue.Queue()
        started = threading.Event()
        release = threading.Event()
        probes = []
        def probe(path):
            probes.append(path.name)
            if len(probes) == 1:
                started.set()
                release.wait(timeout=3)
            return MediaDetails(path.name)
        service = MediaDetailsService(dispatch=queued.put, probe=probe)
        try:
            with tempfile.TemporaryDirectory() as temporary:
                paths = [Path(temporary) / f'{n}.mp4' for n in range(3)]
                for path in paths:
                    path.touch()
                results = []
                service.request(paths[0], results.append)
                self.assertTrue(started.wait(timeout=2))
                service.request(paths[1], results.append)
                service.request(paths[2], results.append)
                release.set()
                queued.get(timeout=2)()
                queued.get(timeout=2)()
                self.assertEqual(probes, ['0.mp4', '2.mp4'])
                self.assertEqual([item.summary for item in results], ['2.mp4'])
                service.request(paths[2], results.append)
                callback = queued.get(timeout=2)
                service.cancel()
                callback()
                self.assertEqual(len(results), 1)
                service.request(paths[2], results.append)
                callback = queued.get(timeout=2)
                service.close()
                callback()
                self.assertEqual(len(results), 1)
        finally:
            release.set()
            service.close()


if __name__ == '__main__':
    unittest.main()
