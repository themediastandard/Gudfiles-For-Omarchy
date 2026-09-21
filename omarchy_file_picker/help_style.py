"""Compact guide styling, scoped independently from the browser and its dialogs."""

def build_help_css(colors):
    ink, muted = colors['foreground'], colors['light_foreground']
    surface, line = colors['background'], colors['darker_background']
    return f'''
    .files-help {{ background: {surface}; color: {ink}; }}
    .files-help windowhandle.titlebar {{ background: {surface}; border: 0; box-shadow: none; }}
    .files-help .help-heading {{ color: {ink}; padding: 7px 10px; border-bottom: 1px solid {line}; }}
    .files-help .help-title {{ color: {ink}; font-size: 12px; font-weight: 600; }}
    .files-help .help-emblem {{ color: {muted}; }}
    .files-help searchentry {{
      min-height: 25px; padding: 0 7px; border-radius: 4px;
      background: alpha({ink}, 0.035); color: {ink};
      border: 1px solid alpha({ink}, 0.12); box-shadow: none;
    }}
    .files-help searchentry:focus-within {{ border-color: alpha({ink}, 0.4); box-shadow: none; outline: none; }}
    .files-help searchentry text {{ color: {ink}; caret-color: {ink}; outline: none; box-shadow: none; }}
    .files-help searchentry placeholder {{ color: {muted}; opacity: 1; }}
    .files-help .help-nav {{ padding: 12px 6px; border-right: 1px solid {line}; }}
    .files-help .help-eyebrow {{ font-size: 9px; letter-spacing: 0.8px; margin: 0 8px 7px; color: {muted}; }}
    .files-help button {{
      min-height: 25px; padding: 0 8px; border-radius: 4px;
      color: {ink}; background: alpha({ink}, 0.035); border: 1px solid alpha({ink}, 0.12);
      background-image: none; box-shadow: none; text-shadow: none;
    }}
    .files-help button:disabled {{ opacity: 0.5; }}
    .files-help button:focus-visible {{ outline: 1px solid {colors['accent']}; outline-offset: -1px; }}
    .files-help button.flat {{ padding: 0; min-width: 24px; min-height: 24px; border: 0; background: transparent; }}
    .files-help button.help-category {{ padding: 4px 7px; border: 0; background: transparent; min-height: 22px; }}
    .files-help .help-nav-title {{ font-size: 11px; font-weight: 500; }}
    .files-help button:hover {{ background: alpha({ink}, 0.07); }}
    .files-help button.help-category:checked {{ background: alpha({ink}, 0.09); color: {ink}; border: 0; }}
    .files-help button.help-category:checked .help-nav-title {{ font-weight: 650; }}
    .files-help .help-content {{ padding: 16px 20px; }}
    .files-help .help-section-title {{ font-size: 15px; font-weight: 650; }}
    .files-help .help-description {{ font-size: 12px; color: {muted}; }}
    .files-help .help-group-heading {{ color: {muted}; margin-top: 14px; }}
    .files-help .help-group-title {{ font-size: 11px; font-weight: 650; }}
    .files-help .help-card {{ background: transparent; border: 0; border-radius: 0; }}
    .files-help .help-card separator {{ background: alpha({ink}, 0.09); min-height: 1px; margin: 0; }}
    .files-help .help-feature {{ padding: 12px 0; }}
    .files-help .help-feature-title {{ font-size: 12px; font-weight: 650; }}
    .files-help .help-key {{
      font-size: 10px; font-weight: 500; color: {muted};
      background: alpha({ink}, 0.035); border: 1px solid alpha({ink}, 0.12);
      border-bottom-width: 1px; padding: 1px 5px; border-radius: 3px;
    }}
    .files-help .help-footer {{ padding: 5px 12px; border-top: 1px solid {line}; }}
    .files-help .help-footer .help-description {{ font-size: 10px; }}
    .files-help .help-about-title {{ font-size: 20px; font-weight: 650; }}
    .files-help .help-about-card {{ padding: 12px 0; border-top: 1px solid alpha({ink}, 0.09); }}
    .files-help .help-license-text {{ font-size: 11px; color: {muted}; }}
    .files-help button.help-link, .files-help button.help-link:visited {{
      color: {ink}; border: 0; background: transparent; padding: 0; min-height: 24px;
    }}
    .files-help button.help-link:hover {{ color: {ink}; background: alpha({ink}, 0.06); }}
    '''
