# Design QA

## Current — cohesive palette, Quick Look and NAS discovery

- Sidebar now uses the same theme background/foreground as the browser. The
  user's initial pure-white request was superseded by a cohesive palette.
- Quick Look uses GTK frame-clock translation/scale/opacity (240 ms), originating
  at the selected tile. Full-image open state inspected at 1200 × 800; automated
  tests sample intermediate opening/closing states and test reversal, selection,
  focus restoration, keyboard isolation, text-entry Space and reduced motion.
- Native tests cover image/text/PDF rendering and the missing-codec fallback.
  Actual audio/video playback is not verified until system codecs are installed.
- NAS dialog has flat themed action buttons, inline validation and an automatic
  discovery list. Live app discovery found an advertised SMB server. The manual
  server-address route and share-selection route are tested without mounting.
- Final NAS appearance verified from `/tmp/picker-nas-native.png`, a native
  WidgetPaintable/renderer capture at 540 × 484 pixels. This captures only the
  dialog, avoiding unrelated desktop authentication overlays. Labels, discovery
  rows, field spacing and both footer actions are fully visible.
- Final checks: 25 unit tests; Quick Look, file-management and live NAS-discovery
  UI smoke tests pass. The installed portal services are active.

Earlier menu-specific evidence follows.

## Current — stock actions and background menu

- Inspected `/tmp/picker-background-complete.png` and
  `/tmp/picker-file-menu-complete.png`, 1500 × 1000 pixels at 1.25 scale.
- Background: New Folder/Text, Paste, Select All, Refresh, Folder, View, Sort.
  File: Open, Rename, clipboard actions, More, Properties, Trash, View/Sort,
  applicable media actions. NAS appears only in the sidebar.
- Disabled Paste is visibly muted. Selected-file menu remains inside the
  1200 × 800 chooser; submenu arrows point inward near its right edge.
- `tests/ui_file_management.py` exercises blank/empty hit-testing, creation,
  collision-safe rename and F2, clipboard copy/cut/paste, single/multi menus,
  properties, bookmarks, view/sort, reload with an open menu, and cancellation
  of the permanent-delete confirmation. All filesystem tests use temporary data.
- Stress testing exposed two lifetime errors: destroying a focused entry before
  Wayland input events drained, and parenting a popover to a disposable tile.
  Dialog destruction is deferred; popovers now use the stable browser stack.
- Final verification: 20 unit tests passed; UI smoke passed twice with the native
  input method. Installed backend Open, Save and folder selection passed, as did
  Open through the public XDG portal. Test automation was cleared afterward.

Earlier evidence below describes superseded menu contents.

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
