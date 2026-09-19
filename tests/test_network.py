import unittest
from pathlib import Path
from unittest.mock import patch, Mock
from omarchy_file_picker.network import NetworkLocation, discover_network, parse_avahi, safe_network_uri, mounted_local_path, mount_display_name


class NetworkTests(unittest.TestCase):
    def test_mount_labels_preserve_share_names_and_local_devices(self):
        cases = [
            ('Media on nas-tms.local', 'smb://nas-tms.local/Media', 'Media'),
            ('Work on location on NAS-TMS.local', 'smb://nas-tms.local/Work%20on%20location', 'Work on location'),
            ('Archive on nas.local', 'nfs://nas.local/archive', 'Archive'),
            ('Custom label', 'smb://nas.local/media', 'Custom label'),
            ('Work on location', 'smb://nas.local/Work%20on%20location', 'Work on location'),
            ('Drive on nas.local', 'file:///media/drive', 'Drive on nas.local'),
        ]
        for name, uri, expected in cases:
            with self.subTest(name=name, uri=uri):
                self.assertEqual(mount_display_name(name, uri), expected)

    def setUp(self):
        gvfs = patch('omarchy_file_picker.network.discover_gvfs', return_value=[])
        gvfs.start()
        self.addCleanup(gvfs.stop)

    def test_service_parsing(self):
        data = '+;eth0;IPv4;Studio;_smb._tcp;local\n=;eth0;IPv4;Studio\\032NAS;_smb._tcp;local;studio.local;192.0.2.2;445;\n'
        result = parse_avahi(data, 'smb')
        self.assertEqual(result, [NetworkLocation('Studio NAS', 'smb://studio.local/', 'SMB server · 192.0.2.2', True)])

    def test_mounted_local_path_no_repair_when_accessible(self):
        with patch('gi.repository.Gio.File.new_for_uri') as file, \
             patch.object(Path, 'is_dir', return_value=True), patch('subprocess.run') as run:
            file.return_value.get_path.return_value = '/run/user/1000/gvfs/share'
            self.assertEqual(mounted_local_path('smb://nas/media'), Path('/run/user/1000/gvfs/share'))
            run.assert_not_called()

    def test_mounted_local_path_repairs_missing_bridge(self):
        with patch('gi.repository.Gio.File.new_for_uri') as file, \
             patch('gi.repository.GLib.get_user_runtime_dir', return_value='/run/user/1000'), \
             patch.object(Path, 'is_dir', side_effect=[False, True]), \
             patch.object(Path, 'is_file', return_value=True), patch.object(Path, 'mkdir'), \
             patch('os.path.ismount', return_value=False), \
             patch('subprocess.run', return_value=Mock(returncode=0)) as run:
            file.return_value.get_path.return_value = '/run/user/1000/gvfs/share'
            self.assertEqual(mounted_local_path('smb://nas/media'), Path('/run/user/1000/gvfs/share'))
            self.assertEqual(run.call_args.args[0], ['/usr/lib/gvfsd-fuse', '/run/user/1000/gvfs'])

    def test_unavailable_local_mount_does_not_start_network_bridge(self):
        with patch('gi.repository.Gio.File.new_for_uri') as file, \
             patch.object(Path, 'is_dir', return_value=False), patch('subprocess.run') as run:
            file.return_value.get_path.return_value = '/media/unavailable'
            with self.assertRaisesRegex(RuntimeError, 'unavailable'):
                mounted_local_path('file:///media/unavailable')
            run.assert_not_called()

    def test_bridge_start_failure_is_reported(self):
        with patch('gi.repository.Gio.File.new_for_uri') as file, \
             patch('gi.repository.GLib.get_user_runtime_dir', return_value='/run/user/1000'), \
             patch.object(Path, 'is_dir', return_value=False), \
             patch.object(Path, 'is_file', return_value=True), patch.object(Path, 'mkdir'), \
             patch('os.path.ismount', return_value=False), \
             patch('subprocess.run', return_value=Mock(returncode=1, stderr='FUSE unavailable')):
            file.return_value.get_path.return_value = '/run/user/1000/gvfs/share'
            with self.assertRaisesRegex(RuntimeError, 'FUSE unavailable'):
                mounted_local_path('smb://nas/media')

    def test_saved_credentials_are_not_propagated(self):
        self.assertEqual(safe_network_uri('smb://user:password@nas.local/media'), 'smb://nas.local/media')
        self.assertIsNone(safe_network_uri('https://example.com'))

    def test_discovery_deduplicates_network_interfaces(self):
        fixture = '=;eth0;IPv4;Studio;_smb._tcp;local;studio.local;192.0.2.2;445;\n'
        class Result:
            returncode = 0
            stdout = fixture + fixture
        with patch('shutil.which', return_value='/usr/bin/avahi-browse'), patch('subprocess.run', return_value=Result()):
            locations, notes = discover_network()
        self.assertEqual(len(locations), 2)  # One each for the two tested protocols.
        self.assertFalse(notes)

    def test_known_shares_survive_missing_discovery_tools(self):
        with patch('shutil.which', return_value=None):
            locations, notes = discover_network([NetworkLocation('Media', 'smb://nas/media', 'Mounted share')])
        self.assertEqual(locations[0].uri, 'smb://nas/media')
        self.assertTrue(notes)
