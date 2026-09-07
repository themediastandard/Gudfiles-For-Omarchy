import configparser
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import shutil
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from omarchy_file_picker import __version__, updates
from omarchy_file_picker.portal_setup import configure, BACKEND

ROOT = Path(__file__).resolve().parents[1]


def script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f'scripts/{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReleaseChecks(unittest.TestCase):
    @unittest.skipUnless(shutil.which('makepkg'), 'Arch release tooling requires makepkg')
    def test_archive_is_reproducible_and_excludes_private_files(self):
        with tempfile.TemporaryDirectory(prefix='gudfiles-release-test-') as temp:
            builder = script('prepare-release')
            first = builder.prepare(Path(temp) / 'first')
            second = builder.prepare(Path(temp) / 'second')
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with tarfile.open(first) as archive:
                members = archive.getmembers()
            names = [member.name for member in members]
            self.assertTrue(any(name.endswith('/LICENSE') for name in names))
            self.assertTrue(any(name.endswith('/release.json') for name in names))
            self.assertFalse(any(name.endswith(('PROJECT.md', '.pyc', '.sqlite3')) or '/tests/' in name or '/.git/' in name for name in names))
            self.assertTrue(all(member.isfile() and member.mtime == 0 and member.uid == 0 for member in members))

    def result(self, release):
        with patch.object(updates, 'urlopen', return_value=io.BytesIO(json.dumps(release).encode())) as fetch:
            result = updates.check_for_updates()
        self.assertEqual(fetch.call_args.kwargs['timeout'], 8)
        self.assertNotIn('Authorization', fetch.call_args.args[0].headers)
        return result

    def test_stable_version_comparison(self):
        with patch.object(updates, '__version__', '0.1.9'):
            self.assertEqual(self.result({'tag_name': 'v0.1.10', 'draft': False, 'prerelease': False}).status, 'available')
            self.assertEqual(self.result({'tag_name': 'v0.1.9', 'draft': False, 'prerelease': False}).status, 'current')
            self.assertEqual(self.result({'tag_name': 'v0.1.8', 'draft': False, 'prerelease': False}).status, 'ahead')

    def test_untrusted_metadata(self):
        for release in ([], {}, {'tag_name': 'v2.0.0', 'draft': True, 'prerelease': False},
                        {'tag_name': 'v2.0.0-rc1', 'draft': False, 'prerelease': True},
                        {'tag_name': 'v2.0.0/../../evil', 'draft': False, 'prerelease': False}):
            self.assertEqual(self.result(release).status, 'error')
        result = self.result({'tag_name': 'v2.0.0', 'draft': False, 'prerelease': False,
                              'html_url': 'https://evil.example/download'})
        self.assertTrue(result.url.startswith('https://github.com/themediastandard/'))

    def test_network_and_unpublished(self):
        for error, status in [(TimeoutError(), 'error'),
                              (HTTPError('url', 403, 'rate limited', {}, None), 'error'),
                              (HTTPError('url', 404, 'missing', {}, None), 'unpublished')]:
            with patch.object(updates, 'urlopen', side_effect=error):
                self.assertEqual(updates.check_for_updates().status, status)
        for content in (b'invalid json', b'x' * 262145):
            with patch.object(updates, 'urlopen', return_value=io.BytesIO(content)):
                self.assertEqual(updates.check_for_updates().status, 'error')

    def test_versions_and_install_channel(self):
        for value in ('v1.0.0', '1.0', '01.2.3', '1.0.0-rc1', None):
            with self.assertRaises(ValueError):
                updates.version_tuple(value)
        with patch.object(updates, '__file__', '/usr/lib/gudfiles/omarchy_file_picker/updates.py'):
            self.assertIn('run Omarchy Update', updates.update_instructions())
        self.assertIn('local development installation', updates.update_instructions())


class InstallChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='gudfiles-install-test-')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / 'A home with spaces'
        self.home.mkdir()
        self.routing = self.home / '.config/xdg-desktop-portal/hyprland-portals.conf'

    def test_portal_restores_choice_and_keeps_later_changes(self):
        self.routing.parent.mkdir(parents=True)
        self.routing.write_text('[preferred]\ndefault=hyprland;gtk\norg.freedesktop.impl.portal.FileChooser=gtk\n')
        configure(enable=True, home=self.home)
        backup = self.home / '.config/omarchy-file-picker/portal-backup.json'
        before = backup.read_bytes()
        configure(enable=True, home=self.home)
        self.assertEqual(backup.read_bytes(), before)
        self.routing.write_text(self.routing.read_text() + 'org.freedesktop.impl.portal.Screenshot=hyprland\n')
        configure(enable=False, home=self.home)
        self.assertIn('FileChooser=gtk', self.routing.read_text())
        self.assertIn('Screenshot=hyprland', self.routing.read_text())
        self.assertFalse(backup.exists())

    def test_portal_does_not_overwrite_another_app_or_bad_config(self):
        configure(enable=True, home=self.home)
        self.routing.write_text('[preferred]\norg.freedesktop.impl.portal.FileChooser=kde\n')
        configure(enable=False, home=self.home)
        self.assertIn('FileChooser=kde', self.routing.read_text())
        self.routing.write_text('not a valid config')
        with self.assertRaises(RuntimeError):
            configure(enable=True, home=self.home)
        self.assertEqual(self.routing.read_text(), 'not a valid config')

    def test_install_upgrade_remove_preserve_user_data(self):
        installer = script('user-install')
        app = self.home / '.local/share/omarchy-file-picker'
        app.mkdir(parents=True)
        user_files = [app / 'ratings.sqlite3', app / 'ratings.sqlite3-wal', app / 'ratings.sqlite3-shm',
                      self.home / '.config/omarchy-file-picker/preferences.json',
                      self.home / '.config/gtk-3.0/bookmarks']
        for index, path in enumerate(user_files):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f'user-data-{index}'.encode())
        installer.change_install(self.home)
        obsolete = app / 'omarchy_file_picker/obsolete.py'
        obsolete.write_text('old code')
        backup = installer.change_install(self.home)
        self.assertFalse(obsolete.exists())
        self.assertTrue((backup / 'omarchy_file_picker/obsolete.py').exists())
        result = subprocess.run([self.home / '.local/bin/gudfiles', '--version'], cwd='/tmp',
                                check=True, capture_output=True, text=True)
        self.assertIn(f'Gudfiles {__version__}', result.stdout)
        configure(enable=True, home=self.home)
        installer.change_install(self.home, remove=True)
        self.assertFalse((app / 'omarchy_file_picker').exists())
        self.assertFalse((self.home / '.local/bin/gudfiles').exists())
        self.assertNotIn(BACKEND, self.routing.read_text())
        for index, path in enumerate(user_files):
            self.assertEqual(path.read_bytes(), f'user-data-{index}'.encode())

    def test_legacy_routing_restore(self):
        installer = script('user-install')
        installer.change_install(self.home)
        self.routing.parent.mkdir(parents=True, exist_ok=True)
        self.routing.write_text((ROOT / 'data/hyprland-portals.conf').read_text())
        legacy = self.home / '.config/omarchy/backups/omarchy-file-picker/hyprland-portals.conf.20260101'
        legacy.parent.mkdir(parents=True)
        legacy.write_text('[preferred]\ndefault=gtk\n')
        installer.change_install(self.home, remove=True)
        self.assertEqual(self.routing.read_text(), legacy.read_text())

    def test_system_layout_never_touches_home_or_restarts_services(self):
        dest = self.home / 'pkg'
        script('install-system').install(dest)
        self.assertFalse((dest / 'home').exists())
        self.assertFalse((dest / 'etc').exists())
        self.assertEqual((dest / 'usr/lib/gudfiles/LICENSE').read_bytes(), (ROOT / 'LICENSE').read_bytes())
        self.assertTrue((dest / 'usr/share/licenses/gudfiles/LICENSE').exists())
        self.assertIn('/usr/lib/gudfiles', (dest / 'usr/bin/gudfiles').read_text())
        self.assertFalse(any(dest.rglob('*.pyc')))
        self.assertFalse(any(dest.rglob('*.sqlite3')))

    def test_desktop_launcher_accepts_a_video_and_advertises_common_video_types(self):
        desktop = configparser.ConfigParser(interpolation=None)
        desktop.read(ROOT / 'data/org.omarchy.FilePicker.desktop')
        entry = desktop['Desktop Entry']
        self.assertEqual(entry['Exec'], 'gudfiles --demo %f --multiple')
        mime_types = set(entry['MimeType'].split(';'))
        self.assertTrue({'video/mp4', 'video/x-matroska', 'video/webm', 'video/quicktime'} <= mime_types)
        self.assertIn('inode/directory', mime_types)

    def test_file_manager_dbus_service_is_installed_for_both_scopes(self):
        installer = script('user-install')
        installer.change_install(self.home)
        user_service = self.home / '.local/share/dbus-1/services/org.freedesktop.FileManager1.service'
        self.assertIn(f'Exec="{self.home}/.local/bin/gudfiles" --file-manager-service',
                      user_service.read_text())

        dest = self.home / 'pkg'
        script('install-system').install(dest)
        system_service = dest / 'usr/share/dbus-1/services/org.freedesktop.FileManager1.service'
        self.assertIn('Exec="/usr/bin/gudfiles" --file-manager-service', system_service.read_text())


if __name__ == '__main__':
    unittest.main()
