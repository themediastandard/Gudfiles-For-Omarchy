"""Stable release discovery. No credentials, downloads or installation."""
from dataclasses import dataclass
import json
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from . import __version__


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)', value):
        raise ValueError('Expected a stable major.minor.patch version')
    return tuple(map(int, value.split('.')))


def repository():
    value = json.loads(Path(__file__).with_name('release.json').read_text())['repository']
    if not re.fullmatch(r'[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+', value):
        raise ValueError('Invalid release repository')
    return value


def releases_url():
    return f'https://github.com/{repository()}/releases'


def update_instructions():
    if Path(__file__).resolve().parent.parent == Path('/usr/lib/gudfiles'):
        return 'Download the package from the release page and follow its installation guide. Finish transfers and close Gudfiles before installing. Omarchy Update requires a published, updated AUR package.'
    return 'This is a local development installation. Follow the release installation guide to upgrade. Finish transfers and close Gudfiles before replacing this installation.'


@dataclass(frozen=True)
class UpdateResult:
    status: str
    message: str
    url: str = ''


def available_version(result):
    """Validate the exact trusted target again before displaying or caching it."""
    if not isinstance(result, UpdateResult) or result.status != 'available':
        return None
    try:
        prefix = f'https://github.com/{repository()}/releases/tag/v'
        if not isinstance(result.url, str) or not result.url.startswith(prefix):
            return None
        version = result.url[len(prefix):]
        return version if version_tuple(version) > version_tuple(__version__) else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def check_for_updates():
    try:
        repo = repository()
        request = Request(f'https://api.github.com/repos/{repo}/releases/latest', headers={
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
            'User-Agent': f'Gudfiles/{__version__}',
        })
        deadline = time.monotonic() + 12
        with urlopen(request, timeout=8) as response:
            raw = bytearray()
            read = getattr(response, 'read1', response.read)
            while len(raw) <= 262144:
                if time.monotonic() >= deadline:
                    raise TimeoutError('Release check timed out')
                chunk = read(min(16384, 262145 - len(raw)))
                if not chunk:
                    break
                raw.extend(chunk)
        if len(raw) > 262144:
            raise ValueError('Release response too large')
        release = json.loads(raw)
        tag = release['tag_name']
        if release.get('draft') is not False or release.get('prerelease') is not False:
            raise ValueError('Not a public stable release')
        if not isinstance(tag, str) or not tag.startswith('v'):
            raise ValueError('Invalid release tag')
        latest = tag[1:]
        latest_version = version_tuple(latest)
        url = f'https://github.com/{repo}/releases/tag/v{latest}'
        if latest_version > version_tuple(__version__):
            assets = release.get('assets', [])
            if not isinstance(assets, list) or not any(
                    isinstance(asset, dict) and
                    re.fullmatch(rf'gudfiles-{re.escape(latest)}-[1-9][0-9]*-any\.pkg\.tar\.zst', str(asset.get('name', ''))) and
                    asset.get('state') == 'uploaded' and
                    isinstance(asset.get('size'), int) and asset['size'] > 0
                    for asset in assets):
                return UpdateResult('unpublished', 'The newer release has no Gudfiles package available yet. Please check again later.')
            return UpdateResult('available', f'Gudfiles {latest} is available. {update_instructions()}', url)
        if latest_version == version_tuple(__version__):
            return UpdateResult('current', f'Gudfiles {__version__} is up to date.', url)
        return UpdateResult('ahead', 'You are running a version newer than the latest public release.', url)
    except HTTPError as error:
        code = error.code
        error.close()
        if code == 404:
            return UpdateResult('unpublished', 'No stable public release is available yet. Please check again later.')
        return UpdateResult('error', 'Could not check for updates. Please try again later.')
    except (OSError, URLError, ValueError, KeyError, TypeError):
        return UpdateResult('error', 'Could not check for updates. Check your connection and try again.')
