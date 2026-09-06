import unittest
from unittest.mock import patch
from omarchy_file_picker.network import NetworkLocation, discover_network, parse_avahi, safe_network_uri


class NetworkTests(unittest.TestCase):
    def setUp(self):
        gvfs = patch('omarchy_file_picker.network.discover_gvfs', return_value=[])
        gvfs.start()
        self.addCleanup(gvfs.stop)

    def test_service_parsing(self):
        data = '+;eth0;IPv4;Studio;_smb._tcp;local\n=;eth0;IPv4;Studio\\032NAS;_smb._tcp;local;studio.local;192.0.2.2;445;\n'
        result = parse_avahi(data, 'smb')
        self.assertEqual(result, [NetworkLocation('Studio NAS', 'smb://studio.local/', 'SMB server · 192.0.2.2', True)])

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
