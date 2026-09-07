# Omarchy File Picker

## Purpose

Provide a fast, visual, theme-aware Open/Save dialog for Omarchy and expose it
as the desktop's XDG FileChooser portal backend.

## Current state

- Native GTK 4 picker with grid, list and Finder-style column layouts, selected
  through a compact three-button toolbar group or the View context submenu.
- Column view opens a selected folder into an adjacent column, retains the
  ancestor trail, and scrolls horizontally without growing the window. Left/
  Right move between columns; each column has independent vertical scrolling.
  The active column owns selection, current-directory actions and metadata;
  ancestor selections are muted. Multi-select, rubber-band selection, labels,
  filters, file operations and Space preview use the shared interaction paths.
- Standalone browsing runs in explorer mode: footer hidden, normal default-app
  file opening without quitting, and Escape clears selection. The preview strip
  remains. Portal requests, CLI `--result`, folder picking and Save modes retain
  picker footer controls and result semantics.
- List view uses compact 32-pixel rows with no inter-row gap; grid spacing is
  unchanged. Native range and individual selection remain supported.
- Standalone Open defaults to multi-selection with native Shift-click ranges,
  Ctrl-click toggles and Ctrl+A. `--single` opts out; portal caller constraints
  and single-destination Save behavior remain authoritative.
- Blank-background drags select intersecting files in all three views with a
  theme-colored rectangle, Shift-add, Ctrl-toggle, edge scrolling and Escape
  restoration. File-origin click gestures remain native GTK.
- Image and cached video thumbnails, selection metadata, search, file filters,
  multi-select, folder selection, Open, Save, and SaveFiles modes.
- Video grid/metadata thumbnails support silent hover-scrubbing with delayed
  entry, a thin position indicator, background decoding and poster restoration.
- Selection details asynchronously show available media resolution, FPS, codec,
  duration, bit depth, audio and camera/EXIF values in a compact information card.
- Local stars/color/rejected annotations appear as small badges and compact
  controls in the metadata strip and Quick Look. Keys 0–5/X work outside text
  entry; toolbar star filters by rated/rejected, minimum rating and color.
  Folders remain navigable; filtered preview culling advances or closes cleanly.
- Multi-selection F2/Batch Rename opens a styled Before/After preview with
  pattern/replace modes, sequence start/padding and preserved extensions.
  Preview is debounced/latest-only offthread; apply revalidates before mutation.
- Compact context actions create folders and text files; cascading media menus
  expose resize presets and format conversions without replacing originals.
- Conversion completion uses one dismissible in-window notification, expiring
  after eight seconds, without a modal dialog or duplicate system notification.
- New Text File creates and selects an empty `untitled.txt` immediately, with
  numbered collision-safe names and no naming dialog. Rename remains available.
- Context-menu surfaces use scoped GTK CSS, compact flat rows, and inward
  submenu placement near the chooser's right edge.
- File and background menus include rename, clipboard file operations,
  confirmed trash/permanent deletion, properties, bookmarks, view and sort.
  NAS connection is sidebar-only. Rename and paste never overwrite collisions.
- SMB/NFS NAS connection dialog backed by Gio/GVfs with native credential
  prompts; mounted shares are refreshed into the Devices sidebar.
- Reads the active Omarchy `colors.toml` on every launch.
- User-local portal installation with GTK retained as the fallback backend.
- Sidebar uses the same application background, not a contrasting white panel.
- Native draggable sidebar divider with a 280-pixel minimum and 300-pixel default,
  older narrower saved widths clamped on load, scrollable places,
  and debounced width persistence without reloading files or clearing selection.
- Hidden-file visibility uses open/concealed eye icons, an active state and Ctrl+H.
- Active search, file-type, rating, color and hidden-file settings appear as
  removable chips below the toolbar. Clear all resets them; the strip hides
  when inactive and scrolls horizontally instead of growing for long labels.
- Mouse context menus preserve browser-relative pointer coordinates. Only
  keyboard-opened menus use the selected row/tile's center as their anchor.
- Breadcrumbs scroll within a bounded toolbar viewport; long metadata, type,
  sidebar and selection labels ellipsize instead of growing the window.
- Breadcrumbs are connected chevron buttons with matching notch hit tests and
  a highlighted current folder. Wheel input scrolls the trail horizontally,
  never navigates folders. File rows, breadcrumbs and metadata paths do not
  show full-path hover tooltips.
- In-window Quick Look expands from the selected tile on Space and contracts
  on Space/Escape. Includes images, bounded read-only text, first-page PDFs,
  adjacent-file browsing, reduced motion and optional GStreamer media playback.
- Image previews support pointer-anchored scroll zoom from fit to 8×, bounded
  drag panning and double-click to fit. Each new image starts fitted. Drawing
  is clipped inside a zero-request widget; the decoded texture remains bounded
  to 1800×1400. Loading uses a spinner instead of the generic preview icon.
- Installed GStreamer good/bad/ugly/libav codecs; generated H.264/AAC, HEVC/AAC,
  ProRes/PCM, VP9/Opus and AV1/AAC clips verify decoding, play, pause, seek,
  resume and stop on preview close. Actual user media and audible output remain
  separate manual checks.
- Selection previews occupy a reserved 113-pixel strip. Neither the strip's
  content nor the Quick Look overlay participates in window size requests;
  long titles and metadata ellipsize with full values available in tooltips.
- NAS dialog uses flat theme-colored controls, automatically searches Avahi/
  GVfs network advertisements, and offers explicit SMB share browsing, Refresh,
  saved/mounted locations, inline errors and cancellable mounting.
- Mounted-device clicks and successful NAS connections verify the local path
  on a worker thread, recover a missing GVfs FUSE bridge when available, and
  report unavailable folders. Credential prompts belong to the NAS dialog.

## Architecture

- `omarchy_file_picker/picker.py` — native chooser UI and result protocol.
- `omarchy_file_picker/portal.py` — XDG FileChooser D-Bus backend.
- `omarchy_file_picker/model.py` — request parsing, filters, filesystem helpers.
- `omarchy_file_picker/actions.py` — validated media commands, output naming,
  and NAS address normalization.
- `omarchy_file_picker/file_actions.py` — filesystem operations and sorting.
- `omarchy_file_picker/file_management.py` — file dialogs, clipboard, shared
  GTK bookmarks and persisted display preferences.
- `omarchy_file_picker/theme.py` — active Omarchy palette to GTK CSS.
- `omarchy_file_picker/quicklook.py` — frame-clock animation and preview loading.
- `omarchy_file_picker/image_preview.py` — clipped image zoom and pan controllers.
- `omarchy_file_picker/hover_scrub.py` — bounded silent thumbnail extraction/cache.
- `omarchy_file_picker/media_details.py` — asynchronous media/EXIF probing and card.
- `omarchy_file_picker/ratings.py` / `creative.py` — local annotation store and controls.
- `omarchy_file_picker/batch_rename.py` — preview planning, no-overwrite apply and dialog.
- `omarchy_file_picker/breadcrumbs.py` — chevron drawing/allocation and wheel handling.
- `omarchy_file_picker/columns.py` — adjacent directory columns and active selection/focus.
- `omarchy_file_picker/drag_selection.py` — background selection and edge scrolling.
- `omarchy_file_picker/network.py` / `network_ui.py` — bounded service discovery
  and explicit server/share browsing in the NAS dialog.
- `data/` — user-local portal, D-Bus, desktop, and systemd templates.
- `install.sh` / `uninstall.sh` — reversible user installation.

## Development

```bash
python -m unittest discover -v
PYTHONPATH=. python tests/ui_file_management.py
PYTHONPATH=. python tests/ui_quicklook.py
PYTHONPATH=. python tests/ui_image_zoom.py
PYTHONPATH=. python tests/ui_hover_scrub.py
PYTHONPATH=. python tests/ui_media_details.py
PYTHONPATH=. python tests/ui_creative.py
PYTHONPATH=. python tests/ui_label_colors.py
PYTHONPATH=. python tests/ui_active_filters.py
PYTHONPATH=. python tests/ui_breadcrumbs.py
PYTHONPATH=. python tests/ui_columns.py
PYTHONPATH=. python tests/ui_batch_rename.py
PYTHONPATH=. python tests/ui_video_playback.py
PYTHONPATH=. python tests/ui_preview_geometry.py
PYTHONPATH=. python tests/ui_nas.py
PYTHONPATH=. python tests/ui_layout.py
PYTHONPATH=. python tests/ui_selection.py
PYTHONPATH=. python tests/ui_sidebar_menu.py
PYTHONPATH=. python tests/ui_explorer.py
PYTHONPATH=. python tests/ui_drag_selection.py
PYTHONPATH=. python tests/ui_conversion_notice.py
PYTHONPATH=. python tests/ui_mounts.py
./bin/omarchy-file-picker --demo ~/Pictures
./install.sh
```

After installation, portal routing is verified with:

```bash
systemctl --user status omarchy-file-picker-portal.service
gdbus introspect --session \
  --dest org.freedesktop.impl.portal.desktop.omarchy.FilePicker \
  --object-path /org/freedesktop/portal/desktop
```

## Decisions and constraints

- No files under `/usr/share/omarchy` are modified.
- The implementation depends only on Omarchy's existing GTK 4/PyGObject stack.
- PDF preview uses optional Poppler GI/Cairo. Media playback needs GStreamer
  codecs; missing dependencies produce an inline explanation. Discovery uses
  the existing Avahi tools/GVfs and never brute-force scans a network.
- The picker defaults to app-local `GSK_RENDERER=gl` before GTK initialization,
  respecting explicit overrides. Vulkan video QA produced an allocation warning
  and GTK rendering crash; all five codec fixtures pass with OpenGL. No global
  graphics configuration is changed. Codec packages require separate privileged
  installation and are not installed by `install.sh`.
- Media actions use the ImageMagick and FFmpeg packages already shipped in the
  current Omarchy environment; NAS access uses GVfs SMB/NFS support.
- Hover uses 48 sampled positions, a 220ms delay, one worker and a 72-frame/
  12MiB memory LRU, with subprocess deadlines and stale-result rejection. It
  never writes the source or a disk frame cache. Metadata uses one worker plus
  one latest pending request, a stat-keyed cache and bounded parsing.
- Annotations live in user-local `ratings.sqlite3`, with serialized SQLite
  read/modify/write transactions. No embedded media/XMP writes. Picker renames
  and confirmed cut/paste moves migrate annotations (including partial success
  and folder descendants); external path changes are not tracked.
- Batch tokens are `{name}`, `{n}`, `{date}`; date means modification date.
  `renameat2(RENAME_NOREPLACE)` is required, with no overwrite-prone fallback.
  Duplicate/existing targets and swaps are rejected; failure/cancel stops and
  reports completed items instead of implying transactional rollback.
- Portal routing changes are user-local and backed up before replacement.
- The stock GTK portal remains the fallback for all non-FileChooser interfaces.
- Context popovers are parented to the stable browser stack, not replaceable
  file tiles. Entry dialogs release focus/hide before deferred destruction to
  avoid queued Wayland input-method events reaching destroyed widgets.
- Sidebar/menu QA uses isolated preferences and native Paned positions, verifies
  restored width, and checks pointer/keyboard anchors against real GTK bounds.
  Present test windows before destroying them; an unshown second window triggered
  a GTK destruction crash on this desktop. No desktop rules are changed by QA.
- Navigation QA checks the wider default/minimum and old-width migration,
  synchronized eye/filter chips and removals, bounded long queries, connected
  chevron geometry/hit areas and bidirectional wheel scrolling without navigation.
  Absolute resize tests float only their exact disposable native window first.
- Content must not increase the top-level minimum size during navigation.
  Keep path ancestors in a horizontal scroller (current folder auto-revealed),
  preserve the full typed path, and use tooltips for truncated labels. The layout
  regression exercises deep paths, long names/types and user-selected sizes.
- Preview geometry tests verify both minimum and natural size requests, native
  window size/position, and browser height during selection and Space preview
  open/close with portrait, landscape, square images and long-name text. They
  float/resize only their disposable test window, without editing desktop rules.
- Image zoom QA emits real GTK controller signals (not physical mouse events)
  and checks zoom limits, pointer anchoring, pan bounds, reset, loading spinner,
  clipped rendered bounds and unchanged layout for wide and tall fixtures.
- Creative QA uses generated media and isolated preferences/catalogs. It tests
  real hover frame differences, media/EXIF values, labels/filtering/culling,
  editable-shortcut safety, preserved selection/geometry, and real batch rename
  with collision/race/partial-failure protection. Native screenshots are inspected
  for controls, filter card and rename dialog; no physical pointer injection.
  Swatch QA asserts actual GTK label foregrounds for all five colors in metadata,
  Quick Look and filter palettes under light and the active desktop theme.
  Palette CSS must outrank generic rating-control button colors because these
  popovers remain descendants of the controls, including under dark themes.
  `CREATIVE_QA_SCREENSHOTS=1` enables optional creative UI captures. GTK can
  return no paintable node when a widget is not drawable; keep its native
  surface visible for capture. Screenshots are separate from behavior QA.
- UI smoke tests require a desktop session and temporarily use the clipboard;
  file actions run only against a disposable fixture with isolated preferences.
- Selection smoke tests exercise GTK's native range/toggle action signals in
  all three views, not injected mouse events; reuse native FlowBox pointer handling.
- Column QA verifies hierarchy expansion, overflow, native selection, preview
  focus, hidden-file refresh, background-context creation destinations, empty
  folders, history, view switching, single/folder-only constraints and stable
  geometry. `COLUMNS_QA_SCREENSHOT=/tmp/columns.png` captures an isolated fixture.
  Newly built column focus is restored on the frame clock after mapping; menu
  close likewise guards against GTK focusing/selecting the first ancestor.
  Keep each column's FlowBox, scroller, entries and child map bound together.
- Background-drag tests invoke the gesture handlers against actual GTK bounds
  and hit testing, including scrolling and cancellation; no physical pointer
  injection. Overlays are excluded from size requests. Conversion-notice QA
  performs a real ImageMagick conversion against a disposable image fixture.
- A GVfs mount and `GFile.get_path()` can exist without a running FUSE bridge.
  Verify local directory accessibility before navigation; never treat a path
  string as proof of a working mount. Start only the existing user bridge, not
  a new server connection, when recovering this condition.
- `PICKER_QA_LIVE_MOUNT=1 PYTHONPATH=. python tests/ui_mounts.py` additionally
  exercises an already-mounted NAS sidebar button, subfolder activation and
  Back read-only. It does not request credentials or mount a new share.
- For unobstructed NAS visual QA, set `NAS_QA_SCREENSHOT=/tmp/nas-qa.png` when
  running `tests/ui_nas.py`; it snapshots the native dialog via GTK's renderer,
  excluding other desktop windows and authentication overlays.

## Known risks and next actions

- Apps that bypass XDG portals keep their toolkit-native chooser.
- A NAS must be reachable and provide valid credentials for a live mount test;
  live passive discovery is verified, while authenticated share browsing and
  mounting require a user-selected server/login and remain unverified here.
  Browsing an existing authenticated mount and entering a subfolder are verified.
- Sandboxed-app and native-app Open/Save flows must both be smoke-tested after
  each portal protocol change.
