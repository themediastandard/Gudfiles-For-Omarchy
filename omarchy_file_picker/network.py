"""Bounded NAS discovery using advertised services, not a subnet/port scan."""
from dataclasses import dataclass
import re
import shutil
import subprocess
import os
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


@dataclass(frozen=True)
class NetworkLocation:
    name: str
    uri: str
    detail: str
    server: bool = False


def mounted_local_path(uri):
    """Resolve an already-mounted location, repairing a missing GVfs bridge.

    Run on a worker thread. This does not authenticate or mount a new server.
    """
    from gi.repository import Gio, GLib
    file = Gio.File.new_for_uri(uri)
    local = file.get_path()
    if local and Path(local).is_dir():
        return Path(local)
    bridge = Path(GLib.get_user_runtime_dir()) / 'gvfs'
    if local and bridge in Path(local).parents and not os.path.ismount(bridge):
        executable = Path('/usr/lib/gvfsd-fuse')
        if not executable.is_file():
            raise RuntimeError('The GVfs filesystem bridge is missing. Install GVfs FUSE support to browse NAS folders.')
        bridge.mkdir(mode=0o700, exist_ok=True)
        try:
            result = subprocess.run([str(executable), str(bridge)], capture_output=True, text=True, timeout=5)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError('The GVfs filesystem bridge did not start in time. Try connecting again.') from exc
        if result.returncode and not os.path.ismount(bridge):
            raise RuntimeError('Could not start the GVfs filesystem bridge: ' + result.stderr.strip())
        for _ in range(20):
            local = file.get_path()
            if local and Path(local).is_dir():
                return Path(local)
            time.sleep(0.1)
    raise RuntimeError('This mounted folder is unavailable. Check the NAS connection and reconnect using Connect to NAS.')


def safe_network_uri(uri):
    """Do not propagate credentials from saved locations into labels or state."""
    parsed = urlsplit(uri)
    if parsed.scheme not in {'smb', 'smbs', 'nfs'} or not parsed.hostname:
        return None
    host = parsed.hostname
    if ':' in host:
        host = f'[{host}]'
    if parsed.port:
        host += f':{parsed.port}'
    return urlunsplit((parsed.scheme, host, parsed.path or '/', '', ''))


def parse_avahi(output, scheme):
    locations = []
    for line in output.splitlines():
        fields = line.split(';')
        if len(fields) < 9 or fields[0] != '=':
            continue
        name = re.sub(r'\\(\d{3})', lambda m: chr(int(m[1])), fields[3])
        host, address, port = fields[6:9]
        if not host or not port.isdigit():
            continue
        host = host.lower()
        authority = host if int(port) == (445 if scheme == 'smb' else 2049) else f'{host}:{port}'
        locations.append(NetworkLocation(name, f'{scheme}://{authority}/',
            f'{scheme.upper()} server · {address}', server=scheme == 'smb'))
    return locations


def discover_gvfs():
    locations = []
    # Include servers known by GVfs (for example its Windows-network provider).
    # Browsing here is passive: do not mount servers or prompt for credentials.
    from gi.repository import Gio
    import threading
    cancel = Gio.Cancellable()
    timer = threading.Timer(3, cancel.cancel)
    timer.daemon = True
    timer.start()
    try:
        network = Gio.File.new_for_uri('network:///')
        iterator = network.enumerate_children('standard::name,standard::display-name,standard::target-uri',
            Gio.FileQueryInfoFlags.NONE, cancel)
        try:
            while info := iterator.next_file(cancel):
                uri = info.get_attribute_string('standard::target-uri') or ''
                if urlsplit(uri).scheme in {'smb', 'smbs', 'nfs'}:
                    locations.append(NetworkLocation(info.get_display_name(), uri, 'Network server',
                        server=urlsplit(uri).scheme.startswith('smb') and not urlsplit(uri).path.strip('/')))
        finally:
            iterator.close(None)
    except Exception:
        pass  # DNS-SD and existing locations still work without this backend.
    finally:
        timer.cancel()
    return locations


def discover_network(known=()):
    locations = list(known) + discover_gvfs()
    notes = []
    if shutil.which('avahi-browse'):
        for service, scheme in [('_smb._tcp', 'smb'), ('_nfs._tcp', 'nfs')]:
            try:
                result = subprocess.run(['avahi-browse', '--resolve', '--terminate',
                    '--parsable', '--no-db-lookup', service], capture_output=True, text=True, timeout=5)
                locations.extend(parse_avahi(result.stdout, scheme))
                if result.returncode:
                    notes.append('Network discovery service is unavailable.')
            except subprocess.TimeoutExpired as error:
                output = error.stdout or b''
                locations.extend(parse_avahi(output.decode(errors='replace') if isinstance(output, bytes) else output, scheme))
            except OSError:
                notes.append('Network discovery could not start.')
    else:
        notes.append('Install Avahi tools to discover advertised servers.')
    unique = {}
    for location in locations:
        try:
            uri = safe_network_uri(location.uri)
        except ValueError:
            continue
        if uri:
            unique.setdefault(uri.rstrip('/').casefold(), NetworkLocation(
                location.name, uri, location.detail, location.server))
    return sorted(unique.values(), key=lambda p: p.name.casefold()), list(dict.fromkeys(notes))
