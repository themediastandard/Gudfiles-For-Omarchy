"""Real subprocess lifecycle checks with a silent disposable player."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import wave

from gi.repository import GLib
from omarchy_file_picker import sound_effects


def until(predicate, timeout=3):
    context = GLib.MainContext.default()
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        while context.pending():
            context.iteration(False)
        time.sleep(.005)
    if not predicate():
        raise AssertionError('Sound player did not settle')


class SoundEffectTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='gudfiles-sound-test-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.player = self.root / 'silent player'
        self.player.write_text(
            '#!/usr/bin/python\nimport json, pathlib, sys, time\n'
            'root = pathlib.Path(__file__).parent\n'
            '(root / "args.json").write_text(json.dumps(sys.argv[1:]))\n'
            'time.sleep(float((root / "delay").read_text()))\n')
        self.player.chmod(0o755)
        (self.root / 'delay').write_text('.04')
        self.preferences = self.root / 'preferences.json'
        self.sounds = sound_effects.ActionSounds(self.preferences)
        self.sounds.player = str(self.player)
        self.addCleanup(self.sounds.close)

    def test_real_player_is_nonblocking_reaped_and_isolated_from_preview_audio(self):
        start = time.monotonic()
        self.assertTrue(self.sounds.play('drop'))
        self.assertLess(time.monotonic() - start, .2)
        until(lambda: (self.root / 'args.json').exists())
        args = json.loads((self.root / 'args.json').read_text())
        self.assertIn('--client-name=Gudfiles Sound Effects', args)
        self.assertIn('--property=media.role=event', args)
        self.assertIn('--volume=32768', args)
        self.assertEqual(Path(args[-1]), sound_effects.SOUND_DIR / 'drop.wav')
        until(lambda: self.sounds.process is None)
        self.assertEqual(self.sounds.timeout, 0)

    def test_overlap_and_fast_completions_do_not_create_a_sound_backlog(self):
        self.assertTrue(self.sounds.play('drop'))
        self.assertFalse(self.sounds.play('complete'))
        until(lambda: self.sounds.process is None)
        self.assertFalse(self.sounds.play('trash'))
        until(lambda: GLib.get_monotonic_time() - self.sounds.last_started >= 310_000)
        self.assertTrue(self.sounds.play('trash'))
        until(lambda: self.sounds.process is None)

    def test_mute_is_read_back_from_other_windows_and_does_not_create_preferences(self):
        self.assertTrue(self.sounds.enabled)
        self.assertFalse(self.preferences.exists())
        self.preferences.write_text('{"sound_effects": false, "view_mode": "columns"}')
        self.assertFalse(self.sounds.enabled)
        self.assertFalse(self.sounds.play('delete'))
        self.assertFalse((self.root / 'args.json').exists())
        self.preferences.write_text('{"sound_effects": true}')
        self.assertTrue(self.sounds.enabled)
        for content in ('not json', '[]', '{"sound_effects": "false"}'):
            self.preferences.write_text(content)
            self.assertTrue(self.sounds.enabled)

    def test_missing_player_assets_and_unknown_cues_are_silent(self):
        self.sounds.player = None
        self.assertFalse(self.sounds.play('drop'))
        self.sounds.player = str(self.root / 'missing player')
        self.assertFalse(self.sounds.play('drop'))
        self.sounds.player = str(self.player)
        self.assertFalse(self.sounds.play('../../anything'))
        with patch.object(sound_effects, 'SOUND_DIR', self.root):
            self.assertFalse(self.sounds.play('drop'))

    def test_stalled_player_is_terminated_and_reaped(self):
        (self.root / 'delay').write_text('60')
        with patch.object(sound_effects, 'PLAYBACK_TIMEOUT_MS', 80):
            self.assertTrue(self.sounds.play('complete'))
        process = self.sounds.process
        until(lambda: self.sounds.process is None)
        process.wait(None)
        self.assertTrue(process.get_if_signaled())
        self.assertEqual(self.sounds.timeout, 0)

    def test_mute_or_window_close_stops_an_active_player(self):
        (self.root / 'delay').write_text('60')
        self.assertTrue(self.sounds.play('trash'))
        process = self.sounds.process
        self.sounds.close()
        process.wait(None)
        self.assertTrue(process.get_if_signaled())
        self.assertFalse(self.sounds.play('complete'))
        self.assertIsNone(self.sounds.process)
        self.assertEqual(self.sounds.timeout, 0)

    def test_bundled_cues_are_short_valid_pcm_with_headroom(self):
        from array import array
        for cue in sound_effects.CUES:
            with wave.open(str(sound_effects.SOUND_DIR / f'{cue}.wav')) as stream:
                self.assertEqual((stream.getnchannels(), stream.getsampwidth()), (1, 2))
                duration = stream.getnframes() / stream.getframerate()
                self.assertTrue(.1 < duration < .4)
                samples = array('h', stream.readframes(stream.getnframes()))
                self.assertTrue(100 < max(abs(n) for n in samples) < 16384)
                self.assertEqual(samples[0], 0)
                self.assertLess(abs(samples[-1]), 10)
