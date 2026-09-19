"""Shared native dialog layout, file summaries and readable detail cards."""
from gi.repository import Gdk, Gio, Gtk, Pango

from .model import file_type


def text_label(text='', css=None, *, selectable=False):
    label = Gtk.Label(label=text, xalign=0, wrap=True, hexpand=True,
                      wrap_mode=Pango.WrapMode.WORD_CHAR, max_width_chars=48,
                      selectable=selectable)
    if css:
        label.add_css_class(css)
    return label


class PickerDialog(Gtk.Dialog):
    """A draggable, bounded dialog with an explicit heading and shared actions.

    Keep Gtk.Dialog responses so Enter, Escape, titlebar close and callers all
    use the same action path. The owner handles safe deferred destruction.
    """
    def __init__(self, owner, title, *, subtitle='', width=500):
        super().__init__(title=title, transient_for=owner, modal=True,
                         use_header_bar=False, destroy_with_parent=True)
        self.add_css_class('picker-dialog')
        self.set_default_size(width, -1)
        self.set_resizable(False)
        self._error_entry = None

        heading = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        heading.add_css_class('dialog-heading')
        copy = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3, hexpand=True)
        self.heading = text_label(title, 'dialog-title')
        self.heading.set_lines(2)
        self.heading.set_ellipsize(Pango.EllipsizeMode.END)
        copy.append(self.heading)
        if subtitle:
            copy.append(text_label(subtitle, 'dialog-description'))
        heading.append(copy)
        self.close_button = Gtk.Button.new_from_icon_name('window-close-symbolic')
        self.close_button.add_css_class('dialog-close')
        self.close_button.set_valign(Gtk.Align.START)
        self.close_button.set_tooltip_text('Close')
        self.close_button.connect('clicked', lambda *_: self.response(Gtk.ResponseType.CANCEL))
        heading.append(self.close_button)
        handle = Gtk.WindowHandle()
        handle.set_child(heading)
        self.set_titlebar(handle)

        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, vexpand=True)
        self.body.add_css_class('dialog-body')
        content = self.get_content_area()
        content.append(self.body)
        self.error_label = text_label('', 'dialog-error')
        self.error_label.add_css_class('error')
        self.error_label.set_visible(False)
        content.append(self.error_label)
        self.footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.footer.add_css_class('dialog-footer')
        self.footer.append(Gtk.Box(hexpand=True))
        content.append(self.footer)
        self.connect('close-request', self._request_close)
        keys = Gtk.EventControllerKey()
        keys.connect('key-pressed', self._key_pressed)
        self.add_controller(keys)

    def _request_close(self, *_):
        self.response(Gtk.ResponseType.CANCEL)
        return True

    def _key_pressed(self, _controller, key, *_):
        if key == Gdk.KEY_Escape:
            self.response(Gtk.ResponseType.CANCEL)
            return True
        return False

    def add_action(self, title, response, *, role='secondary-action', default=False):
        button = Gtk.Button(label=title)
        button.add_css_class(role)
        button.connect('clicked', lambda *_: self.response(response))
        self.footer.append(button)
        if default:
            self.set_default_widget(button)
        return button

    def scroll_body(self, max_height=480):
        """Keep long paths and large selections from pushing actions offscreen."""
        content = self.get_content_area()
        content.remove(self.body)
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER,
                                     vscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
                                     propagate_natural_height=True, max_content_height=max_height)
        scroller.set_child(self.body)
        content.prepend(scroller)
        return scroller

    def set_error(self, message, entry=None):
        self.clear_error()
        self.error_label.set_text(message)
        self.error_label.set_visible(bool(message))
        if entry and message:
            self._error_entry = entry
            entry.add_css_class('error')

    def clear_error(self, *_):
        self.error_label.set_visible(False)
        if self._error_entry:
            self._error_entry.remove_css_class('error')
            self._error_entry = None


def file_icon(path):
    if path.is_symlink():
        return 'emblem-symbolic-link-symbolic'
    if path.is_dir():
        return 'folder-symbolic'
    mime, _ = Gio.content_type_guess(path.name, None)
    return Gio.content_type_get_symbolic_icon(mime)


def file_summary(path=None, *, title='', detail='', icon=None):
    card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    card.add_css_class('dialog-file-summary')
    glyph = icon or (file_icon(path) if path else 'edit-select-all-symbolic')
    image = Gtk.Image.new_from_icon_name(glyph) if isinstance(glyph, str) else Gtk.Image.new_from_gicon(glyph)
    image.set_pixel_size(20)
    plate = Gtk.Box(valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER)
    plate.add_css_class('dialog-file-icon')
    plate.append(image)
    card.append(plate)
    copy = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True, valign=Gtk.Align.CENTER)
    name = Gtk.Label(label=title or path.name or str(path), xalign=0, hexpand=True,
                     ellipsize=Pango.EllipsizeMode.MIDDLE, max_width_chars=32)
    name.add_css_class('dialog-file-name')
    name.set_tooltip_text(name.get_text())
    copy.append(name)
    if not detail and path:
        detail = 'Symbolic link' if path.is_symlink() else file_type(path)
    copy.append(text_label(detail, 'dialog-description'))
    card.append(copy)
    return card


def entry_field(title, entry, hint=''):
    field = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    caption = text_label(title, 'dialog-field-label')
    caption.set_mnemonic_widget(entry)
    entry.update_property([Gtk.AccessibleProperty.LABEL], [title])
    field.append(caption)
    entry.set_hexpand(True)
    field.append(entry)
    if hint:
        field.append(text_label(hint, 'dialog-description'))
    return field


def detail_card(rows):
    card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    card.add_css_class('dialog-detail-card')
    for index, (title, value) in enumerate(rows):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add_css_class('dialog-detail-row')
        if index:
            row.add_css_class('divided')
        key = Gtk.Label(label=title, xalign=0, yalign=0)
        key.set_size_request(100, -1)
        key.add_css_class('dialog-detail-key')
        row.append(key)
        row.append(text_label(str(value), 'dialog-detail-value', selectable=True))
        card.append(row)
    return card


def section(title, child):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    box.append(text_label(title, 'dialog-section-title'))
    box.append(child)
    return box


def path_list(paths, *, limit=100):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    box.add_css_class('dialog-detail-card')
    for path in paths[:limit]:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        row.add_css_class('dialog-path-row')
        glyph = file_icon(path)
        image = Gtk.Image.new_from_icon_name(glyph) if isinstance(glyph, str) else Gtk.Image.new_from_gicon(glyph)
        image.set_pixel_size(16)
        row.append(image)
        name = Gtk.Label(label=path.name or str(path), xalign=0, hexpand=True,
                         ellipsize=Pango.EllipsizeMode.MIDDLE, max_width_chars=36)
        name.set_tooltip_text(str(path))
        row.append(name)
        box.append(row)
    if len(paths) > limit:
        more = text_label(f'… and {len(paths) - limit:,} more', 'dialog-description')
        more.add_css_class('dialog-path-row')
        box.append(more)
    scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER,
                                 vscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
                                 propagate_natural_height=True, max_content_height=180)
    scroller.set_child(box)
    return scroller


def confirmation(owner, title, detail, action, paths, callback, *, destructive=False):
    dialog = PickerDialog(owner, title, subtitle=detail)
    dialog.body.append(file_summary(paths[0]) if len(paths) == 1 else path_list(paths))
    cancel = dialog.add_action('Cancel', Gtk.ResponseType.CANCEL, default=True)
    dialog.add_action(action, Gtk.ResponseType.ACCEPT,
                      role='destructive-action' if destructive else 'suggested-action')
    def response(_dialog, code):
        owner._dismiss_dialog(dialog)
        if code == Gtk.ResponseType.ACCEPT:
            callback()
    dialog.connect('response', response)
    dialog.present()
    cancel.grab_focus()
    return dialog
