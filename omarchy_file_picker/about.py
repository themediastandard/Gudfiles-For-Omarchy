"""Product credit and the bundled free-use license."""
from pathlib import Path

CREATOR = 'The Media Standard'
WEBSITE = 'https://themediastandard.com'
TAGLINE = 'Made for creatives using Linux.'
LICENSE_NAME = 'Gudfiles Free Use License'
LICENSE_SUMMARY = (
    'Free for personal and commercial use. Modification and redistribution '
    'require prior written permission from The Media Standard.'
)


def license_text():
    # The repository and user installation both keep LICENSE beside the package.
    try:
        return (Path(__file__).resolve().parent.parent / 'LICENSE').read_text(encoding='utf-8')
    except OSError:
        return 'The license file is missing. Reinstall Gudfiles to restore the full license.'
