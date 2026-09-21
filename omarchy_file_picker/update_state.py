"""Private update bookkeeping, separate from file preferences and user content."""
from contextlib import contextmanager
from dataclasses import asdict
import fcntl
import json
import os
from pathlib import Path
import tempfile
import threading
import time

from . import __version__, updates

DAY = 24 * 60 * 60
RETRY = 60 * 60
CHECK_TIMEOUT = 12


def bounded_check():
    # Socket timeouts alone do not bound a server that keeps trickling bytes.
    # Late replies stay local to this worker and cannot replace the timeout.
    done = threading.Event()
    replies = []

    def run():
        try:
            replies.append(updates.check_for_updates())
        except Exception:
            replies.append(updates.UpdateResult('error', 'Could not check for updates. Please try again later.'))
        finally:
            done.set()

    threading.Thread(target=run, name='gudfiles-release-request', daemon=True).start()
    if done.wait(CHECK_TIMEOUT) and replies:
        return replies[0]
    return updates.UpdateResult('error', 'Could not check for updates. Please try again later.')


class UpdateState:
    def __init__(self, directory=None, clock=time.time):
        self.directory = Path(directory) if directory is not None else Path(
            os.environ.get('XDG_STATE_HOME') or Path.home() / '.local/state') / 'gudfiles/updates'
        self.clock = clock
        self.used_cache = False

    @contextmanager
    def locked(self, name='lock'):
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (self.directory / name).open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield

    def read(self):
        try:
            with (self.directory / 'state.json').open() as file:
                value = json.loads(file.read(16385))
            if isinstance(value, dict) and value.get('repository') == updates.repository():
                return value
        except (OSError, ValueError, TypeError):
            pass
        return {'repository': updates.repository()}

    def write(self, value):
        name = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', dir=self.directory, delete=False) as file:
                name = file.name
                json.dump(value, file)
            os.replace(name, self.directory / 'state.json')
        finally:
            if name and os.path.exists(name):
                os.unlink(name)

    def fresh(self, timestamp, interval):
        return (isinstance(timestamp, (float, int)) and
                0 <= self.clock() - timestamp < interval)

    def check(self, *, force=False):
        self.used_cache = False
        try:
            with self.locked('check.lock'):
                with self.locked():
                    state = self.read()
                cached = state.get('result', {})
                if (not force and state.get('installed') == __version__ and
                        isinstance(cached, dict) and
                        self.fresh(state.get('checked'), RETRY if cached.get('status') == 'error' else DAY)):
                    try:
                        result = updates.UpdateResult(**cached)
                        valid = (result.status in {'available', 'current', 'ahead', 'unpublished', 'error'} and
                                 isinstance(result.message, str) and len(result.message) <= 4096 and
                                 isinstance(result.url, str) and len(result.url) <= 512)
                        if result.url:
                            prefix = updates.releases_url() + '/tag/v'
                            valid = valid and result.url.startswith(prefix)
                            if valid:
                                updates.version_tuple(result.url[len(prefix):])
                        if valid and (result.status != 'available' or updates.available_version(result)):
                            self.used_cache = True
                            return result
                    except (TypeError, ValueError):
                        pass
                started = self.clock()
                result = bounded_check()
                with self.locked():
                    state = self.read()
                    state.update(checked=started, installed=__version__, result=asdict(result))
                    self.write(state)
                return result
        except BlockingIOError:
            return updates.UpdateResult('busy', 'Another window is checking for updates. Please try again shortly.')
        except (OSError, ValueError, TypeError):
            # Fail quietly on launch, but give manual checks a useful diagnosis.
            return updates.UpdateResult('error', 'Could not access update history. Check that your user state folder is writable and try again.')

    def claim_notice(self, result):
        version = updates.available_version(result)
        if not version:
            return False
        try:
            with self.locked():
                state = self.read()
                if state.get('dismissed') == version:
                    return False
                if state.get('shown_version') == version and self.fresh(state.get('shown'), DAY):
                    return False
                state.update(shown_version=version, shown=self.clock())
                self.write(state)
                return True
        except (OSError, ValueError, TypeError):
            return False

    def dismiss(self, result):
        version = updates.available_version(result)
        if not version:
            return
        try:
            with self.locked():
                state = self.read()
                state['dismissed'] = version
                self.write(state)
        except (OSError, ValueError, TypeError):
            pass  # Always allow closing the notice, even on read-only storage.
