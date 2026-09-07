"""Small command entry point; diagnostic/version commands need no display."""
import sys
from . import __version__


def doctor():
    import shutil
    try:
        import gi
        gi.require_version('Gtk', '4.0')
        gi.require_version('Graphene', '1.0')
        from gi.repository import Gtk, Graphene  # noqa: F401
        import cairo  # noqa: F401
    except (ImportError, ValueError) as error:
        print(f'Missing required support: {error}\nInstall python-gobject, python-cairo and gtk4.')
        return 1
    print(f'Gudfiles {__version__}: Python and GTK requirements are available.')
    for command, purpose in [('ffmpeg', 'video conversion and media details'),
                             ('magick', 'image conversion'),
                             ('ffmpegthumbnailer', 'video thumbnails'),
                             ('avahi-browse', 'NAS discovery'),
                             ('paplay', 'action sounds'),
                             ('raw-preview', 'camera RAW preview')]:
        print(f'{purpose}: {"available" if shutil.which(command) else "optional support not installed"}')
    return 0


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if args == ['--version']:
        print(f'Gudfiles {__version__}')
        return 0
    if args == ['--doctor']:
        return doctor()
    if args == ['--check-updates']:
        from .updates import check_for_updates
        result = check_for_updates()
        print(result.message)
        if result.url:
            print(result.url)
        return 1 if result.status == 'error' else 0
    if args in (['--enable-portal'], ['--disable-portal']):
        from .portal_setup import configure
        try:
            print(configure(enable=args == ['--enable-portal']))
        except (OSError, RuntimeError) as error:
            print(str(error), file=sys.stderr)
            return 1
        return 0
    from .picker import main as picker_main
    return picker_main(args)


if __name__ == '__main__':
    raise SystemExit(main())
