"""Disposable thumbnail decoder. A broken/huge image cannot take down GTK."""
from __future__ import annotations

import resource
from pathlib import Path
import shutil
import subprocess
import sys

from .thumbnails import IMAGE_TYPES, RAW_TYPES, VIDEO_TYPES


def main():
    # Set limits inside the child (preexec_fn is unsafe in a threaded GTK app).
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_AS, (1024 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    # Glycin uses memory-backed files for decoded pixels (including full photos).
    resource.setrlimit(resource.RLIMIT_FSIZE, (256 * 1024 * 1024,) * 2)
    import gi
    gi.require_version('GdkPixbuf', '2.0')
    from gi.repository import GdkPixbuf

    source, output = map(Path, sys.argv[1:3])
    size = min(360, max(1, int(sys.argv[3])))
    suffix = source.suffix.casefold()
    intermediate = output.with_name('extracted.png')
    if suffix in RAW_TYPES:
        helper = shutil.which('raw-preview')
        if not helper:
            return 1
        subprocess.run([helper, '--thumbnail', str(source), str(intermediate), str(size)],
                       check=True, stdin=subprocess.DEVNULL)
        source = intermediate
    elif suffix in VIDEO_TYPES:
        subprocess.run(['ffmpegthumbnailer', '-i', str(source), '-o', str(intermediate),
                        '-s', str(size), '-q', '8'], check=True, stdin=subprocess.DEVNULL)
        source = intermediate
    elif suffix not in IMAGE_TYPES:
        return 1
    dimensions = GdkPixbuf.Pixbuf.get_file_info(str(source))[1:] if suffix in IMAGE_TYPES else None
    pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(source), size, size, True)
    pixbuf = pixbuf.apply_embedded_orientation()
    keys = ['tEXt::SourceWidth', 'tEXt::SourceHeight'] if dimensions else []
    values = [str(value) for value in dimensions] if dimensions else []
    pixbuf.savev(str(output), 'png', keys, values)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
