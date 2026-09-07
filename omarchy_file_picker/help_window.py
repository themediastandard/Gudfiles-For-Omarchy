"""A compact, searchable native guide, independent of browser/file actions."""
from gi.repository import Gdk, GLib, Gtk, Pango

from .help_catalog import CATEGORIES, FEATURES, matching_features


def text(value, css, *, wrap=False):
    widget = Gtk.Label(label=value, xalign=0, hexpand=True, max_width_chars=1)
    widget.add_css_class(css)
    widget.set_wrap(wrap)
    widget.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    if not wrap:
        widget.set_ellipsize(Pango.EllipsizeMode.END)
    return widget


class HelpWindow(Gtk.Window):
    def __init__(self, owner):
        super().__init__(title='Gudfiles Help', transient_for=owner,
                         application=owner.get_application(), destroy_with_parent=True)
        self.set_default_size(800, 680)
        self.set_size_request(660, 480)
        self.set_hide_on_close(True)
        self.add_css_class('files-help')
        self.category = None
        self.visible_features = []

        heading = Gtk.Box(spacing=14)
        heading.add_css_class('help-heading')
        icon = Gtk.Image.new_from_icon_name('help-browser-symbolic')
        icon.set_pixel_size(26)
        icon.add_css_class('help-emblem')
        heading.append(icon)
        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3, hexpand=True)
        titles.append(text('A little help with Gudfiles', 'help-title'))
        titles.append(text('Find a feature. Learn a shortcut. Make yourself at home.', 'help-description'))
        heading.append(titles)
        self.close_button = Gtk.Button.new_from_icon_name('window-close-symbolic')
        self.close_button.add_css_class('flat')
        self.close_button.set_tooltip_text('Close help (Escape)')
        self.close_button.set_valign(Gtk.Align.CENTER)
        self.close_button.connect('clicked', lambda *_: self.close())
        heading.append(self.close_button)
        handle = Gtk.WindowHandle()
        handle.set_child(heading)
        self.set_titlebar(handle)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_child(root)
        search_box = Gtk.Box()
        search_box.add_css_class('help-search-box')
        self.search = Gtk.SearchEntry(hexpand=True)
        self.search.set_placeholder_text('Find a feature or shortcut…')
        self.search.set_tooltip_text('Search all features (Ctrl+F)')
        self.search.connect('search-changed', self._search_changed)
        search_box.append(self.search)
        root.append(search_box)

        body = Gtk.Box(vexpand=True)
        root.append(body)
        nav_scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=False)
        nav_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        nav_scroll.set_size_request(190, -1)
        nav_scroll.add_css_class('help-nav')
        nav = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        nav.append(text('EXPLORE', 'help-eyebrow'))
        self.nav_buttons = {}
        for key, title, icon_name in [(None, 'All features', 'view-grid-symbolic')] + [
                (group.key, group.title, group.icon) for group in CATEGORIES]:
            button = Gtk.ToggleButton()
            button.add_css_class('help-category')
            if self.nav_buttons:
                button.set_group(self.nav_buttons[None])
            row = Gtk.Box(spacing=9)
            row.append(Gtk.Image.new_from_icon_name(icon_name))
            row.append(text(title, 'help-nav-title'))
            button.set_child(row)
            button.connect('clicked', self._choose_category, key)
            nav.append(button)
            self.nav_buttons[key] = button
        nav.append(Gtk.Box(vexpand=True))
        tip = text('A good first trick\nSelect a file and press Space for Quick Look.',
                   'help-tip', wrap=True)
        nav.append(tip)
        nav_scroll.set_child(nav)
        body.append(nav_scroll)

        self.scroll = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        self.scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self.content.add_css_class('help-content')
        self.scroll.set_child(self.content)
        body.append(self.scroll)

        self.footer = Gtk.Box(spacing=12)
        self.footer.add_css_class('help-footer')
        self.summary = text('', 'help-description')
        self.footer.append(self.summary)
        self.footer.append(Gtk.Label(label='Esc', css_classes=['help-key']))
        self.footer.append(Gtk.Label(label='Close', css_classes=['help-description']))
        root.append(self.footer)
        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect('key-pressed', self._key_pressed)
        self.add_controller(keys)
        self.nav_buttons[None].set_active(True)
        self._render()

    def _key_pressed(self, _controller, key, _code, state):
        if key == Gdk.KEY_Escape:
            self.close()
            return Gdk.EVENT_STOP
        if key == Gdk.KEY_F1 or (state & Gdk.ModifierType.CONTROL_MASK and key in (Gdk.KEY_f, Gdk.KEY_F)):
            self.search.grab_focus()
            return Gdk.EVENT_STOP
        return Gdk.EVENT_PROPAGATE

    def _choose_category(self, button, category):
        self.category = category
        # A category is a fresh browse; typing a query always searches the
        # entire catalog, so features cannot be hidden by an old category.
        self.search.set_text('')
        button.set_active(True)
        self._render()

    def _search_changed(self, *_):
        if self.search.get_text().strip():
            self.category = None
            self.nav_buttons[None].set_active(True)
        self._render()

    def _render(self):
        while child := self.content.get_first_child():
            self.content.remove(child)
        query = self.search.get_text().strip()
        self.visible_features = matching_features(query, self.category)
        groups = [group for group in CATEGORIES if self.category in (None, group.key)]
        title = 'Search results' if query else groups[0].title if self.category else 'Get to know Gudfiles'
        description = ('Matching features from across the app.' if query else
                       groups[0].description if self.category else
                       'Everyday essentials and a few things worth discovering.')
        intro = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        intro.append(text(title, 'help-section-title'))
        intro.append(text(description, 'help-description', wrap=True))
        self.content.append(intro)
        count = len(self.visible_features)
        self.summary.set_text(f'{count} of {len(FEATURES)} features' if query or self.category else
                              f'{len(FEATURES)} features · Made for your everyday workflow')
        if not count:
            empty = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            empty.add_css_class('help-empty')
            empty.append(Gtk.Image(icon_name='system-search-symbolic', pixel_size=32))
            empty.append(text('No features found', 'help-feature-title', wrap=True))
            empty.append(text('Try a shorter search, like “preview”, “NAS” or “Ctrl+V”.',
                              'help-description', wrap=True))
            clear = Gtk.Button(label='Clear search', halign=Gtk.Align.START)
            clear.add_css_class('help-category')
            clear.connect('clicked', lambda *_: self.search.set_text(''))
            empty.append(clear)
            self.content.append(empty)
        for group in groups:
            features = [feature for feature in self.visible_features if feature.category == group.key]
            if not features:
                continue
            section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=9)
            if self.category is None:
                heading = Gtk.Box(spacing=8)
                heading.add_css_class('help-group-heading')
                heading.append(Gtk.Image.new_from_icon_name(group.icon))
                heading.append(text(group.title, 'help-group-title'))
                section.append(heading)
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            card.add_css_class('help-card')
            for index, feature in enumerate(features):
                if index:
                    card.append(Gtk.Separator())
                row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
                row.add_css_class('help-feature')
                top = Gtk.Box(spacing=8)
                top.append(text(feature.title, 'help-feature-title', wrap=True))
                if feature.shortcut:
                    badge = Gtk.Label(label=feature.shortcut, valign=Gtk.Align.START)
                    badge.add_css_class('help-key')
                    top.append(badge)
                row.append(top)
                row.append(text(feature.description, 'help-description', wrap=True))
                card.append(row)
            section.append(card)
            self.content.append(section)
        self.scroll.get_vadjustment().set_value(0)


def show_help(owner):
    window = getattr(owner, 'help_window', None)
    if window is None:
        window = HelpWindow(owner)
        owner.help_window = window
        owner.connect('unrealize', _dispose_help)
    window.present()
    window.search.grab_focus()
    return window


def _dispose_help(owner):
    window = getattr(owner, 'help_window', None)
    if window is not None:
        owner.help_window = None
        # Hide-on-close is useful between visits, but the guide must not keep
        # a finished picker application alive. Release text input before teardown.
        window.set_focus(None)
        window.set_visible(False)
        GLib.idle_add(lambda: window.destroy() or False)
