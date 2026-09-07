"""User-requested release checks. No credentials, downloads or installation."""
from dataclasses import dataclass
import json
from pathlib import Path
import re
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
        return 'Finish transfers and close Gudfiles, then run Omarchy Update. Package availability may follow the release.'
    return 'This is a local development installation. Install the official Gudfiles package to receive Omarchy updates. Finish transfers and close Gudfiles before replacing this installation.'


@dataclass(frozen=True)
class UpdateResult:
    status: str
    message: str
    url: str = ''


def check_for_updates():
    try:
        repo = repository()
        request = Request(f'https://api.github.com/repos/{repo}/releases/latest', headers={
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
            'User-Agent': f'Gudfiles/{__version__}',
        })
        with urlopen(request, timeout=8) as response:
            raw = response.read(262145)
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
            return UpdateResult('available', f'Gudfiles {latest} is available. {update_instructions()}', url)
        if latest_version == version_tuple(__version__):
            return UpdateResult('current', f'Gudfiles {__version__} is up to date.', url)
        return UpdateResult('ahead', 'You are running a version newer than the latest public release.', url)
    except HTTPError as error:
        code = error.code
        error.close()
        if code == 404:
            return UpdateResult('unpublished', 'No public release is available yet. Please check again later.')
        return UpdateResult('error', 'Could not check for updates. Please try again later.')
    except (OSError, URLError, ValueError, KeyError, TypeError):
        return UpdateResult('error', 'Could not check for updates. Check your connection and try again.')
