from __future__ import annotations

import tomllib
from pathlib import Path


DEFAULT_COLORS = {
    "mode": "light",
    "accent": "#1e66f5",
    "selection": "#ccd0da",
    "muted": "#acb0be",
    "background": "#eff1f5",
    "dark_background": "#e3e4e8",
    "darker_background": "#d7d8dc",
    "lighter_background": "#dce0e8",
    "foreground": "#4c4f69",
    "dark_foreground": "#9ca0b0",
    "light_foreground": "#5c5f77",
    "bright_foreground": "#4c4f69",
    "red": "#d20f39",
}


def load_colors(path: Path | None = None) -> dict[str, str]:
    path = path or Path.home() / ".local/state/omarchy/current/theme/colors.toml"
    colors = DEFAULT_COLORS.copy()
    try:
        with path.open("rb") as handle:
            loaded = tomllib.load(handle)
        colors.update({key: value for key, value in loaded.items() if isinstance(value, str)})
    except (OSError, tomllib.TOMLDecodeError):
        pass
    return colors


def _rgb(color: str) -> tuple[int, ...]:
    return tuple(int(color.lstrip('#')[i:i + 2], 16) for i in (0, 2, 4))


def _mix(ink: str, surface: str, amount: float) -> str:
    return '#%02x%02x%02x' % tuple(round(a * amount + b * (1 - amount))
                                  for a, b in zip(_rgb(ink), _rgb(surface)))


def contrast_ratio(first: str, second: str) -> float:
    def luminance(color):
        channels = [value / 255 for value in _rgb(color)]
        linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in channels]
        return sum(v * weight for v, weight in zip(linear, (0.2126, 0.7152, 0.0722)))
    a, b = sorted((luminance(first), luminance(second)))
    return (b + 0.05) / (a + 0.05)


def _readable(ink: str, surface: str, minimum: float = 4.5) -> str:
    """Retain the hue, deepening only light-theme ink that is too faint."""
    for step in range(101):
        candidate = _mix('#000000', ink, step / 100)
        if contrast_ratio(candidate, surface) >= minimum:
            return candidate
    return '#000000'


def prepare_colors(colors: dict[str, str]) -> dict[str, str]:
    """Map terminal-oriented light palettes to quiet, readable native surfaces.

    The desktop palette is never rewritten. Keep accent fills and media intact;
    use separate ink for small accent text on pale backgrounds.
    """
    c = colors.copy()
    c['accent_ink'], c['error_ink'] = c['accent'], c['red']
    if c.get('mode') == 'light':
        fg, bg = c['foreground'], c['background']
        c['dark_background'] = _mix(fg, bg, 0.035)
        c['darker_background'] = _mix(fg, bg, 0.14)
        c['lighter_background'] = _mix(fg, bg, 0.07)
        c['selection'] = _mix(c['accent'], bg, 0.12)
        text_surface = min((bg, c['selection'], c['lighter_background']),
                           key=lambda color: contrast_ratio('#000000', color))
        secondary = _readable(_mix(fg, bg, 0.70), text_surface)
        c['dark_foreground'] = c['light_foreground'] = c['muted'] = secondary
        c['accent_ink'] = _readable(c['accent'], _mix(c['accent'], bg, 0.22))
        c['error_ink'] = _readable(c['red'], _mix(c['red'], bg, 0.10))
    return c


def label_colors(colors: dict[str, str]) -> dict[str, str]:
    swatches = {'red': '#d96868', 'orange': '#c68b37', 'green': '#579a70',
                'blue': '#598dc8', 'purple': '#a47ac4'}
    if colors.get('mode') == 'light':
        c = prepare_colors(colors)
        surface = min((c['background'], c['selection'], c['lighter_background']),
                      key=lambda color: contrast_ratio('#000000', color))
        return {name: _readable(color, surface) for name, color in swatches.items()}
    return swatches


def build_css(colors: dict[str, str]) -> str:
    colors = prepare_colors(colors)
    swatches = label_colors(colors)
    return f"""
    * {{
      font-family: 'Noto Sans', sans-serif;
      font-size: 14px;
    }}
    window, .picker-root, headerbar {{
      background: {colors['background']};
      color: {colors['foreground']};
    }}
    headerbar {{
      min-height: 46px;
      border-bottom: 1px solid {colors['darker_background']};
      box-shadow: none;
    }}
    headerbar button.header-utility {{
      background: transparent; background-image: none; border: 1px solid transparent;
      color: {colors['light_foreground']}; min-width: 18px; min-height: 18px;
      padding: 6px; margin: 0; border-radius: 7px; box-shadow: none; text-shadow: none;
    }}
    headerbar button.header-utility image {{ -gtk-icon-size: 16px; }}
    headerbar button.header-utility:hover {{ background: alpha({colors['foreground']}, 0.07); color: {colors['foreground']}; }}
    headerbar button.header-utility:active {{ background: alpha({colors['accent']}, 0.14); color: {colors['accent_ink']}; }}
    headerbar button.header-utility:focus-visible {{ outline: 2px solid alpha({colors['accent']}, 0.65); outline-offset: 1px; }}
    headerbar button.header-utility.active {{ color: {colors['accent_ink']}; }}
    headerbar .header-transfer-badge {{
      font-size: 9px; font-weight: 700; min-width: 10px; padding: 0 2px;
      margin-top: -7px; margin-right: -7px; border-radius: 5px;
      background: {colors['background']}; color: {colors['accent_ink']};
      border: 1px solid alpha({colors['accent']}, 0.35);
    }}
    headerbar.compact-header {{ min-height: 30px; padding: 0 4px; }}
    .file-chooser .footer {{ padding: 5px 8px; }}
    .file-chooser .footer button {{
      min-height: 26px; padding: 1px 6px; border-radius: 4px;
      background-image: none; box-shadow: none; text-shadow: none;
    }}
    .file-chooser .footer button.chooser-action {{
      min-height: 22px; min-width: 56px; padding: 0 9px; border-radius: 3px;
      border: 1px solid alpha({colors['foreground']}, 0.14);
      background: alpha({colors['foreground']}, 0.04); color: {colors['foreground']};
      font-size: 12px; font-weight: 500;
      outline-color: {colors['foreground']}; outline-width: 1px;
      outline-offset: 2px; outline-style: none;
    }}
    .file-chooser .footer button.chooser-action:hover {{ background: alpha({colors['foreground']}, 0.09); }}
    .file-chooser .footer button.chooser-action:active {{ background: alpha({colors['foreground']}, 0.14); }}
    .file-chooser .footer button.chooser-action:disabled {{ opacity: 0.4; }}
    .file-chooser .footer button.chooser-action:focus-visible {{ outline-style: solid; }}
    .file-chooser .footer entry {{ min-height: 28px; padding: 1px 8px; border-radius: 4px; }}
    headerbar.compact-header button.header-utility,
    headerbar.compact-header windowcontrols button {{
      min-width: 24px; min-height: 24px; padding: 1px; margin: 0;
      border-radius: 5px;
    }}
    headerbar.compact-header button.header-utility image,
    headerbar.compact-header windowcontrols button image {{ -gtk-icon-size: 14px; }}
    headerbar.compact-header windowcontrols button image,
    headerbar.compact-header windowcontrols button:hover image {{
      min-width: 14px; min-height: 14px; padding: 0; margin: 0;
      background: transparent; border: 0; box-shadow: none;
    }}
    headerbar.compact-header windowcontrols {{ padding: 0; margin: 0; }}
    .toolbar.compact-toolbar {{ padding: 0; border: 0; }}
    button.compact-control, .compact-control > button {{
      min-width: 20px; min-height: 20px; padding: 1px; margin: 0;
      border-radius: 5px;
    }}
    menubutton.compact-control {{ margin: 0; padding: 0; }}
    button.compact-control > image, .compact-control > button image {{ -gtk-icon-size: 12px; }}
    button.compact-control label, .compact-control > button label {{ font-size: 11px; }}
    headerbar.compact-header button.compact-control,
    headerbar.compact-header .compact-control > button {{ min-width: 24px; min-height: 24px; }}
    headerbar.compact-header button.compact-control > image,
    headerbar.compact-header .compact-control > button image {{ -gtk-icon-size: 14px; }}
    .compact-toolbar .path-segment {{ min-height: 28px; padding: 0; margin: 0; }}
    .compact-toolbar .path-segment label {{ font-size: 11px; }}
    entry.compact-location {{ min-height: 20px; padding: 1px 5px; margin: 0; font-size: 11px; }}
    .compact-toolbar .view-switcher {{ border-radius: 5px; }}
    .toolbar-group-divider {{ min-width: 1px; margin: 7px 0;
      background: alpha({colors['foreground']}, 0.14); }}
    headerbar.compact-header button.compact-control,
    headerbar.compact-header .compact-control > button,
    headerbar.compact-header button.header-utility,
    headerbar.compact-header windowcontrols button,
    headerbar.compact-header button.compact-control:hover,
    headerbar.compact-header .compact-control > button:hover,
    headerbar.compact-header button.header-utility:hover,
    headerbar.compact-header windowcontrols button:hover {{
      background: transparent; background-image: none; border: 0;
      border-radius: 0; box-shadow: none; text-shadow: none;
      color: {colors['light_foreground']};
    }}
    headerbar.compact-header button.compact-control.active,
    headerbar.compact-header button.compact-control.active:hover,
    headerbar.compact-header button.header-utility.active,
    headerbar.compact-header button.header-utility.active:hover,
    headerbar.compact-header .compact-control.active > button,
    headerbar.compact-header .compact-control.active > button:hover,
    headerbar.compact-header .compact-control > button:checked {{
      background: transparent; color: {colors['accent_ink']};
    }}
    headerbar.compact-header button:disabled {{ opacity: 0.45; }}
    .files-help windowhandle.titlebar {{ background: {colors['background']}; border: 0; box-shadow: none; }}
    .files-help .help-heading {{ padding: 12px 14px 8px; }}
    .files-help .help-title {{ font-size: 15px; font-weight: 600; }}
    .files-help .help-emblem {{
      color: {colors['light_foreground']}; background: transparent;
      border: 0; padding: 0;
    }}
    .files-help .help-description {{ color: {colors['light_foreground']}; font-size: 12px; }}
    .files-help .help-search-box {{ padding: 0 14px 10px; border-bottom: 1px solid {colors['darker_background']}; }}
    .files-help searchentry {{
      min-height: 28px; padding: 1px 8px; border-radius: 4px;
      background: alpha({colors['foreground']}, 0.035); color: {colors['foreground']};
      border: 1px solid {colors['darker_background']}; box-shadow: none;
    }}
    .files-help searchentry:focus-within {{ border-color: {colors['accent']}; box-shadow: none; }}
    .files-help .help-nav {{ border-right: 1px solid {colors['darker_background']}; padding: 10px 6px; }}
    .files-help .help-eyebrow {{ font-size: 10px; font-weight: 700; letter-spacing: 1px; color: {colors['light_foreground']}; margin: 0 10px 9px; }}
    .files-help button {{ min-height: 26px; padding: 1px 8px; border-radius: 4px;
      background-image: none; box-shadow: none; text-shadow: none; }}
    .files-help button.flat {{ background: transparent; border: 0; padding: 2px; min-height: 24px; min-width: 24px; }}
    .files-help button.help-category {{
      background: transparent; border: 1px solid transparent; border-radius: 4px;
      padding: 4px 6px; min-height: 20px; color: {colors['foreground']};
    }}
    .files-help .help-nav-title {{ font-size: 12px; font-weight: 550; }}
    .files-help button.help-category:hover, .files-help button.flat:hover {{ background: alpha({colors['foreground']}, 0.06); }}
    .files-help button.help-category:checked {{ background: alpha({colors['accent']}, 0.12); color: {colors['accent_ink']}; border-color: alpha({colors['accent']}, 0.18); }}
    .files-help .help-content {{ padding: 14px; }}
    .files-help .help-section-title {{ font-size: 15px; font-weight: 600; }}
    .files-help .help-group-heading {{ color: {colors['accent_ink']}; margin-top: 4px; }}
    .files-help .help-group-title {{ font-size: 12px; font-weight: 650; }}
    .files-help .help-card {{ border: 1px solid {colors['darker_background']}; border-radius: 4px; background: alpha({colors['foreground']}, 0.02); }}
    .files-help .help-card separator {{ background: {colors['darker_background']}; min-height: 1px; margin: 0 14px; }}
    .files-help .help-feature {{ padding: 8px 10px; }}
    .files-help .help-feature-title {{ font-size: 13px; font-weight: 650; }}
    .files-help .help-key {{
      font-size: 10px; font-weight: 600; color: {colors['light_foreground']};
      background: alpha({colors['foreground']}, 0.035); border: 1px solid {colors['darker_background']};
      border-bottom-width: 2px; padding: 2px 6px; border-radius: 5px;
    }}
    .files-help .help-empty {{ padding: 30px 14px; color: {colors['light_foreground']}; }}
    .files-help .help-footer {{ padding: 8px 14px; border-top: 1px solid {colors['darker_background']}; }}
    .files-help .help-about-title {{ font-size: 18px; font-weight: 600; }}
    .files-help .help-about-card {{ padding: 10px; }}
    .files-help .help-license-text {{ color: {colors['light_foreground']}; font-size: 12px; }}
    .files-help button.help-link, .files-help button.help-link:visited {{
      background: transparent; border: 0; padding: 3px 0; min-height: 22px;
      color: {colors['accent_ink']};
    }}
    .files-help button.help-link:hover {{ color: {colors['foreground']}; }}
    .transfer-window .transfer-toolbar {{ padding: 8px 12px; border-bottom: 1px solid {colors['darker_background']}; }}
    .transfer-window .transfer-row {{
      background: alpha({colors['foreground']}, 0.025); border: 1px solid {colors['darker_background']};
      padding: 10px; border-radius: 4px;
    }}
    .transfer-window .transfer-title {{ font-size: 13px; font-weight: 600; }}
    .transfer-window .transfer-subtitle {{ color: {colors['light_foreground']}; font-size: 12px; }}
    .transfer-window .transfer-icon, .transfer-window .transfer-status.running {{ color: {colors['accent_ink']}; }}
    .transfer-window .transfer-status {{ color: {colors['light_foreground']}; font-size: 10px; font-weight: 700; }}
    .transfer-window .transfer-status.failed {{ color: {colors['error_ink']}; }}
    .transfer-window .transfer-status.completed {{ color: {colors['accent_ink']}; }}
    .transfer-window button {{ min-height: 24px; padding: 1px 8px; border-radius: 4px; background-image: none; box-shadow: none; text-shadow: none; }}
    .transfer-window button.flat {{ background: transparent; border: 1px solid transparent; }}
    .transfer-window button.flat:hover {{ background: alpha({colors['foreground']}, 0.07); }}
    .transfer-window button.transfer-action {{
      background: alpha({colors['accent']}, 0.12); color: {colors['accent_ink']};
      border: 1px solid alpha({colors['accent']}, 0.25);
    }}
    .transfer-window button.transfer-action:hover {{ background: alpha({colors['accent']}, 0.22); }}
    .transfer-window button:disabled {{ opacity: 0.45; }}
    .transfer-window progressbar trough {{ min-width: 0; min-height: 4px; padding: 0; background: {colors['darker_background']}; border: 0; border-radius: 3px; }}
    .transfer-window progressbar progress {{ min-width: 0; min-height: 4px; margin: 0; padding: 0; background: {colors['accent']}; border: 0; border-radius: 3px; }}
    .transfer-window .transfer-footer {{ padding: 8px 12px; border-top: 1px solid {colors['darker_background']}; }}
    .transfer-window .transfer-close-box {{ padding: 8px 12px; background: alpha({colors['accent']}, 0.07); border-top: 1px solid {colors['darker_background']}; }}
    .transfer-window headerbar {{ min-height: 32px; padding: 0 8px; }}
    .transfer-window headerbar windowcontrols button {{ min-width: 24px; min-height: 24px; padding: 0; }}
    .transfer-window headerbar windowcontrols button image {{ min-width: 12px; min-height: 12px; padding: 0; -gtk-icon-size: 12px; }}
    .toolbar, .footer, .metadata-strip {{
      background: {colors['background']};
    }}
    .toolbar {{
      padding: 12px 16px;
      border-bottom: 1px solid {colors['darker_background']};
    }}
    .active-filters {{
      background: {colors['background']}; padding: 6px 16px;
      border-bottom: 1px solid {colors['darker_background']};
    }}
    button.active-filter-chip {{
      background: alpha({colors['accent']}, 0.08); background-image: none;
      border: 1px solid alpha({colors['accent']}, 0.22); border-radius: 6px;
      min-height: 24px; padding: 0 8px; box-shadow: none;
    }}
    .active-filter-chip label {{ font-size: 12px; }}
    .active-filter-chip image {{ -gtk-icon-size: 12px; color: {colors['light_foreground']}; }}
    button.active-filter-chip:hover {{ background: alpha({colors['accent']}, 0.16); }}
    button.clear-active-filters {{
      background: transparent; background-image: none; border: 0;
      color: {colors['light_foreground']}; min-height: 24px; padding: 0 4px; font-size: 12px;
    }}
    button.clear-active-filters:hover {{ color: {colors['accent_ink']}; }}
    button.hidden-toggle.active {{ color: {colors['accent_ink']}; background: alpha({colors['accent']}, 0.10); }}
    .footer {{
      padding: 12px 16px;
      border-top: 1px solid {colors['darker_background']};
    }}
    .sidebar {{
      background: {colors['background']};
      color: {colors['foreground']};
      border-right: 0;
      padding: 6px 0;
    }}
    .sidebar-split > separator, .sidebar-split > separator:hover {{
      min-width: 1px;
      background: {colors['darker_background']};
      background-image: none; border: 0; padding: 0; margin: 0;
    }}
    .sidebar-heading {{
      color: {colors['dark_foreground']};
      font-size: 10px;
      font-weight: 400;
      letter-spacing: 1.2px;
      margin: 8px 12px 4px 12px;
    }}
    .sidebar-section {{ margin-top: 12px; }}
    .sidebar-section .sidebar-heading {{ margin-top: 0; }}
    button.sidebar-connect {{
      min-width: 20px; min-height: 20px; padding: 0; margin: 0 8px 2px 0;
      background: transparent; background-image: none; border: 0;
      color: {colors['dark_foreground']}; border-radius: 0;
    }}
    button.sidebar-connect:hover {{ color: {colors['foreground']}; background: {colors['lighter_background']}; }}
    .location-button {{
      min-height: 28px;
      padding: 0 12px;
      font-size: 13px;
      border-radius: 0;
      background: transparent;
      background-image: none;
      color: {colors['foreground']};
      border: 0;
      box-shadow: none;
    }}
    .location-button:hover {{ background: {colors['lighter_background']}; }}
    .sidebar-mount-row .location-button {{ padding-right: 4px; }}
    button.sidebar-unmount {{ min-width: 22px; min-height: 22px; padding: 0; margin: 0 8px 0 2px;
      background: transparent; background-image: none; border: 0; border-radius: 3px;
      color: {colors['light_foreground']}; box-shadow: none; }}
    button.sidebar-unmount image {{ -gtk-icon-size: 12px; }}
    button.sidebar-unmount:hover {{ background: {colors['lighter_background']}; color: {colors['foreground']}; }}
    button.sidebar-unmount:disabled {{ opacity: 0.35; }}
    .location-button.active {{
      background: alpha({colors['foreground']}, 0.07);
      color: {colors['foreground']};
      box-shadow: inset 2px 0 {colors['accent']};
    }}
    .quicklook-card {{
      background: {colors['background']};
      color: {colors['foreground']};
      border-radius: 6px;
      border: 1px solid alpha({colors['foreground']}, 0.15);
      box-shadow: 0 8px 24px alpha(#000000, 0.20);
    }}
    .quicklook-bar {{ padding: 2px 4px; border-bottom: 1px solid {colors['darker_background']}; }}
    .quicklook-title {{ font-size: 13px; font-weight: 400; }}
    .quicklook-bar > box > button,
    .quicklook-bar .rating-controls > button,
    .quicklook-bar .rating-controls > menubutton > button {{
      background: transparent; border: 0; border-radius: 0;
      min-width: 26px; min-height: 26px; padding: 0; margin: 0;
    }}
    .quicklook-bar .rating-controls > button,
    .quicklook-bar .rating-controls > menubutton > button {{ min-width: 22px; }}
    .quicklook-bar .rating-controls > .rating-star {{ font-size: 15px; }}
    .quicklook-content {{ padding: 0; }}
    .quicklook-content textview, .quicklook-content text {{
      background: {colors['background']}; color: {colors['foreground']}; font-family: monospace;
    }}
    .quicklook-caption {{
      color: {colors['light_foreground']}; font-size: 11px; padding: 4px 8px;
      border-top: 1px solid {colors['darker_background']};
    }}
    button {{
      color: {colors['foreground']};
      border-radius: 7px;
      min-height: 34px;
      box-shadow: none;
    }}
    button.suggested-action {{
      background: {colors['accent']};
      color: {button_foreground(colors['accent'])};
      border-color: {colors['accent']};
      font-weight: 700;
    }}
    entry, searchentry, dropdown {{
      background: {colors['background']};
      color: {colors['foreground']};
      border: 1px solid {colors['darker_background']};
      border-radius: 7px;
      min-height: 36px;
      box-shadow: none;
    }}
    entry:focus, searchentry:focus {{
      border-color: {colors['accent']};
      box-shadow: 0 0 0 1px {colors['accent']};
    }}
    .path-segment {{
      background: transparent;
      background-image: none;
      border: 0;
      box-shadow: none;
      padding: 0;
      min-height: 34px;
      color: {colors['light_foreground']};
    }}
    .path-segment:hover {{ background: transparent; }}
    .path-segment.current {{
      font-weight: 700;
      color: {colors['accent_ink']};
    }}
    flowbox {{
      background: {colors['background']};
      padding: 14px;
    }}
    flowboxchild {{
      border-radius: 0;
      padding: 5px;
      border: 1px solid transparent;
    }}
    flowboxchild:hover {{ background: {colors['dark_background']}; }}
    flowbox.file-list {{ padding: 6px 0; }}
    .list-heading {{ padding: 0 11px; background: {colors['background']};
      border-bottom: 1px solid alpha({colors['foreground']}, 0.08); }}
    button.list-heading-button {{ min-height: 24px; padding: 0; margin: 0;
      border: 0; border-radius: 0; background: transparent; box-shadow: none; }}
    button.list-heading-button {{ color: {colors['muted']}; }}
    button.list-heading-button:hover {{ background: transparent; color: {colors['muted']}; }}
    button.list-heading-button.active {{ color: {colors['foreground']}; }}
    button.list-heading-button label {{ font-size: 11px; font-weight: 500; }}
    button.list-heading-button.name-heading {{ box-shadow: inset -1px 0 alpha({colors['foreground']}, 0.12); }}
    button.list-heading-button.column-drag-slot,
    .list-cell.column-drag-slot {{ background: alpha({colors['accent']}, 0.12);
      box-shadow: inset 1px 0 alpha({colors['accent']}, 0.3), inset -1px 0 alpha({colors['accent']}, 0.3); }}
    .column-drag-slot label {{ opacity: 0.45; }}
    .column-drag-ghost {{ background: {colors['background']}; color: {colors['foreground']};
      border: 1px solid {colors['accent_ink']}; border-radius: 4px; padding: 0 7px;
      box-shadow: 0 2px 5px alpha(#000000, 0.18); }}
    .column-drag-ghost label {{ font-size: 11px; font-weight: 600; }}
    .column-drag-ghost .column-drag-grip {{ color: {colors['accent_ink']}; }}
    .list-cell label {{ font-size: 13px; }}
    .list-sort-status {{ font-size: 11px; padding: 3px 11px; color: {colors['muted']}; }}
    .toolbar button.active {{ background: {colors['selection']}; color: {colors['accent_ink']}; }}
    .view-switcher {{ background: {colors['dark_background']}; border-radius: 8px; }}
    .browser-column {{ background: {colors['background']}; border-right: 1px solid {colors['lighter_background']}; }}
    .browser-column:not(.active-column) flowboxchild:selected {{ background: alpha({colors['foreground']}, 0.06); border-color: transparent; }}
    .column-heading {{ padding: 10px 14px; font-size: 12px; font-weight: 600; color: {colors['muted']}; border-bottom: 1px solid {colors['lighter_background']}; }}
    .active-column .column-heading {{ color: {colors['accent_ink']}; }}
    .column-empty {{ padding: 22px 14px; color: {colors['muted']}; }}
    flowbox.column-files {{ padding: 6px 0; }}
    .column-files .rating-badge {{ padding: 0; }}
    flowbox.file-list > flowboxchild {{
      padding: 1px 10px;
      border-radius: 0;
    }}
    .file-list .filename {{ font-size: 13px; }}
    .file-list .muted {{ font-size: 11px; }}
    flowboxchild:selected {{
      background: alpha({colors['accent']}, 0.10);
      border-color: transparent;
      color: {colors['foreground']};
    }}
    .browser-tabs {{ padding: 0; border-bottom: 1px solid alpha({colors['foreground']}, 0.08); }}
    .browser-tab {{
      padding: 1px 3px; border: 0; border-right: 1px solid alpha({colors['foreground']}, 0.08);
      border-radius: 0; background: transparent;
    }}
    .browser-tab:hover {{ background: alpha({colors['foreground']}, 0.04); }}
    .browser-tab.active {{ background: alpha({colors['foreground']}, 0.06); }}
    .browser-tab button, .browser-tabs button.tab-new {{
      background: transparent; background-image: none; border: 0; box-shadow: none;
      text-shadow: none; min-width: 0; min-height: 22px; padding: 0; margin: 0;
      border-radius: 0; color: {colors['light_foreground']};
    }}
    .browser-tab button.tab-label {{ padding: 0 7px 0 4px; }}
    .browser-tab .tab-label label {{ font-size: 12px; font-weight: 400; }}
    .browser-tab.active .tab-label {{ color: {colors['foreground']}; }}
    .browser-tab button.tab-close {{ min-width: 22px; background: transparent; }}
    .browser-tab .tab-close image {{ -gtk-icon-size: 10px; }}
    .browser-tab button.tab-close:hover {{ background: alpha({colors['foreground']}, 0.10); color: {colors['foreground']}; }}
    .browser-tabs button.tab-new {{ min-width: 24px; min-height: 24px; }}
    .browser-tabs .tab-new image {{ -gtk-icon-size: 12px; }}
    .browser-tabs button.tab-new:hover {{ background: alpha({colors['foreground']}, 0.06); color: {colors['foreground']}; }}
    .browser-tabs button:focus-visible {{ outline: 1px solid {colors['accent']}; outline-offset: -1px; }}
    .drop-copy-target {{ box-shadow: inset 0 0 0 2px {colors['accent']}; }}
    .file-copy-drag {{
      background: {colors['background']}; color: {colors['foreground']};
      border: 1px solid {colors['accent']}; border-radius: 8px; padding: 10px 12px;
    }}
    .file-copy-drag image {{ color: {colors['accent_ink']}; }}
    .thumbnail-frame {{
      background: {colors['dark_background']};
      border-radius: 7px;
      min-width: 0;
      min-height: 0;
    }}
    .file-view-status {{
      min-height: 26px; padding: 0 11px;
      border-top: 1px solid alpha({colors['foreground']}, 0.08);
      color: {colors['muted']};
    }}
    .file-view-status label {{ font-size: 11px; }}
    .file-view-status scale {{ padding: 7px 4px; min-height: 0; }}
    .file-view-status scale trough {{ min-height: 2px; background: alpha({colors['foreground']}, 0.15); }}
    .file-view-status scale highlight {{ min-height: 2px; background: alpha({colors['foreground']}, 0.5); }}
    .file-view-status scale slider {{
      min-width: 10px; min-height: 10px; margin: -5px; border-radius: 50%;
      background: {colors['foreground']}; border: 0; box-shadow: none;
    }}
    .file-view-status scale:disabled {{ opacity: 0.35; }}
    .filename {{ color: {colors['foreground']}; }}
    .muted {{ color: {colors['dark_foreground']}; font-size: 12px; }}
    .sidebar-empty {{ font-size: 10px; }}
    .metadata-strip {{
      padding: 10px 16px;
      border-top: 1px solid {colors['darker_background']};
      min-height: 92px;
    }}
    .metadata-title {{ font-size: 15px; font-weight: 700; }}
    .key-hint {{
      font-family: monospace;
      color: {colors['dark_foreground']};
      font-size: 11px;
    }}
    .empty-title {{ font-size: 18px; font-weight: 700; }}
    popover.file-context-menu > contents {{
      background: {colors['background']};
      border: 1px solid {colors['darker_background']};
      border-radius: 6px;
      padding: 0;
      box-shadow: 0 4px 12px alpha(#000000, 0.12);
    }}
    .context-heading {{
      color: {colors['dark_foreground']};
      font-size: 10px;
      font-weight: 600;
      letter-spacing: 0.04em;
      margin: 4px 7px 3px;
    }}
    button.context-action {{
      background: transparent;
      border: 0;
      box-shadow: none;
      padding: 1px 7px;
      border-radius: 3px;
      background-image: none;
      text-shadow: none;
      min-width: 180px;
      min-height: 22px;
    }}
    button.context-action:hover {{ background: {colors['lighter_background']}; }}
    menubutton.context-action {{
      background: transparent;
      border: 0;
      box-shadow: none;
      padding: 0;
      min-width: 180px;
      min-height: 0;
    }}
    menubutton.context-action > button {{
      background: transparent;
      border: 0;
      box-shadow: none;
      padding: 1px 7px;
      border-radius: 3px;
      background-image: none;
      text-shadow: none;
      min-height: 22px;
    }}
    menubutton.context-action > button:hover {{ background: {colors['lighter_background']}; }}
    menubutton.context-action > button:checked {{ background: {colors['lighter_background']}; }}
    .context-action:focus-visible {{ outline: 1px solid {colors['accent']}; outline-offset: -1px; }}
    .context-icon {{ color: {colors['light_foreground']}; }}
    .context-label {{ color: {colors['foreground']}; font-size: 12px; }}
    .context-detail {{ color: {colors['light_foreground']}; font-size: 11px; }}
    .context-arrow {{ color: {colors['dark_foreground']}; }}
    .context-action:disabled label, .context-action:disabled image {{ color: {colors['dark_foreground']}; }}
    .file-context-menu separator {{ margin: 3px 5px; background: {colors['darker_background']}; min-height: 1px; }}
    .trash-page {{ background: {colors['background']}; color: {colors['foreground']}; }}
    .trash-actions {{ padding: 6px 12px; border-bottom: 1px solid {colors['darker_background']}; }}
    .trash-actions label {{ font-size: 12px; }}
    .trash-actions button {{ min-height: 26px; padding: 0 8px; border-radius: 4px;
      background: {colors['dark_background']}; color: {colors['foreground']};
      border: 1px solid {colors['darker_background']};
      background-image: none; box-shadow: none; text-shadow: none; font-size: 12px; }}
    .trash-actions button:hover {{ background: {colors['lighter_background']}; }}
    .trash-actions button:disabled {{ color: {colors['muted']}; opacity: 0.5; }}
    .trash-actions button image {{ -gtk-icon-size: 14px; }}
    .trash-error {{ color: {colors['error_ink']}; padding: 6px 12px; font-size: 12px; }}
    .trash-list {{ background: {colors['background']}; color: {colors['foreground']}; }}
    .trash-list row {{ padding: 7px 8px; border-radius: 3px; }}
    .trash-list row:hover {{ background: {colors['lighter_background']}; }}
    .trash-list row:selected {{ background: {colors['selection']}; color: {colors['foreground']}; }}
    .trash-list row label {{ font-size: 12px; }}
    .trash-list row .dialog-description {{ font-size: 11px; }}
    .nas-button {{ margin-top: 2px; }}
    .update-notice {{
      padding: 3px 8px;
      background: {colors['dark_background']};
      color: {colors['foreground']};
    }}
    .update-notice button {{
      background: transparent; background-image: none; border: 0;
      box-shadow: none; text-shadow: none;
      min-height: 24px;
      padding: 0 6px;
      color: {colors['foreground']};
    }}
    .update-notice button:hover {{ background: {colors['lighter_background']}; }}
    .conversion-notice {{
      background: {colors['dark_background']};
      color: {colors['foreground']};
      border: 1px solid {colors['darker_background']};
      border-radius: 8px;
      padding: 12px 14px;
    }}
    .conversion-success {{ color: {colors['accent_ink']}; }}
    .conversion-notice button {{
      background: transparent;
      border: 0;
      box-shadow: none;
      min-height: 24px;
      min-width: 24px;
      padding: 3px;
    }}
    .rating-controls button, .rating-controls menubutton > button {{
      background: transparent; background-image: none; border: 0; box-shadow: none;
      padding: 0 3px; min-height: 24px; min-width: 20px; border-radius: 5px;
      color: {colors['light_foreground']}; text-shadow: none;
    }}
    .rating-controls button:hover, .rating-controls menubutton > button:hover {{
      background: {colors['lighter_background']};
    }}
    .rating-controls .rating-star {{ font-size: 17px; }}
    .rating-controls .rating-star.active, .creative-filter.active > button {{ color: {colors['accent_ink']}; }}
    .rating-controls .rating-reject.active {{ color: {colors['error_ink']}; background: alpha({colors['red']}, 0.10); }}
    .rating-badge {{
      font-size: 11px; font-weight: 600; color: {colors['foreground']};
      background: alpha({colors['background']}, 0.92); border-radius: 5px; padding: 2px 5px; margin: 3px;
    }}
    .file-list .rating-badge {{ background: transparent; margin: 0; padding: 0 4px; }}
    .rating-badge.rejected {{ color: {colors['error_ink']}; }}
    /* Popovers remain descendants of rating-controls: swatches must outrank
       its generic button foreground, not merely inherit a label color. */
    .label-red, .color-swatch.label-red, .label-red > button, .rating-controls .label-red > button {{ color: {swatches['red']}; }}
    .label-orange, .color-swatch.label-orange, .label-orange > button, .rating-controls .label-orange > button {{ color: {swatches['orange']}; }}
    .label-green, .color-swatch.label-green, .label-green > button, .rating-controls .label-green > button {{ color: {swatches['green']}; }}
    .label-blue, .color-swatch.label-blue, .label-blue > button, .rating-controls .label-blue > button {{ color: {swatches['blue']}; }}
    .label-purple, .color-swatch.label-purple, .label-purple > button, .rating-controls .label-purple > button {{ color: {swatches['purple']}; }}
    popover.compact-popover > contents,
    popover.creative-popover > contents, popover.media-details-popover > contents {{
      background: {colors['background']}; color: {colors['foreground']};
      border: 1px solid {colors['darker_background']}; border-radius: 6px;
      padding: 10px; box-shadow: 0 6px 20px alpha(#000000, 0.14);
    }}
    popover.compact-popover > contents {{ padding: 0; }}
    .compact-popover label {{ font-size: 12px; }}
    .compact-popover button {{ min-height: 26px; padding: 1px 8px; border-radius: 4px;
      background-image: none; box-shadow: none; text-shadow: none; }}
    .compact-popover checkbutton {{ min-height: 22px; padding: 0; }}
    popover.columns-popover > contents {{ border-radius: 0; }}
    .columns-popover .columns-heading {{ font-weight: 600; margin: 2px 0 6px; }}
    .columns-popover checkbutton {{ min-height: 24px; padding: 0 4px; border-radius: 0; }}
    .columns-popover checkbutton:hover {{ background: alpha({colors['foreground']}, 0.05); }}
    .columns-popover checkbutton check {{
      min-width: 12px; min-height: 12px; padding: 0; margin: 0 7px 0 0;
      border: 1px solid alpha({colors['foreground']}, 0.35); border-radius: 0;
      background: transparent; background-image: none; box-shadow: none;
    }}
    .columns-popover checkbutton check:checked {{
      background: {colors['selection']}; color: {colors['accent_ink']};
      border-color: {colors['accent_ink']};
    }}
    .columns-popover checkbutton:disabled {{ opacity: 0.45; }}
    .columns-popover button.columns-reset {{
      margin-top: 6px; min-height: 24px; border-radius: 0;
      border: 1px solid {colors['darker_background']}; background: transparent;
    }}
    .columns-popover button.columns-reset:hover {{ background: {colors['dark_background']}; }}
    .compact-popover searchentry {{ min-height: 28px; padding: 1px 8px; border-radius: 4px; }}
    .creative-heading {{ font-weight: 600; font-size: 14px; }}
    .creative-choice, .color-swatch {{
      background: transparent; background-image: none; border: 1px solid transparent;
      border-radius: 6px; min-height: 28px; min-width: 24px; padding: 2px 8px;
      box-shadow: none; text-shadow: none;
    }}
    .creative-choice {{ color: {colors['foreground']}; }}
    .color-swatch:not(.label-red):not(.label-orange):not(.label-green):not(.label-blue):not(.label-purple) {{ color: {colors['light_foreground']}; }}
    .creative-choice:hover, .color-swatch:hover {{ background: {colors['lighter_background']}; }}
    .creative-choice.active, .color-swatch.active {{
      background: alpha({colors['accent']}, 0.09); border-color: alpha({colors['accent']}, 0.4);
    }}
    .creative-choice.active {{ color: {colors['accent_ink']}; }}
    .color-swatch {{ font-size: 19px; padding: 0 6px; }}
    .hover-scrub-track {{ color: {colors['accent_ink']}; }}
    .media-details-row {{ font-size: 12px; }}
    .media-details-button > button {{
      background: transparent; background-image: none; border: 0; box-shadow: none;
      min-width: 20px; min-height: 20px; padding: 0 3px; color: {colors['light_foreground']};
    }}
    .media-details-button > button:hover {{ background: {colors['lighter_background']}; }}
    .media-details-key {{ color: {colors['light_foreground']}; font-size: 12px; }}
    .media-details-value {{ color: {colors['foreground']}; font-size: 12px; }}
    .error {{ color: {colors['error_ink']}; }}
    separator {{ background: {colors['darker_background']}; }}
    """ + dialog_css(colors) + light_controls_css(colors)


def button_foreground(color):
    """Use dark ink on pastel accents and white ink on deeper accents."""
    try:
        return max(('#111318', '#ffffff'), key=lambda ink: contrast_ratio(ink, color))
    except (ValueError, TypeError, AttributeError):
        return '#ffffff'


def dialog_css(c):
    c = prepare_colors(c)
    muted = c['light_foreground'] if c.get('mode') == 'light' else f"alpha({c['foreground']}, 0.85)"
    return f"""
    window.picker-dialog {{ border-radius: 8px; }}
    .picker-dialog windowhandle.titlebar {{ background: {c['background']}; border: 0; box-shadow: none; }}
    .picker-dialog .dialog-heading {{ padding: 10px 14px 8px; }}
    .picker-dialog .dialog-title {{ color: {c['bright_foreground']}; font-size: 15px; font-weight: 600; }}
    .picker-dialog .dialog-description {{ color: {muted}; font-size: 12px; }}
    .picker-dialog .dialog-body {{ padding: 6px 14px 14px; }}
    .picker-dialog .dialog-footer {{
      padding: 8px 14px; border-top: 1px solid alpha({c['foreground']}, 0.10);
      background: transparent;
    }}
    .picker-dialog button {{ background-image: none; text-shadow: none; box-shadow: none; }}
    .picker-dialog button.flat {{ background: transparent; border: 0; }}
    .picker-dialog button.dialog-close {{
      background: transparent; border: 0; min-width: 24px; min-height: 24px;
      padding: 0; margin: 0; color: alpha({c['foreground']}, 0.7);
      border-radius: 4px;
    }}
    .picker-dialog button.dialog-close:hover {{ background: alpha({c['foreground']}, 0.09); color: {c['foreground']}; }}
    .picker-dialog button.secondary-action, .picker-dialog button.suggested-action,
    .picker-dialog button.destructive-action {{
      min-width: 64px; min-height: 26px; padding: 1px 10px; border-radius: 4px;
      font-weight: 600;
    }}
    .picker-dialog button.secondary-action {{
      background: alpha({c['foreground']}, 0.04); color: {c['foreground']};
      border: 1px solid alpha({c['foreground']}, 0.16);
    }}
    .picker-dialog button.secondary-action:hover {{ background: alpha({c['foreground']}, 0.10); }}
    .picker-dialog button.suggested-action {{
      background: {c['accent']}; color: {button_foreground(c['accent'])}; border: 1px solid transparent;
    }}
    .picker-dialog button.suggested-action:hover {{ background: shade({c['accent']}, 1.08); }}
    .picker-dialog button.destructive-action {{
      background: {c['red']}; color: {button_foreground(c['red'])}; border: 1px solid transparent;
    }}
    .picker-dialog button.destructive-action:hover {{ background: shade({c['red']}, 1.08); }}
    .picker-dialog button:disabled {{ opacity: 0.45; }}
    .picker-dialog button:focus-visible {{ outline: 1px solid {c['accent']}; outline-offset: 1px; }}
    .picker-dialog entry {{
      background: {c['dark_background']}; color: {c['foreground']};
      border: 1px solid alpha({c['foreground']}, 0.20); border-radius: 4px;
      min-height: 28px; padding: 1px 8px; caret-color: {c['accent']};
    }}
    .picker-dialog entry:focus-within {{ border-color: {c['accent']}; box-shadow: none; }}
    .picker-dialog entry.error {{ border-color: {c['red']}; }}
    .picker-dialog entry selection {{ background: alpha({c['accent']}, 0.3); color: {c['bright_foreground']}; }}
    .picker-dialog .dialog-field-label {{ font-size: 12px; font-weight: 500; color: {c['foreground']}; }}
    .picker-dialog .dialog-file-summary {{
      background: transparent; border: 0;
      border-radius: 4px; padding: 6px 0;
    }}
    .picker-dialog .dialog-file-icon {{
      background: transparent; color: {c['light_foreground']}; border-radius: 0; padding: 4px;
    }}
    .picker-dialog .dialog-file-name {{ color: {c['bright_foreground']}; font-size: 13px; font-weight: 500; }}
    .picker-dialog .dialog-section-title {{ color: {muted}; font-size: 11px; font-weight: 700; letter-spacing: 0.06em; }}
    .picker-dialog .dialog-detail-card {{
      border: 1px solid alpha({c['foreground']}, 0.12); border-radius: 4px;
      background: transparent;
    }}
    .picker-dialog .dialog-detail-row {{ padding: 6px 10px; }}
    .picker-dialog .dialog-detail-row.divided {{ border-top: 1px solid alpha({c['foreground']}, 0.08); }}
    .picker-dialog .dialog-detail-key {{ color: {muted}; font-size: 12px; }}
    .picker-dialog .dialog-detail-value {{ color: {c['foreground']}; font-size: 13px; }}
    .picker-dialog .dialog-path-row {{ padding: 6px 10px; }}
    .picker-dialog .dialog-path-row image {{ color: {c['accent_ink']}; }}
    .picker-dialog .dialog-path-row label {{ font-size: 13px; }}
    .picker-dialog .dialog-error {{
      margin: 0 14px 10px; padding: 6px 8px; border-radius: 4px;
      color: {c['error_ink']}; background: alpha({c['red']}, 0.08); font-size: 12px;
    }}
    .picker-dialog .error-detail {{ padding: 8px; font-size: 12px; }}
    .picker-dialog .rename-preview {{
      background: transparent; border: 1px solid alpha({c['foreground']}, 0.12); border-radius: 4px;
    }}
    .picker-dialog .rename-preview-heading {{ padding: 6px 10px; border-bottom: 1px solid alpha({c['foreground']}, 0.10); }}
    .picker-dialog .rename-preview-heading label {{ color: {muted}; font-size: 11px; font-weight: 600; }}
    .picker-dialog .rename-preview-row {{ padding: 6px 10px; border-bottom: 1px solid alpha({c['foreground']}, 0.07); }}
    .picker-dialog .rename-before {{ color: {muted}; font-size: 12px; }}
    .picker-dialog .rename-after {{ color: {c['accent_ink']}; font-size: 12px; }}
    .picker-dialog .rename-status {{ color: {muted}; font-size: 12px; }}
    .picker-dialog .rename-status.error {{ color: {c['error_ink']}; }}
    .picker-dialog .linked {{ background: alpha({c['foreground']}, 0.05); border-radius: 4px; padding: 3px; }}
    .picker-dialog .linked button {{ border: 0; background: transparent; border-radius: 3px; padding: 2px 10px; }}
    .picker-dialog .linked button:checked {{ background: alpha({c['accent']}, 0.15); color: {c['accent_ink']}; }}
    .picker-dialog stackswitcher button {{ min-height: 26px; padding: 1px 10px; border-radius: 4px; }}
    .picker-dialog spinbutton {{
      background: {c['dark_background']}; color: {c['foreground']};
      border: 1px solid alpha({c['foreground']}, 0.20); border-radius: 4px; box-shadow: none;
    }}
    .picker-dialog spinbutton text {{ background: transparent; color: {c['foreground']}; padding: 4px 8px; }}
    .picker-dialog spinbutton button {{
      background: transparent; color: {c['foreground']}; border: 0;
      border-left: 1px solid alpha({c['foreground']}, 0.12); min-width: 24px; min-height: 28px;
    }}
    .picker-dialog spinbutton button:hover {{ background: alpha({c['foreground']}, 0.08); }}
    .picker-dialog button.network-location {{
      background: alpha({c['foreground']}, 0.035); border: 1px solid alpha({c['foreground']}, 0.12);
      border-radius: 4px; padding: 6px 10px;
    }}
    .picker-dialog button.network-location:hover {{ background: alpha({c['accent']}, 0.09); border-color: alpha({c['accent']}, 0.30); }}
    .picker-dialog .network-locations .muted, .picker-dialog .muted {{ color: {muted}; }}
    .picker-dialog .network-heading {{ font-size: 12px; font-weight: 500; }}
    """


def light_controls_css(c):
    if c.get('mode') != 'light':
        return ''
    return f"""
    /* Complete the native control palette, including popup surfaces and states
       which would otherwise retain the desktop GTK theme's colors. */
    .files-help windowhandle.titlebar, .picker-dialog windowhandle.titlebar {{
      background: {c['background']}; color: {c['foreground']};
      border: 0; box-shadow: none;
    }}
    button {{ background-image: none; text-shadow: none; }}
    button {{
      background-color: {c['dark_background']}; border-color: {c['darker_background']};
    }}
    button:hover {{ background-color: {c['lighter_background']}; }}
    button:disabled {{ color: {c['dark_foreground']}; opacity: 0.45; }}
    button:focus-visible, flowboxchild:focus-visible {{
      outline: 2px solid {c['accent_ink']}; outline-offset: -2px;
    }}
    .toolbar button {{ background: transparent; border-color: transparent; }}
    .toolbar button:hover {{ background: {c['lighter_background']}; }}
    .toolbar button.active {{ background: {c['selection']}; color: {c['accent_ink']}; }}
    .toolbar .view-switcher {{ background: {c['dark_background']}; }}
    .toolbar .path-segment:hover {{ background: transparent; }}
    .location-button, .browser-tab button, .browser-tabs button.tab-new,
    button.context-action, menubutton.context-action > button,
    .rating-controls button, .rating-controls menubutton > button,
    .creative-choice, .color-swatch, .quicklook-bar button {{ background: transparent; }}
    .location-button:hover, button.context-action:hover,
    menubutton.context-action > button:hover, menubutton.context-action > button:checked,
    .rating-controls button:hover, .rating-controls menubutton > button:hover,
    .creative-choice:hover, .color-swatch:hover, .quicklook-bar button:hover {{
      background: {c['lighter_background']};
    }}
    .location-button.active {{ background: alpha({c['foreground']}, 0.07); }}
    .creative-choice.active, .color-swatch.active {{ background: {c['selection']}; }}
    .browser-tab button.tab-close {{ background: transparent; }}
    .browser-tab button.tab-close:hover {{ background: alpha({c['foreground']}, 0.17); }}
    entry:focus-within, searchentry:focus-within {{
      border-color: {c['accent']}; outline: none;
      box-shadow: 0 0 0 2px alpha({c['accent']}, 0.14);
    }}
    entry placeholder, searchentry placeholder,
    entry .placeholder, searchentry .placeholder {{ color: {c['dark_foreground']}; opacity: 1; }}
    selection {{ background: {c['selection']}; color: {c['foreground']}; }}
    dropdown > button {{ background: {c['dark_background']}; color: {c['foreground']}; }}
    popover > contents, popover > arrow, tooltip {{
      background: {c['background']}; color: {c['foreground']}; border-color: {c['darker_background']};
    }}
    popover listview, popover listview row {{ background: {c['background']}; color: {c['foreground']}; }}
    popover listview row:hover, popover listview row:selected {{ background: {c['selection']}; color: {c['foreground']}; }}
    scrollbar {{ background: transparent; }}
    scrollbar slider {{ background: alpha({c['foreground']}, 0.25); border: 0; }}
    scrollbar slider:hover {{ background: alpha({c['foreground']}, 0.4); }}
    .quicklook-content video controls.osd {{
      background: alpha({c['background']}, 0.96); color: {c['foreground']};
      border: 1px solid {c['darker_background']}; border-radius: 0;
      padding: 2px 4px; box-shadow: none;
    }}
    .quicklook-content video controls.osd button {{
      background: transparent; border-color: transparent; color: {c['foreground']};
      min-height: 26px; min-width: 26px; padding: 0; border-radius: 0;
    }}
    .quicklook-content video controls.osd button:hover {{ background: {c['lighter_background']}; }}
    .quicklook-content video controls.osd label {{ color: {c['foreground']}; }}
    .quicklook-content video scale trough {{ background: {c['darker_background']}; border-color: transparent; }}
    .quicklook-content video scale highlight {{ background: {c['accent']}; border-color: transparent; }}
    .quicklook-content video scale slider {{ background: {c['accent_ink']}; border-color: {c['background']}; box-shadow: none; }}
    .quicklook-bar > box > button:hover,
    .quicklook-bar .rating-controls > button:hover,
    .quicklook-bar .rating-controls > menubutton > button:hover {{ background: transparent; }}
    .picker-dialog button.suggested-action:hover {{ background: {c['accent']}; }}
    .picker-dialog button.destructive-action:hover {{ background: {c['red']}; }}
    """
