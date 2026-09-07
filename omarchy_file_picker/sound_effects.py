"""Short, optional action cues, isolated from preview audio and file operations."""
import json
from pathlib import Path
import shutil

from gi.repository import Gio, GLib


SOUND_DIR = Path(__file__).with_name('sounds')
CUES = {'drop', 'trash', 'delete', 'complete'}
PLAYBACK_TIMEOUT_MS = 2500
APPLICATION_NAME = 'Gudfiles Sound Effects'
APPLICATION_ID = 'org.omarchy.FilePicker.SoundEffects'


class ActionSounds:
    def __init__(self, preferences_path):
        self.preferences_path = preferences_path
        self.player = shutil.which('paplay')
        self.process = None
        self.timeout = 0
        self.last_started = -1_000_000
        self.closed = False

    @property
    def enabled(self):
        # Read the small local preference file so an older window respects a
        # mute chosen in another process, without changing its display settings.
        try:
            value = json.loads(self.preferences_path.read_text()).get('sound_effects', True)
            return value if isinstance(value, bool) else True
        except (OSError, ValueError, AttributeError):
            return True

    def play(self, cue):
        if self.closed or cue not in CUES or not self.player or not self.enabled:
            return False
        now = GLib.get_monotonic_time()
        if self.process is not None or now - self.last_started < 300_000:
            return False
        path = SOUND_DIR / f'{cue}.wav'
        if not path.is_file():
            return False
        try:
            process = Gio.Subprocess.new([
                self.player, f'--client-name={APPLICATION_NAME}',
                f'--property=application.id={APPLICATION_ID}',
                '--property=media.role=event', f'--stream-name=Gudfiles {cue}',
                '--volume=32768', str(path),
            ], Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE)
        except GLib.Error:
            return False
        self.process = process
        self.last_started = now
        self.timeout = GLib.timeout_add(PLAYBACK_TIMEOUT_MS, self._expired)
        process.wait_async(None, self._finished)
        return True

    def _finished(self, process, result):
        try:
            process.wait_finish(result)
        except GLib.Error:
            pass
        if self.process is process:
            self.process = None
            if self.timeout:
                GLib.source_remove(self.timeout)
                self.timeout = 0

    def _expired(self):
        self.timeout = 0
        self.stop()
        return False

    def stop(self):
        if self.timeout:
            GLib.source_remove(self.timeout)
            self.timeout = 0
        process, self.process = self.process, None
        if process is not None:
            try:
                process.force_exit()
            except GLib.Error:
                pass

    def close(self, *_):
        self.closed = True
        self.stop()
