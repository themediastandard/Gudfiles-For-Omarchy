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


def build_css(colors: dict[str, str]) -> str:
    return f"""
    * {{
      font-family: 'Adwaita Sans', sans-serif;
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
    .transfer-launcher {{
      background: transparent; background-image: none; border: 1px solid {colors['darker_background']};
      min-height: 30px; padding: 0 10px;
    }}
    .transfer-launcher.active {{ color: {colors['accent']}; border-color: alpha({colors['accent']}, 0.4); }}
    .transfer-window .transfer-toolbar {{ padding: 14px 16px; border-bottom: 1px solid {colors['darker_background']}; }}
    .transfer-window .transfer-row {{
      background: alpha({colors['foreground']}, 0.025); border: 1px solid {colors['darker_background']};
      padding: 14px; border-radius: 10px;
    }}
    .transfer-window .transfer-title {{ font-size: 14px; font-weight: 650; }}
    .transfer-window .transfer-subtitle {{ color: {colors['light_foreground']}; font-size: 12px; }}
    .transfer-window .transfer-icon, .transfer-window .transfer-status.running {{ color: {colors['accent']}; }}
    .transfer-window .transfer-status {{ color: {colors['light_foreground']}; font-size: 10px; font-weight: 700; }}
    .transfer-window .transfer-status.failed {{ color: {colors['red']}; }}
    .transfer-window .transfer-status.completed {{ color: {colors['accent']}; }}
    .transfer-window button {{ min-height: 28px; padding: 2px 10px; background-image: none; box-shadow: none; text-shadow: none; }}
    .transfer-window button.flat {{ background: transparent; border: 1px solid transparent; }}
    .transfer-window button.flat:hover {{ background: alpha({colors['foreground']}, 0.07); }}
    .transfer-window button.transfer-action {{
      background: alpha({colors['accent']}, 0.12); color: {colors['accent']};
      border: 1px solid alpha({colors['accent']}, 0.25);
    }}
    .transfer-window button.transfer-action:hover {{ background: alpha({colors['accent']}, 0.22); }}
    .transfer-window button:disabled {{ opacity: 0.45; }}
    .transfer-window progressbar trough {{ min-width: 0; min-height: 4px; padding: 0; background: {colors['darker_background']}; border: 0; border-radius: 3px; }}
    .transfer-window progressbar progress {{ min-width: 0; min-height: 4px; margin: 0; padding: 0; background: {colors['accent']}; border: 0; border-radius: 3px; }}
    .transfer-window .transfer-footer {{ padding: 12px 16px; border-top: 1px solid {colors['darker_background']}; }}
    .transfer-window .transfer-close-box {{ padding: 14px 16px; background: alpha({colors['accent']}, 0.07); border-top: 1px solid {colors['darker_background']}; }}
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
    button.clear-active-filters:hover {{ color: {colors['accent']}; }}
    button.hidden-toggle.active {{ color: {colors['accent']}; background: alpha({colors['accent']}, 0.10); }}
    .footer {{
      padding: 12px 16px;
      border-top: 1px solid {colors['darker_background']};
    }}
    .sidebar {{
      background: {colors['background']};
      color: {colors['foreground']};
      border-right: 1px solid {colors['darker_background']};
      padding: 12px 8px;
    }}
    .sidebar-split > separator {{
      min-width: 5px;
      background: {colors['background']};
      border: 0;
    }}
    .sidebar-split > separator:hover {{ background: alpha({colors['accent']}, 0.35); }}
    .sidebar-heading {{
      color: {colors['dark_foreground']};
      font-size: 12px;
      font-weight: 700;
      margin: 10px 10px 6px 10px;
    }}
    .location-button {{
      min-height: 38px;
      padding: 0 10px;
      border-radius: 7px;
      background: transparent;
      color: {colors['foreground']};
      border: 0;
      box-shadow: none;
    }}
    .location-button:hover {{ background: {colors['lighter_background']}; }}
    .location-button.active {{
      background: {colors['selection']};
      color: {colors['accent']};
    }}
    .quicklook-card {{
      background: {colors['background']};
      color: {colors['foreground']};
      border-radius: 14px;
      border: 1px solid alpha({colors['foreground']}, 0.15);
      box-shadow: 0 18px 48px alpha(#000000, 0.26);
    }}
    .quicklook-bar {{ padding: 10px 14px; border-bottom: 1px solid {colors['darker_background']}; }}
    .quicklook-bar button {{ background: transparent; border: 0; min-width: 28px; }}
    .quicklook-content {{ padding: 12px; }}
    .quicklook-content textview, .quicklook-content text {{
      background: {colors['background']}; color: {colors['foreground']}; font-family: monospace;
    }}
    .quicklook-caption {{ color: {colors['light_foreground']}; font-size: 12px; padding: 10px 16px; }}
    button {{
      color: {colors['foreground']};
      border-radius: 7px;
      min-height: 34px;
      box-shadow: none;
    }}
    button.suggested-action {{
      background: {colors['accent']};
      color: white;
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
      color: {colors['accent']};
    }}
    flowbox {{
      background: {colors['background']};
      padding: 14px;
    }}
    flowboxchild {{
      border-radius: 8px;
      padding: 5px;
      border: 1px solid transparent;
    }}
    flowboxchild:hover {{ background: {colors['dark_background']}; }}
    flowbox.file-list {{ padding: 6px 10px; }}
    .toolbar button.active {{ background: {colors['selection']}; color: {colors['accent']}; }}
    .view-switcher {{ background: {colors['dark_background']}; border-radius: 8px; }}
    .browser-column {{ background: {colors['background']}; border-right: 1px solid {colors['lighter_background']}; }}
    .browser-column:not(.active-column) flowboxchild:selected {{ background: alpha({colors['foreground']}, 0.06); border-color: transparent; }}
    .column-heading {{ padding: 10px 14px; font-size: 12px; font-weight: 600; color: {colors['muted']}; border-bottom: 1px solid {colors['lighter_background']}; }}
    .active-column .column-heading {{ color: {colors['accent']}; }}
    .column-empty {{ padding: 22px 14px; color: {colors['muted']}; }}
    flowbox.column-files {{ padding: 6px; }}
    .column-files .rating-badge {{ padding: 0; }}
    flowbox.file-list > flowboxchild {{
      padding: 1px 6px;
      border-radius: 4px;
    }}
    flowboxchild:selected {{
      background: alpha({colors['accent']}, 0.10);
      border-color: {colors['accent']};
      color: {colors['foreground']};
    }}
    .drop-copy-target {{ box-shadow: inset 0 0 0 2px {colors['accent']}; }}
    .file-copy-drag {{
      background: {colors['background']}; color: {colors['foreground']};
      border: 1px solid {colors['accent']}; border-radius: 8px; padding: 10px 12px;
    }}
    .file-copy-drag image {{ color: {colors['accent']}; }}
    .thumbnail-frame {{
      background: {colors['dark_background']};
      border-radius: 7px;
      min-width: 156px;
      min-height: 98px;
    }}
    .filename {{ color: {colors['foreground']}; }}
    .muted {{ color: {colors['dark_foreground']}; font-size: 12px; }}
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
      border-radius: 10px;
      padding: 0;
      box-shadow: 0 4px 14px alpha(#000000, 0.16);
    }}
    .context-heading {{
      color: {colors['dark_foreground']};
      font-size: 10px;
      font-weight: 700;
      letter-spacing: 0.08em;
      margin: 5px 9px 4px 9px;
    }}
    button.context-action {{
      background: transparent;
      border: 0;
      box-shadow: none;
      padding: 4px 9px;
      min-width: 200px;
      min-height: 24px;
    }}
    button.context-action:hover {{ background: {colors['lighter_background']}; }}
    menubutton.context-action {{
      background: transparent;
      border: 0;
      box-shadow: none;
      padding: 0;
      min-width: 200px;
      min-height: 0;
    }}
    menubutton.context-action > button {{
      background: transparent;
      border: 0;
      box-shadow: none;
      padding: 4px 9px;
      min-height: 24px;
    }}
    menubutton.context-action > button:hover {{ background: {colors['lighter_background']}; }}
    menubutton.context-action > button:checked {{ background: {colors['lighter_background']}; }}
    .context-action:focus-visible {{ outline: 2px solid {colors['accent']}; outline-offset: -2px; }}
    .context-icon {{ color: {colors['light_foreground']}; }}
    .context-label {{ color: {colors['foreground']}; font-size: 13px; }}
    .context-detail {{ color: {colors['light_foreground']}; font-size: 11px; }}
    .context-arrow {{ color: {colors['dark_foreground']}; }}
    .context-action:disabled label, .context-action:disabled image {{ color: {colors['dark_foreground']}; }}
    .file-context-menu separator {{ margin: 5px 4px; }}
    .nas-button {{ margin-top: 2px; }}
    .conversion-notice {{
      background: {colors['dark_background']};
      color: {colors['foreground']};
      border: 1px solid {colors['darker_background']};
      border-radius: 8px;
      padding: 12px 14px;
    }}
    .conversion-success {{ color: {colors['accent']}; }}
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
    .rating-controls .rating-star.active, .creative-filter.active > button {{ color: {colors['accent']}; }}
    .rating-controls .rating-reject.active {{ color: {colors['red']}; background: alpha({colors['red']}, 0.10); }}
    .rating-badge {{
      font-size: 11px; font-weight: 600; color: {colors['foreground']};
      background: alpha({colors['background']}, 0.92); border-radius: 5px; padding: 2px 5px; margin: 3px;
    }}
    .file-list .rating-badge {{ background: transparent; margin: 0; padding: 0 4px; }}
    .rating-badge.rejected {{ color: {colors['red']}; }}
    /* Popovers remain descendants of rating-controls: swatches must outrank
       its generic button foreground, not merely inherit a label color. */
    .label-red, .color-swatch.label-red, .label-red > button, .rating-controls .label-red > button {{ color: #d96868; }}
    .label-orange, .color-swatch.label-orange, .label-orange > button, .rating-controls .label-orange > button {{ color: #c68b37; }}
    .label-green, .color-swatch.label-green, .label-green > button, .rating-controls .label-green > button {{ color: #579a70; }}
    .label-blue, .color-swatch.label-blue, .label-blue > button, .rating-controls .label-blue > button {{ color: #598dc8; }}
    .label-purple, .color-swatch.label-purple, .label-purple > button, .rating-controls .label-purple > button {{ color: #a47ac4; }}
    popover.creative-popover > contents, popover.media-details-popover > contents {{
      background: {colors['background']}; color: {colors['foreground']};
      border: 1px solid {colors['darker_background']}; border-radius: 10px;
      padding: 16px; box-shadow: 0 6px 20px alpha(#000000, 0.14);
    }}
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
    .creative-choice.active {{ color: {colors['accent']}; }}
    .color-swatch {{ font-size: 19px; padding: 0 6px; }}
    .hover-scrub-track {{ color: {colors['accent']}; }}
    .media-details-row {{ font-size: 12px; }}
    .media-details-button > button {{
      background: transparent; background-image: none; border: 0; box-shadow: none;
      min-width: 20px; min-height: 20px; padding: 0 3px; color: {colors['light_foreground']};
    }}
    .media-details-button > button:hover {{ background: {colors['lighter_background']}; }}
    .media-details-key {{ color: {colors['light_foreground']}; font-size: 12px; }}
    .media-details-value {{ color: {colors['foreground']}; font-size: 12px; }}
    .error {{ color: {colors['red']}; }}
    separator {{ background: {colors['darker_background']}; }}
    """ + dialog_css(colors)


def button_foreground(color):
    """Use dark ink on pastel accents and white ink on deeper accents."""
    try:
        rgb = [int(color.lstrip('#')[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in rgb]
        luminance = sum(v * weight for v, weight in zip(linear, (0.2126, 0.7152, 0.0722)))
        return '#111318' if luminance > 0.179 else '#ffffff'
    except (ValueError, TypeError):
        return '#ffffff'


def dialog_css(c):
    muted = c['light_foreground'] if c.get('mode') == 'light' else f"alpha({c['foreground']}, 0.85)"
    return f"""
    window.picker-dialog {{ border-radius: 14px; }}
    .picker-dialog .dialog-heading {{ padding: 24px 24px 12px; }}
    .picker-dialog .dialog-title {{ color: {c['bright_foreground']}; font-size: 22px; font-weight: 700; }}
    .picker-dialog .dialog-description {{ color: {muted}; font-size: 12px; }}
    .picker-dialog .dialog-body {{ padding: 10px 24px 24px; }}
    .picker-dialog .dialog-footer {{
      padding: 16px 24px; border-top: 1px solid alpha({c['foreground']}, 0.10);
      background: alpha({c['foreground']}, 0.025);
    }}
    .picker-dialog button {{ background-image: none; text-shadow: none; box-shadow: none; }}
    .picker-dialog button.flat {{ background: transparent; border: 0; }}
    .picker-dialog button.dialog-close {{
      background: transparent; border: 0; min-width: 28px; min-height: 28px;
      padding: 3px; margin: -3px -5px 0 0; color: alpha({c['foreground']}, 0.7);
      border-radius: 7px;
    }}
    .picker-dialog button.dialog-close:hover {{ background: alpha({c['foreground']}, 0.09); color: {c['foreground']}; }}
    .picker-dialog button.secondary-action, .picker-dialog button.suggested-action,
    .picker-dialog button.destructive-action {{
      min-width: 82px; min-height: 36px; padding: 2px 16px; border-radius: 8px;
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
    .picker-dialog button:focus-visible {{ outline: 2px solid {c['accent']}; outline-offset: 3px; }}
    .picker-dialog entry {{
      background: {c['dark_background']}; color: {c['foreground']};
      border: 1px solid alpha({c['foreground']}, 0.20); border-radius: 8px;
      min-height: 42px; padding: 2px 12px; caret-color: {c['accent']};
    }}
    .picker-dialog entry:focus-within {{ border-color: {c['accent']}; box-shadow: 0 0 0 2px alpha({c['accent']}, 0.14); }}
    .picker-dialog entry.error {{ border-color: {c['red']}; }}
    .picker-dialog entry selection {{ background: alpha({c['accent']}, 0.3); color: {c['bright_foreground']}; }}
    .picker-dialog .dialog-field-label {{ font-size: 13px; font-weight: 600; color: {c['foreground']}; }}
    .picker-dialog .dialog-file-summary {{
      background: alpha({c['foreground']}, 0.035); border: 1px solid alpha({c['foreground']}, 0.10);
      border-radius: 10px; padding: 16px;
    }}
    .picker-dialog .dialog-file-icon {{
      background: alpha({c['accent']}, 0.12); color: {c['accent']}; border-radius: 10px; padding: 12px;
    }}
    .picker-dialog .dialog-file-name {{ color: {c['bright_foreground']}; font-size: 15px; font-weight: 600; }}
    .picker-dialog .dialog-section-title {{ color: {muted}; font-size: 11px; font-weight: 700; letter-spacing: 0.06em; }}
    .picker-dialog .dialog-detail-card {{
      border: 1px solid alpha({c['foreground']}, 0.12); border-radius: 10px;
      background: alpha({c['foreground']}, 0.025);
    }}
    .picker-dialog .dialog-detail-row {{ padding: 12px 14px; }}
    .picker-dialog .dialog-detail-row.divided {{ border-top: 1px solid alpha({c['foreground']}, 0.08); }}
    .picker-dialog .dialog-detail-key {{ color: {muted}; font-size: 12px; }}
    .picker-dialog .dialog-detail-value {{ color: {c['foreground']}; font-size: 13px; }}
    .picker-dialog .dialog-path-row {{ padding: 10px 14px; }}
    .picker-dialog .dialog-path-row image {{ color: {c['accent']}; }}
    .picker-dialog .dialog-path-row label {{ font-size: 13px; }}
    .picker-dialog .dialog-error {{
      margin: 0 24px 18px; padding: 10px 12px; border-radius: 8px;
      color: {c['red']}; background: alpha({c['red']}, 0.08); font-size: 12px;
    }}
    .picker-dialog .error-detail {{ padding: 14px; font-size: 13px; }}
    .picker-dialog .rename-preview {{
      background: alpha({c['foreground']}, 0.025); border: 1px solid alpha({c['foreground']}, 0.12); border-radius: 10px;
    }}
    .picker-dialog .rename-preview-heading {{ padding: 10px 14px; border-bottom: 1px solid alpha({c['foreground']}, 0.10); }}
    .picker-dialog .rename-preview-heading label {{ color: {muted}; font-size: 11px; font-weight: 600; }}
    .picker-dialog .rename-preview-row {{ padding: 10px 14px; border-bottom: 1px solid alpha({c['foreground']}, 0.07); }}
    .picker-dialog .rename-before {{ color: {muted}; font-size: 12px; }}
    .picker-dialog .rename-after {{ color: {c['accent']}; font-size: 12px; }}
    .picker-dialog .rename-status {{ color: {muted}; font-size: 12px; }}
    .picker-dialog .rename-status.error {{ color: {c['red']}; }}
    .picker-dialog .linked {{ background: alpha({c['foreground']}, 0.05); border-radius: 8px; padding: 3px; }}
    .picker-dialog .linked button {{ border: 0; background: transparent; border-radius: 6px; padding: 3px 14px; }}
    .picker-dialog .linked button:checked {{ background: alpha({c['accent']}, 0.15); color: {c['accent']}; }}
    .picker-dialog spinbutton {{
      background: {c['dark_background']}; color: {c['foreground']};
      border: 1px solid alpha({c['foreground']}, 0.20); border-radius: 7px; box-shadow: none;
    }}
    .picker-dialog spinbutton text {{ background: transparent; color: {c['foreground']}; padding: 4px 8px; }}
    .picker-dialog spinbutton button {{
      background: transparent; color: {c['foreground']}; border: 0;
      border-left: 1px solid alpha({c['foreground']}, 0.12); min-width: 24px; min-height: 28px;
    }}
    .picker-dialog spinbutton button:hover {{ background: alpha({c['foreground']}, 0.08); }}
    .picker-dialog button.network-location {{
      background: alpha({c['foreground']}, 0.035); border: 1px solid alpha({c['foreground']}, 0.12);
      border-radius: 9px; padding: 12px 14px;
    }}
    .picker-dialog button.network-location:hover {{ background: alpha({c['accent']}, 0.09); border-color: alpha({c['accent']}, 0.30); }}
    .picker-dialog .network-locations .muted, .picker-dialog .muted {{ color: {muted}; }}
    .picker-dialog .network-heading {{ font-size: 13px; font-weight: 600; }}
    """
