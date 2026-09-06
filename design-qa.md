# Design QA

## Latest correction — context-menu polish

The previous pass missed raised submenu rows and a submenu extending beyond
the chooser. Its acceptance statements below describe the earlier pass, not
the corrected appearance.

- Verified capture: `/tmp/picker-menu-polished-final.png` (1500 × 1000 pixels,
  1200 × 800 logical viewport, 1.25 scale).
- Detail: `/tmp/picker-menu-detail.png`.
- Fixed the overly broad `contents` CSS selector: it was styling internal GTK
  button content as a popup surface. Only the popover's direct contents now
  receive borders and shadows.
- Flat 32-pixel action rows, centered labels/icons, lighter popup shadows,
  and compact trailing size values replace the large stacked controls.
- Submenus open left near the right edge; disclosure arrows match the direction.
- Captured and inspected the final open submenu: all options are visible,
  without raised inner panels or truncated size labels.
- GTK smoke check passed for submenu callback activation, dismissal, reload,
  and the background context. Media commands and portal protocol are unchanged.

## Earlier review (superseded)

## Comparison target

- Source visual truth: `/tmp/omarchy-picker-context-final.png`.
- Implementation: `/tmp/omarchy-picker-organized-final.png`.
- Open-submenu evidence: `/tmp/omarchy-picker-organized-submenu-3.png`.
- Full comparison: `/tmp/omarchy-picker-menu-before-after.png`.
- Focused comparison: `/tmp/omarchy-picker-menu-focus-comparison.png`.
- State: image selected with its right-click menu open.
- Viewport: 1200 × 800 logical pixels at 1.25 display scale.
- Source and implementation: 1500 × 1000 pixels. No density normalization
  was required because both captures use the same viewport and scale.

## Findings

No actionable P0, P1, or P2 differences remain.

- Fonts and typography: the existing Adwaita Sans hierarchy is preserved;
  section title, action labels, and submenu details have distinct optical weight.
- Spacing and layout rhythm: the menu is shorter and uses consistent 34-pixel
  rows, separators, padding, radius, and elevation. Cascading menus align to the
  triggering row and stay visually attached to the first level.
- Colors and visual tokens: background, border, muted text, hover surfaces, and
  symbolic icons use the active Omarchy theme tokens.
- Image quality and asset fidelity: file thumbnails are unchanged; all action
  icons come from the installed Adwaita symbolic icon set and render sharply.
- Copy and content: every original capability remains reachable. Size choices
  now explain their longest-edge dimensions and conversions say they create a
  new copy.

The focused comparison was required because the action labels and grouping are
too small to judge confidently in the full 1200 × 800 view.

## Comparison history

### Iteration 1 — baseline

- [P2] The original action sheet placed resize and format choices into dense
  horizontal rows, forcing the user to scan unrelated operations together.
- [P2] Actions lacked consistent icons and the size values did not explain that
  they apply to the longest edge.

### Fixes applied

- Kept New Folder, New Text File, and Connect to NAS directly accessible.
- Moved image resize, image conversion, and video conversion choices into
  cascading submenus that only appear for the relevant file type.
- Added standard symbolic icons, right-facing disclosure indicators, and concise
  supporting details for submenu choices.

### Post-fix evidence

- `/tmp/omarchy-picker-menu-focus-comparison.png` shows the reduced top-level
  density and clearer hierarchy.
- `/tmp/omarchy-picker-organized-submenu-3.png` shows the open Resize Image menu
  with Small, Medium, and Large choices aligned beside the parent action.

## Interaction verification

- The top-level menu remains keyboard-focusable through native GTK buttons.
- Resize and conversion callbacks still use the existing validated media actions.
- Background, image, and video contexts conditionally expose only relevant rows.
- Portal selection behavior is unchanged by the context-menu refactor.

final result: passed
