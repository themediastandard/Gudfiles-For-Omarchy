"""Display-only filename compatibility; never use these strings as paths."""
import re


_SMB_TRAILING_SPACE = re.compile(r"\uf028+(?=/|\Z)")


def display_filename(name: str) -> str:
    """Render SMB-encoded trailing spaces without changing filesystem identity.

    macOS SMB maps a trailing space to private-use U+F028, which icon fonts
    render as a speaker. Decode only at component boundaries in display text;
    paths, URIs, editable fields and file operations must retain the raw name.
    """
    return _SMB_TRAILING_SPACE.sub(lambda match: ' ' * len(match[0]), name)
