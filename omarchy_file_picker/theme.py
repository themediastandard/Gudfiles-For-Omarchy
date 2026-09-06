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
    .toolbar, .footer, .metadata-strip {{
      background: {colors['background']};
    }}
    .toolbar {{
      padding: 12px 16px;
      border-bottom: 1px solid {colors['darker_background']};
    }}
    .footer {{
      padding: 12px 16px;
      border-top: 1px solid {colors['darker_background']};
    }}
    .sidebar {{
      background: {colors['dark_background']};
      border-right: 1px solid {colors['darker_background']};
      padding: 12px 8px;
    }}
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
    button {{
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
      border: 0;
      box-shadow: none;
      padding: 4px 8px;
      min-height: 30px;
      color: {colors['light_foreground']};
    }}
    .path-segment:last-child {{
      font-weight: 700;
      color: {colors['foreground']};
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
    flowboxchild:selected {{
      background: alpha({colors['accent']}, 0.10);
      border-color: {colors['accent']};
      color: {colors['foreground']};
    }}
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
    .file-context-menu contents {{
      background: {colors['background']};
      border: 1px solid {colors['darker_background']};
      border-radius: 9px;
      box-shadow: 0 10px 28px alpha(#000000, 0.24);
    }}
    .context-heading {{
      color: {colors['dark_foreground']};
      font-size: 10px;
      font-weight: 700;
      margin: 5px 7px 2px 7px;
    }}
    .context-action {{
      background: transparent;
      border: 0;
      box-shadow: none;
      padding: 6px 9px;
      min-height: 30px;
    }}
    .context-action:hover {{ background: {colors['lighter_background']}; }}
    .nas-button {{ margin-top: 2px; }}
    .error {{ color: {colors['red']}; }}
    separator {{ background: {colors['darker_background']}; }}
    """
