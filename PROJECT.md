# Gudfiles

## Purpose

Provide Gudfiles, a fast, visual, theme-aware file manager for Omarchy, with
Open/Save dialogs exposed through the desktop's XDG FileChooser portal backend.

## Current state

- SMB-encoded trailing spaces (U+F028) display as normal spaces in file rows,
  folder headings, breadcrumbs, tabs, sidebar shortcuts and Quick Look titles.
  `filename_display.py` owns display-only decoding at path-component boundaries;
  filesystem paths, selection keys, portal URIs and editable names stay raw.
  Native regression `tests/ui_filename_display.py` checks all three views in
  two palettes and accepts distinct files whose rendered names are identical.
  The regression also covers browser tabs, breadcrumbs, Recents and Quick Look.
  September 21 verification: 295 unit tests pass; the native display regression
  passes against source and the installed runtime. All 65 runtime files match
  source after atomic package exchange with a rollback backup. Reopen existing
  windows to load the change. Actual NAS names and contents are unchanged.

- Current app version: 0.1.2, with changes recorded in `releases/0.1.2.md`.
  This source/version update does not publish new download assets or an AUR package.

- Favorites and Recents are separate sidebar sections in browser/Open/Save/folder
  windows. Right-click a folder, the current folder background, or a sidebar
  folder to Add to Favorites; removal deletes only the shortcut. Existing GTK
  bookmarks and default places are preserved; the former Recent place is labeled
  Recent Files to distinguish it from folder Recents. Empty sections display
  NO FAVORITES YET and NO RECENT FOLDERS in 10-pixel text, aligned with their headings.
  Right-click a Recents entry to Remove from Recents; this persists without
  changing Favorites or deleting anything. A later visit can add it again.
  Only one sidebar entry highlights the current folder; a Places, Favorites or
  device shortcut takes precedence over a duplicate in Recents.
  Recents persists the five distinct most recently used folder paths, newest
  first. Explicit navigation (including columns, history and tabs), accepted
  picker choices, file opening/preview, clipboard copy/cut, Properties, ratings,
  and completed file operations update it. Startup, thumbnail work and passive
  refresh/selection restoration do not. Disconnected shortcuts stay saved and
  report an unavailable folder when opened.
  `folder_locations.py` owns the private `folders.sqlite3` beside the ratings
  database, outside the replaceable runtime package. SQLite transactions merge
  concurrent window writes, and failures preserve existing data. Sidebar sections
  refresh across windows within a second, deferring during menus and drags;
  automatic history-save errors appear inline without blocking picker results.
  Completed transfers replayed during recovery do not update Recents; only
  newly completed transfer events do. Native transfer QA must isolate
  XDG_STATE_HOME as well as Path.home() to avoid persisting fixture receipts.
- The standalone browser shows its large bottom preview only when a photo,
  camera RAW image or video is selected. Empty/folder/document selections reclaim
  that space. Mixed selections preview the first selected media file, with the
  preview rating controls scoped to that file; the small bar retains totals for
  the whole selection. Open/Save/folder pickers keep their compact layout.
- A compact bar beneath the file area has a thumbnail-size slider at the left
  and a centered selected-file count/combined size. The slider works only in grid
  view, ranges from 96 to 312 pixels wide and persists across windows. Tiles resize
  in place, preserving selection/native rows; bounded cached textures refresh
  after dragging settles. The summary is blank with no selection. One background
  worker cancels obsolete totals and identifies unavailable sizes; folder contents
  are not scanned and mixed totals explicitly say they cover files only.
- Open/Save/folder pickers request 1750×1200 by default, capped to 90% of the
  initial monitor geometry while retaining the existing 820×560 minimum.
  Copy/Move destination pickers share this default. Footer Cancel and accept
  buttons have neutral fills, thin borders and compact 22–24-pixel heights with visible
  keyboard focus; the accept action has no blue suggested-action fill.
- The Name heading's right edge resizes the filename column by dragging;
  double-click fits every filename in the current list, including offscreen
  rows, using rendered text widths plus icons and annotation badges. Narrowing
  truncates names within one shared column width; filename/metadata natural
  widths cannot push cells past their headings. New/reset layouts start at
  220 pixels. Dragged widths persist; double-click fitting stays in the current
  window and does not change the saved default. Escape cancels
  a drag; Reset columns restores the compact default. Sorting, column reordering,
  selection and horizontal header/body alignment remain independent.
- Thumbnail decoder crash fix (September 21): source and user-local runtime are
  now 0.1.2. Glycin aborted while creating threads under the old 1 GiB virtual
  address-space limit; disposable decoders now allow 4 GiB while retaining the
  20-second CPU/deadline and 256 MiB file-size limits. This is an address-space
  ceiling, not a RAM reservation. Decoder failures log at most 4 KiB of stderr
  plus the exit status/reason and retain the ordinary file icon.
- Thumbnail speed: browser and Open/Save dialogs share a single-pass image
  decoder, immediate worker refill, stable display ordering and selected-preview
  priority. Two-worker concurrency, viewport cancellation, source-version cache
  keys and hidden-texture release remain bounded. Cached PNGs are checked without
  an extra GdkPixbuf metadata decode. Image decoding remains CPU-based; GPU
  rendering is provided by GTK. GPU decode acceleration has not been implemented.
- The public README features `docs/screenshots/gudfiles-demo.png`, the
  framed 0.1.2 product image with Favorites, Recents and media-preview captions.
  It uses an isolated native capture with mock folders/files; the original is
  `docs/screenshots/gudfiles-0.1.2-capture.png`. The adjacent README owns provenance
  and sample-media attribution.
- Friend preview packaging is documented in `docs/TESTING.md` and
  `docs/RELEASING.md`. The repository and preview downloads are public
  following the owner's September 20 visibility change. The app
  published preview reports 0.1.0, with tag `v0.1.0-preview.1`; changed runtime contents
  after this distribution require a new app version. Public/AUR publication
  remains separate, and a fresh-machine install plus portal login cycle remains
  the next acceptance check.
- Folder-selection popups show surrounding files as disabled entries in grid,
  list, columns and search, while returning folders only. File-type controls are
  hidden and ignored in folder mode; a files-only folder is no longer called
  empty. Preserve this visibility: Tommy needs to recognize folder contents
  before choosing a folder. Open/Save/folder popups use the same compact header,
  navigation, toolbar groups and styling as the regular Gudfiles browser. Caller
  titles remain window titles. Popup footers are a compact action row with Cancel
  and Open/Save, plus a filename entry when saving. The file-type dropdown,
  repeated prompt, selection summary and shortcut legend are absent; the caller's
  selected file filter and required custom choices remain honored. Popups have no
  preview/metadata strip and do not start its hidden metadata work. Space preview
  remains available, and the standalone browser shows its strip for media selections. Pickers
  retain their separate application identity and no browser tabs.
- List view uses real image, camera RAW and video thumbnails beside filenames,
  preserving 28-pixel rows and aspect ratios. It shares the grid's versioned
  cache, two-worker limit, viewport-only scheduling and cancellation. Folders and
  unsupported files retain icons; whole-computer search retains its lightweight
  icons. This applies to the standalone browser and Open/Save/folder popups.
- File/folder items have no hover tooltips in grid, list, columns or Trash,
  including filenames, metadata cells and rating badges. The selection strip
  also omits redundant filename/fact tooltips. Toolbar and action-button hints
  remain; annotation descriptions stay available through accessibility labels.
  Preserve this preference when adding file-item content.
- Visible ordinary folders refresh from debounced GIO change events in grid,
  list and columns, preserving selections, native keyboard cursor, scroll,
  column trails and in-progress location entry. Navigation/tab changes invalidate
  late work. Refresh defers during interactions/file jobs; unavailable watched
  locations re-arm when restored. Recent, Trash and computer-search keep their
  own refresh behavior; remote backends without events retain manual F5.
- Ctrl+Z and file/background menu Undo reverse successful renames, batch renames
  and same-drive moves within the current window. Inverses use identity/version
  checks and no-overwrite renames, carry annotations, retain failed work for
  retry and preserve partial-success receipts. Text editors and Quick Look keep
  their existing keys. History retains 20 actions, with a 10,000-entry snapshot
  limit per item; cross-drive moves and deletion are not recorded for Undo.
- Transfers save private, atomic recovery records under the user's state
  directory, claimed by a single window/process. Save queue & close waits for
  stopped workers; relaunch/crash recovery holds jobs for explicit continuation.
  Publication, cancellation, restart, source removal and retention intents are
  saved before their filesystem changes. Corrupt/unsafe records are reported
  without acting on their paths. Completed move annotations use idempotent
  SQLite receipts so recovery cannot apply a move twice.
- Cut/Paste and Move to support cross-drive moves: copy, verify, publish without
  overwrite, validate originals, then remove only unchanged original entries.
  Source cleanup uses a private held name and a durable removal ledger; failures
  retain the verified copy and remaining originals. Keep remaining originals
  safely resolves a stopped move, restoring any held data to an available name.
  Same-drive moves remain atomic. Cross-drive drag-and-drop still copies.
- September 19 integration verification: 285 unit tests pass, including actual
  subprocess crashes during copy/publication/source unlink/cancellation and
  annotation commits. Native checks cover Undo/collisions, paused recovery,
  Save queue & close, Keep remaining originals, Retry labels, real GIO refresh,
  tab/column/selection continuity, typed-path preservation and hover deferral.
  Queue/All/visibility checks and H.264, HEVC, ProRes, VP9 and AV1 playback pass.
  A real 4K/60fps H.264 clip passed physical hover and Quick Look checks with its
  hash unchanged; both existing SMB shares passed read-only browsing. A
  1,000-image fixture switched to grid in 0.22 seconds with 16 resident thumbnails.
  Cross-drive writes/deletion and crash tests use owned disposable local/tmpfs
  fixtures; this pass does not certify NAS transfer/reconnect or RAW footage.
  Native physical input uses isolated X11 displays, not live Wayland injection.
  New runtime installation uses an atomic whole-package exchange with a rollback
  backup and preserves existing windows; reopening loads the new code.

- September 19 compact visual pass: tabs are 24-pixel rectangular segments with
  square corners, quiet dividers and flat close buttons; the complete strip is
  25 pixels including its separator. The first tab and rightmost + control sit
  flush with the tab row edges, with no outer padding or gap beside +.
  Equal-width expansion, drag/reordering,
  keyboard shortcuts and reduced-motion behavior remain supported. List headings
  use the app background with a subtle separator and readable active sort state.
  Explorer top-bar controls, breadcrumbs and list headings do not change visually
  on hover, including the native close icon. Active selections and keyboard focus
  stay visible; breadcrumb press feedback remains. Right-hand toolbar actions
  are grouped into Find and filter, Sort and view, Tools, and Window controls
  with subtle dividers and spacing. Help, Transfers and window controls remain
  available while Quick Look disables browser actions.
- Supported devices and network mounts show a separate trailing eject icon.
  Its accessible name/tooltip identifies Eject, Unmount or Disconnect and the
  target; it never activates folder navigation. Pending operations disable the
  control, failures re-enable it, and existing busy-transfer/no-force guards
  remain shared with the context menu. Non-removable entries omit the icon.
- Mounted sidebar entries have no status dots. SMB/NFS labels remove only the
  host suffix matching their own URI, preserving share names and local-device
  names; the safe address remains in the tooltip for distinguishing hosts.
  The NAS browser uses the same share labels.
- Shared Rename, New Folder, Properties, Trash/Delete, replacement and error
  dialogs use 15-pixel titles, compact fields/actions and flat file summaries.
  Batch Rename, NAS, Help/About, Transfers, search/column/media popovers and
  Open/Save/destination pickers follow the lighter spacing and controls.
  Destination pickers use the large picker default; Help opens at 760×600, Transfers at 640×460,
  and Batch Rename at 680×520. Native scrolling, keyboard focus, inline errors,
  cancellation, destructive-action defaults and transfer close guards remain.
  Keep future secondary surfaces compact and consistent with the browser.
- Space preview follows the compact browser styling: a 31-pixel single-row
  header (26-pixel controls plus padding/separator), 13-pixel filename, flat
  controls, 6-pixel card corners and a quieter shadow. Media fills the frame
  without an inner gutter; the compact footer shows file details and PDF page
  count, with interaction hints on hover. Narrow previews retain a second row
  for ratings. Text uses 12-pixel margins; native playback controls are compact.
  Aspect fitting, opening animation, keyboard navigation and zoom are preserved.

- List view has a pinned, aligned heading row directly above the files. Click a
  heading to sort/reverse; right-click or Shift+F10 chooses Name, Rating,
  Color Label, Rejected, Size, Type, Date Created, Date Modified, Resolution,
  FPS, Duration and Codec. Rating is included in new/reset layouts; existing
  custom column choices remain intact. Saved annotations update immediately
  after successful writes, and can be sorted without media probing. Unrated
  files show a dash and sort last in either direction; color labels have text
  as well as colored dots. Name badges omit annotations already shown in columns.
  Name stays fixed in the first position, including when loading older layouts.
  Drag other headings or use Alt+Left/Right to reorder them to its right. A
  floating header follows the pointer; the full column is shaded and neighboring
  headings/cells move aside live. Preferences change only on release. Escape or
  dropping outside restores the original order. Edge dragging scrolls; header
  and body remain aligned throughout. Column choices/order persist. Reordering preserves file selection and the current sort.
  The column customization popup uses square corners and checkbox indicators,
  compact 24-pixel rows, 8-pixel outer spacing and a flat reset action. Native
  active/light/dark checks cover appearance, toggles, keyboard opening, reset
  and persisted choices.
  App typography uses Noto Sans, with a generic sans-serif fallback. This
  replaces the briefly used Omarchy monospace font and the older Adwaita Sans.
  Text previews and path/keyboard hints retain their purposeful monospace rules.
  File rows are 28 pixels with a 2-pixel inter-row gap, 14-pixel icons,
  13-pixel names and 11-pixel
  metadata. `list_details.py` owns the native
  header/cells/menu; `list_metadata.py` owns formatting and a single background
  worker with replaceable batches of at most 16 and a versioned 512-entry cache.
  Normal browsing probes visible rows only. Media/creation-date sorting reports
  progress while reading entries, then applies one stable order without losing
  selection. Navigation and close invalidate late replies. Missing values show
  a dash and sort last within folders-first groups. Date Created uses actual
  filesystem birth time, never Linux ctime. Media helpers retain their existing
  six-second deadlines; a running probe can finish after cancellation but cannot
  update the new view. F5 refreshes changed files.

- Image, Nikon NEF / camera RAW and video thumbnails load only for visible tiles
  and the selection strip, through two background workers with no pending decode
  queue. Scrolling/view/tab/close changes cancel obsolete jobs and release hidden
  textures. Full images and video/RAW helpers decode in isolated, resource-limited
  processes with a 20-second deadline; failures retain the ordinary file icon.
  Versioned, atomically published 360-pixel PNGs live in
  `~/.cache/omarchy-file-picker/thumbnails-v2`. Cache keys include source identity,
  size and nanosecond mtime; CRC/dimension checks reject damaged cache files.
  Grid image dimensions appear asynchronously, without probing every original on
  the GTK thread. RAW support uses the existing optional `raw-preview` helper.

- File deletion accepts `Super+Backspace` and `Super+Delete` as confirmed
  Move-to-Trash shortcuts alongside `Delete`; adding Shift keeps the existing
  confirmed permanent-delete behavior. Plain Backspace remains untouched for
  navigation/editing, text fields retain native editing, and Quick Look blocks
  the shortcuts from acting on files behind its overlay.
- Clicking outside a right-click menu now dismisses the entire cascade even
  when a hover submenu owns GTK's active popup grab. Intentional submenu
  switching and hover timeout closes keep the root menu open, while Escape
  can still back out of the active submenu without immediately reopening it.
- Switching right-click submenus closes the previous popup before mapping its
  sibling. The shared MenuButton pre-popup callback covers hover, click and
  keyboard activation and respects Wayland's popup-grab ordering.
- Right-clicking a file or selection offers **Copy to…** and **Move to…**.
  A modal Gudfiles folder picker chooses the destination with Copy here/Move
  here; it captures the source selection and leaves the clipboard unchanged.
  Existing files remain visible as disabled entries while browsing destinations,
  including nested columns and whole-computer search. Only folders can be
  destinations; activating a displayed file does not submit the prompt. Ordinary
  portal folder pickers also show disabled files while accepting folders only.
  Cancel/close schedules nothing. The parent owns progress, queue controls,
  refreshes, move annotation receipts and close guards. Copies choose available
  names; moves retain no-overwrite protection and verify copies across drives.
  The folder prompt closes with its owner and never quits the parent app or
  writes an Open/Save result. Existing paused/failed queues remain held until
  resumed in Transfers.
  Copy/Move use supported neutral symbolic icons; the file-selection menu has
  no More submenu. Bookmarking remains under the background Folder menu.
- Search offers **This folder** and **Whole computer** in the magnifying-glass
  popover. This folder retains the immediate-folder name filter. Whole computer
  recursively searches accessible files and already-mounted drives, starting
  with Home, without following directory symlinks or scanning virtual system
  roots. Hidden/type constraints apply; folder pickers display files as disabled
  context and accept folders only. Each tab keeps its own scope.
  Results include parent locations in all three views and Visit File in their
  context menu. Background paste/create/drop requires an actual folder; drops
  onto a found folder remain supported. Save searches open the selected result's
  folder before saving; folder pickers require a selection in computer results.
  A cancellable subprocess scans for at most 15 seconds or 500 matches. A status
  row distinguishes searching, complete, partial, unreadable and failed results.
  Clear/query/scope/tab/window changes invalidate late replies; F5 rescans.
  View/sort changes reuse the result metadata collected off the GTK thread.
- The toolbar has an Up one folder button beside Back/Forward, sharing Alt+Up
  behavior and disabled at `/` and in Recent. Search is a magnifying-glass
  button with a focused popover and Ctrl+F support. Enter applies the query and
  focuses results; Escape closes the popover while retaining the filter, and
  the search chip clears it. Explorer navigation, scrollable/editable path,
  search, rating/hidden filters, sort and three view buttons now share the compact
  title bar with Help, Transfers and close. Its controls use 14-pixel icons and
  26-pixel targets; the bar measures 30 pixels plus its separator. It fits the
  820-pixel minimum width independently of sidebar width. Open/Save and folder
  pickers share this same compact header; caller prompts and selection actions
  remain in their footer. Quick Look disables the moved
  browsing controls while its overlay owns navigation and restores them on close;
  Help, Transfers and native Close remain available.
- `tests/ui_toolbar.py` verifies native compact bounds, long-path/location
  entry, sidebar independence, view buttons, Up/history, search, preview guards,
  filter clearing and tab state in
  active/light palettes. Its windows alone are floated/resized; optional
  `TOOLBAR_QA_SCREENSHOTS` captures the actual GTK surfaces. Keyboard checks use
  native signals, not physical pointer/key injection.
- Locations without Trash support, including the verified SMB NAS shares, show
  an explicit permanent-delete confirmation after GIO reports `NOT_SUPPORTED`.
  Cancel keeps the unsupported items intact; successful Trash items are excluded
  from that confirmation. Source identities/metadata are rechecked before the
  confirmed deletion. Permission/I/O/read-only failures do not offer this
  fallback, and partial failures report completed/not-completed counts. Removal
  refreshes preserve visible column trails and avoid redirecting another tab.
- Column row clicks preserve vertical position and native selection. New child
  columns are revealed after layout, including empty folders, equal-width sibling
  replacements and re-clicking an already selected folder. The horizontal
  viewport no longer overrides reveal to follow focus in the parent column.
  Folder double-click/Enter enters the adjacent column without rebuilding and
  resetting the scrolled ancestors.
- Double-clicking a ZIP in explorer mode extracts it into a new sibling folder
  named after the archive, using ` (1)`, ` (2)`, etc. for collisions. The archive
  and existing entries remain intact. A background worker shows an Extracting
  notice, then completion or an error; duplicate work and normal close are guarded.
  Visible destination columns refresh without discarding the trail or switching
  tabs. Open/Save dialogs keep ordinary ZIP selection behavior.
  Extraction validates relative paths, rejects encrypted entries, links and
  special files, checks ZIP CRCs through streamed reads and publishes the complete
  staged tree using atomic no-overwrite rename. Failure removes unpublished
  staging; forced process termination can leave a hidden staging directory.
  The limit is 100,000 archive entries; extraction has no pause/resume or password
  prompt and is separate from the transfer queue.
- External file-manager requests use `org.omarchy.FilePicker.External`.
  `ShowItems` groups requested items by parent folder and selects them after
  layout, including folder entries, hidden files, symlinks and escaped names.
  `ShowFolders` enters the requested folder in the same external window mode.
  Desktop launches with an explicit file/folder also use external mode;
  a plain launcher click remains ordinary browsing.
  CLI `--select PATH` (repeat for siblings) reveals items; `--external` marks
  temporary browsers. A standalone file argument also selects that file and
  uses the external identity. Ordinary folder browsing remains the base class;
  Open/Save requests retain the picker class and their existing semantics.
  Hyprland floating behavior is configured in the user profile, matching the
  external class, independently of the app title.
- The top-bar Sort menu exposes Newest/Oldest first (date modified), name and
  type in both directions, Largest/Smallest first, and a Folders first toggle.
  It shares choices and the current-order checkmark with right-click → Sort By.
  Sorting preserves selection in grid/list/columns and saves criterion/direction
  together; new explorer/Open/Save windows restore the choice. Unrelated writes
  from older windows preserve the newest saved sorting pair.
- The desktop launcher accepts a local file argument and advertises common video
  MIME types, so Gudfiles can be the default application for opening videos. A
  file launch reveals and selects that video in its containing folder.
- Open/Save picker windows use the distinct Wayland application ID
  `org.omarchy.FilePicker.Picker`; the standalone browser retains
  `org.omarchy.FilePicker`. This lets Hyprland float every picker regardless of
  caller-supplied title while leaving ordinary Gudfiles windows tiled.
- Gudfiles 0.1.0 has local distribution preparation: an Arch `gudfiles` package,
  pinned AUR recipe and `.SRCINFO`, SHA-256 checksums, deterministic allowlisted
  runtime archive, release notes and a packaging-only CI workflow. Source and
  friend-preview downloads are now public; stable releases and an AUR listing
  remain unpublished. `release.json` currently uses the
  proposed `themediastandard/gudfiles-releases` destination; owner confirmation
  is pending. Shipped Python remains readable regardless of repository privacy.
- Help → About & License displays the version and a manual asynchronous GitHub
  release check. It sends no user files/settings, does not install anything, and
  distinguishes package installs from local development copies. Official AUR
  updates require both a GitHub release and an updated AUR recipe. The AUR RPC
  returned no `gudfiles` entry on 2026-09-07; availability must be checked again
  before publication.
- Public packaging stages code under `/usr/lib/gudfiles` and leaves user data
  outside package ownership. `gudfiles` is the primary command; legacy commands
  and desktop/portal IDs remain compatible. The portal spawns its own Python
  module so an old PATH launcher cannot select a different installation.
- Portal routing is explicit per-user opt-in via `gudfiles --enable-portal` and
  reversible with `--disable-portal`. It records the previous FileChooser value
  and preserves other portal preferences. Applying it requires a later logout
  and login; installation does not restart active user services.
- The updated development `install.sh` replaces only code, backs up previous
  files and checks required runtime imports. It refuses a detected system
  package and ordinary running Gudfiles processes. `uninstall.sh` retains the
  ratings database including WAL/SHM, preferences and shared GTK bookmarks,
  restores owned legacy/opt-in routing, and removes only app-owned files. Use
  this updated uninstaller when migrating older copies to the package.

- Help → About & License credits The Media Standard, links to
  `https://themediastandard.com`, and describes Gudfiles as made for creatives
  using Linux. The Gudfiles Free Use License permits personal/commercial use
  without a fee while reserving modification and redistribution permissions.
  Full terms are readable and selectable offline in Help. Root `LICENSE` is
  canonical and `install.sh` copies it beside the installed Python package.

- Light mode derives quiet surfaces and readable secondary/accent/error text
  from the active Omarchy palette. Sidebar, breadcrumbs, selection, menus,
  placeholders, Help/dialog title bars, transfer controls and native video
  controls share the palette. Color labels retain their hues with deeper light
  shades; filled actions choose the more legible dark/white foreground. Desktop
  theme files, primary palette identity and media pixels remain untouched.

- Four short original action sounds confirm successful drop/copy batches, Trash,
  permanent deletion and conversions. Right-click → View → Sound Effects saves
  a shared mute preference, read back by existing windows without changing their
  views or selection. Cancelled, failed, partial-failure, staged and no-op actions
  produce no success cue; completion polling does not repeat sounds. Playback
  is optional, asynchronous, limited to one sound at a time with a 300 ms gap,
  and killed after 2.5 seconds or when muted/its window closes.

- Product name is Gudfiles in the launcher, Help, transfer messages, notifications
  and installation output. Tommy requested a very small, minimal top bar with no
  app name, with small options, the path and view buttons in the top bar
  (2026-09-19). The standalone browser now uses one compact 30-pixel title bar
  for these controls; Open/Save pickers retain their task headings.
  Native active/light checks verify the height, utility actions, transfer badge,
  820–1200-pixel layouts and picker titles. All 222 unit tests pass. The complete
  native toolbar suite also passes against the installed package in both themes.
  All 54 runtime files match source; the update has a rollback backup. Reopen
  existing windows to load it.
  The existing commands,
  application/portal IDs and storage paths remain stable for compatibility.

- File arrows follow the visible layout: Up/Down moves between grid rows or
  adjacent items in list/column views; Left/Right moves across grid tiles or
  between folder columns. The first arrow after a view/sort-button handoff moves
  immediately. Full rows stay visible and edges keep focus in the files. Shift
  extends ranges and Ctrl moves focus without replacing selection; menus, search,
  filename fields, sidebar and Alt navigation retain their own controls.
- Space preview accepts Down/Right for the next file and Up/Left for the previous
  file in the current sort order. Closing restores the native cursor to the last
  previewed file, including within a nested column trail. Focused preview text
  and playback sliders retain their own arrow controls.
- Help and Transfers use matching compact header icon buttons (24-pixel explorer
  targets, 32-pixel picker targets) with quiet idle
  styling, hover/focus feedback, tooltips and accessible names. Unfinished transfers
  show a small count badge without changing the button width or header layout.
- Explorer tabs keep independent folders, history, selection, view, search,
  hidden/rating/type filters, scroll position and full column trails. The tab
  strip has New/Close controls, native reordering, middle-click close and folder
  opening, context-menu Open in New Tab, Ctrl+T/W/Shift+T, Ctrl+Tab/Shift+Tab,
  Ctrl+PageUp/PageDown and Alt+1–9. Tab hover switches after 600 ms during a
  file drag. All tabs share the existing transfer queue and guarded final close.
  Tabs are session-only; portal/explicit picker windows retain their original
  controls and result semantics.
- Tabs fill the available strip width, sharing it equally as tabs open or close.
  Opening tabs expand and fade in with a subtle vertical settle; closing tabs
  collapse and fade out as their neighbors smoothly resize. Native frame-clock
  motion lasts 220 ms with cubic easing, supports rapid interruption/reopening,
  and settles immediately when GTK animations are disabled. Logical closure
  happens immediately; outgoing tabs cannot receive clicks, focus or drops.
  Drag reordering settles active motion first, and overflow reveal tracks the
  selected tab throughout its expansion. Final-tab transfer guards are unchanged.
  They use 24-pixel square segments, ellipsized labels and a flat 22-pixel
  close target on the left. A small New Tab control stays at the right edge;
  many tabs scroll horizontally when their minimum widths exceed the viewport.
  Native sizing checks cover one/two/three tabs, unequal folder-name lengths,
  820/1200-pixel windows, close/reopen expansion and overflow reveal. Tab/drag
  regression checks pass; they await frame-clock selection restoration rather
  than assuming a fixed 250 ms delay.
  New-tab scrolling waits for GTK layout before revealing the selected pill.
- Header Help / F1 opens a compact, searchable feature guide with seven categories,
  shortcut badges, empty-search recovery and active Omarchy colors. Ctrl+F focuses
  help search; Escape closes only help. Each browser owns one reusable guide,
  cleaned up when its Gudfiles/picker window ends. Quick Look, selection and file
  operations remain independent of the guide.
- Shared native dialog design for Rename, Properties, New Folder, Batch Rename,
  NAS, errors, Trash/Delete and Save replacement: draggable in-window headings,
  consistent file cards, labeled fields, inline errors and a fixed action footer.
  Accent/destructive buttons choose legible dark or light text from the palette.
- Properties uses aligned, selectable detail rows, human-readable access,
  symbolic/octal permissions and Copy Location. Multiple selections show combined
  file size with explicit exclusions/unavailable entries and a bounded item list.
  Long paths scroll within the body; directory-entry bytes are not shown as
  folder-content size. Rename selects the stem and reports collisions inline.
  Destructive and replacement confirmations default to Cancel; Enter activates
  ready form actions and Escape/titlebar close share the cancellation path.
- Native GTK 4 picker with grid, list and Finder-style column layouts, selected
  through a compact three-button toolbar group or the View context submenu.
  The last chosen view is saved immediately and restored in new Gudfiles windows
  and Open/Save pickers. Missing/invalid values default to grid; startup does
  not rewrite the preference. Settings writes merge the latest on-disk values
  so an older window's sidebar resize cannot replace a newer view choice.
- Column view opens a selected folder into an adjacent column, retains the
  ancestor trail, and scrolls horizontally without growing the window. Left/
  Right move between columns; each column has independent vertical scrolling.
  The active column owns selection, current-directory actions and metadata;
  ancestor selections are muted. Multi-select, rubber-band selection, labels,
  filters, file operations and Space preview use the shared interaction paths.
- Standalone browsing runs in explorer mode: footer hidden, normal default-app
  file opening without quitting, and Escape clears selection. The preview strip
  appears for media selections. Portal requests, CLI `--result`, folder picking and Save modes retain
  picker footer controls and result semantics.
- List view uses compact 28-pixel rows with a 2-pixel gap (30-pixel pitch).
  Column rows also have a 2-pixel gap; grid spacing is unchanged. Selected
  files use a square soft accent fill without a blue selection border in all views. List and column
  rows fill the content width without left/right outer padding; file icons sit
  11 pixels inside the selection's left edge, and list headings retain alignment
  with the cells. The last visible metadata column and its heading align right,
  11 pixels inside the content edge. Native range and individual selection remain supported.
- Standalone Open defaults to multi-selection with native Shift-click ranges,
  Ctrl-click toggles and Ctrl+A. `--single` opts out; portal caller constraints
  and single-destination Save behavior remain authoritative.
- Blank-background drags select intersecting files in all three views with a
  theme-colored rectangle, Shift-add, Ctrl-toggle, edge scrolling and Escape
  restoration. File-origin click gestures remain native GTK.
- Ordinary file drags move within a filesystem and copy between filesystems;
  Alt/Option forces copies, including same-folder duplication. Drops target
  folders, column backgrounds, sidebar locations and tabs in all three views.
  Source/destination device checks use worker-thread stat/lstat, including the
  symlink's own device. Mixed-device selections split into move/copy batches.
  Same-folder ordinary drops do nothing. Existing names are never overwritten;
  copies choose available names or `copy`/`copy 2` suffixes. Queue operations
  retain verified copies, atomic moves, labels, progress and clipboard contents.
- Drag sources preserve GTK click/range/double-click behavior until the drag
  threshold. FlowBox's duplicate native rubber-band controller is disabled;
  the existing background selection overlay owns blank drags. Sources publish
  both native `GdkFileList` data and an explicit CRLF-delimited, URI-escaped
  `text/uri-list` offer so MIME-only X11/Xwayland receivers such as DaVinci
  Resolve can import the files; Alt advertises COPY only. Gudfiles uses a marker
  to negotiate MOVE internally, acknowledges outside sources as COPY so they
  cannot delete before queued work, and never deletes URI sources based solely
  on GDK's delete-data flag. Hover checks are bounded/latest-only;
  publication and identity verification remain the transfer engine's authority.
- Image and cached video thumbnails, selection metadata, search, file filters,
  multi-select, folder selection, Open, Save, and SaveFiles modes.
- The compact status bar summarizes multi-selections, including combined file
  sizes and folder/file counts; folder contents are excluded and unavailable
  sizes are marked. Non-media selections do not open a large summary panel.
- Video grid/metadata thumbnails support silent hover-scrubbing with delayed
  entry, a thin position indicator, background decoding and poster restoration.
  Completed frames from the current hover stay visible while the pointer moves;
  the decoder immediately requests the newest position after each completion.
  The progress line follows the displayed frame. Skim hints remain accessible
  without a tooltip; filenames and file rows also have no hover tooltips.
  Leaving/re-entering rejects prior-hover frames; dragging cancels
  without starting another hover timer.
  September 19 verification: all 234 unit tests passed. The expanded
  `tests/ui_hover_scrub.py` passed against source and the installed package with
  real FFmpeg frames, deliberately delayed replies, stale-hover cancellation,
  geometry/selection checks and tooltip ancestry. Isolated X11 pointer sweeps
  displayed 26 positions while moving in each run and restored the poster on
  exit. Restoring the old completion method makes the continuous-motion
  regression fail. The two runtime modules were installed atomically with
  backups; existing windows need reopening. Physical-input verification used
  X11, not the live Wayland desktop.
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
  submenu placement near the chooser's right edge. Submenus open after 140 ms
  of hover, with a 280 ms grace period for crossing into the submenu. Hovering
  another submenu switches it; ordinary actions dismiss it. Click/keyboard
  controls remain available. Popup-grab changes after dismissal cannot reopen
  a submenu until the pointer moves; closing the root cancels pending timers.
- File and background menus include rename, clipboard file operations,
  confirmed trash/permanent deletion, properties, bookmarks, view and sort.
  NAS connection is sidebar-only. Rename and paste never overwrite collisions.
- A compact Omarchy-themed Transfers window is accessible from the header.
  Ctrl+V starts that clipboard batch; Ctrl+Shift+V / Add to Transfer Queue stages
  it without starting. Start runs one chosen batch, Start queue authorizes the
  current waiting/staged batches. A Queue / All toggle chooses one transfer at a
  time or up to three independent transfers together; All uses a Start all action.
  The choice is remembered in display preferences. Newly staged batches remain
  staged when the mode changes or an earlier queue is draining. Switching from
  All to Queue lets active workers finish, then starts only one at a time, with
  that transition stated in the transfer summary.
- Transfers show current file, bytes, transfer rate, progress and inline errors,
  with Start, Pause, Resume/Continue, Retry, Restart unfinished and Cancel controls.
  Queue mode holds scheduling on pause/failure. In All mode, a row Pause/failure
  leaves independent transfers running; Pause all holds scheduling and pauses
  every active worker. Completed items remain at their destinations.
  The separate window scrolls its rows without resizing the Gudfiles browser.
- Automatically opened transfer panels hide when quick work finishes; copies
  already complete before opening do not flash a window. Five minutes of actual
  running time (accumulated across attempts) keeps the panel open afterward.
  Manually opened panels, pauses and errors stay visible. All mode waits for
  every unfinished batch; history remains available from the header. Closing
  a panel manually never causes it to reopen on completion.
- Completed transfers refresh affected visible columns without changing the
  active column, selections or ancestor trail.
- Copy resume checks every retained byte against an unchanged source and verifies
  the completed data before publication. Changed sources/corrupt partials refuse
  resume and require an explicit restart of unfinished items. Same-volume moves
  use atomic no-overwrite renames; cross-volume moves verify a published copy
  before removing unchanged originals, with recoverable source-cleanup receipts.
- Closing the transfer panel hides it. Closing Gudfiles/finishing a picker pauses
  scheduling and offers saving unfinished work or cancelling it, waiting for
  active I/O/cleanup to stop. Recovery records preserve completed output mappings
  and held work across relaunch. No background transfer daemon or automatic
  network reconnection is used; recovered jobs require explicit continuation.
- SMB/NFS NAS connection dialog backed by Gio/GVfs with native credential
  prompts; mounted shares are refreshed into the Network sidebar section.
- Reads the active Omarchy `colors.toml` on every launch.
- User-local portal installation with GTK retained as the fallback backend.
- Sidebar follows the clean September 19 reference: flat 28-pixel rows, 14-pixel
  symbolic icons and 13-pixel labels, quiet uppercase headings, a subtle active fill with a thin
  accent edge, and whitespace between sections. Places includes existing local
  shortcuts and bookmarks; Music appears when present and Recent remains available.
  Network has a compact accessible + connection button. Mounts are grouped by
  native URI rather than their GVfs bridge path; local disks and MTP/camera/phone
  devices stay under Devices, which hides when empty. Mounted entries show only their name and icon, without status dots or the
  redundant host suffix. The sidebar retains the app background.
- Sidebar items have native pointer/keyboard context menus for Open, a separate
  Gudfiles window, enclosing-folder reveal, Copy Location and Properties. Right-click
  preserves the current directory, browser selection, column trail and geometry.
  Remove from Sidebar hides default locations in display preferences or removes
  only the shared GTK bookmark. Restore Default Locations is available from the
  sidebar context menu. Recent has Open/removal actions; devices expose supported
  Eject/Unmount/Disconnect actions and the NAS entry opens its connection dialog.
- Native draggable sidebar divider with a 180-pixel minimum and 220-pixel default,
  older narrower saved widths clamped on load, scrollable places,
  and debounced width persistence without reloading files or clearing selection.
  The divider is a single 1-pixel line with no hover color or width change; it
  provides the drag target without adding a separate gap beside the tabs.
- Hidden-file visibility uses open/concealed eye icons, an active state and Ctrl+H.
- Active search, file-type, rating, color and hidden-file settings appear as
  removable chips below the toolbar. Clear all resets them; the strip hides
  when inactive and scrolls horizontally instead of growing for long labels.
- Mouse context menus preserve browser-relative pointer coordinates. Only
  keyboard-opened menus use the selected row/tile's center as their anchor.
- Breadcrumbs scroll within a bounded toolbar viewport; long metadata, type,
  sidebar and selection labels ellipsize instead of growing the window.
- Breadcrumbs are connected chevron buttons with matching notch hit tests and
  a highlighted current folder. In columns, the trail includes the single
  selected folder whose contents have opened beside its parent; selection and
  file actions remain owned by the active column. Up and the location field
  follow the displayed folder. The current breadcrumb is revealed after layout,
  including equal-width sibling changes. Hover shows each breadcrumb's full
  folder name. Wheel input scrolls ancestors without navigating folders or
  being overridden by pending automatic reveal. File rows and metadata paths
  retain their existing tooltip behavior.
- In-window Quick Look expands from the selected tile on Space and contracts
  on Space/Escape. Includes images, bounded read-only text, first-page PDFs,
  adjacent-file browsing, reduced motion and optional GStreamer media playback.
- Camera RAW Quick Look uses desktop MIME recognition and the installed
  `raw-preview --thumbnail` reader, preserving orientation and the existing
  1800×1400 texture bound, zoom/pan/fit controls and file navigation. Decoding
  runs off GTK's thread with two shared slots and a 90-second limit. Closing,
  browsing away or destroying the preview cancels queued work and kills the
  active decoder process group. Temporary output is removed; originals and
  sidecars are untouched. Missing support and unreadable files show an error.
- Image, PDF and video preview cards fit the displayed media's aspect ratio
  within the existing window bounds. Narrow previews put ratings below the
  title/navigation row; extreme portrait media retains enough width for usable
  controls. First opening waits for decoded content (and prepared video display
  dimensions) before drawing or animating the card. A frameless spinner covers
  slow initialization. Arrow navigation keeps an already open card at its last
  aspect while the next file loads, then fits the decoded result without replaying
  the opening zoom. Cancellation and reduced motion preserve these rules. Text,
  audio-only and unavailable previews retain the general-purpose frame.
- Image previews support pointer-anchored scroll zoom from fit to 8×, bounded
  drag panning and double-click to fit. Each new image starts fitted. Drawing
  is clipped inside a zero-request widget; the decoded texture remains bounded
  to 1800×1400. Loading uses a spinner instead of the generic preview icon.
- Installed GStreamer good/bad/ugly/libav codecs; generated H.264/AAC, HEVC/AAC,
  ProRes/PCM, VP9/Opus and AV1/AAC clips verify decoding, play, pause, seek,
  resume and stop on preview close. Actual user media and audible output remain
  separate manual checks.
- Media selection previews occupy a 113-pixel strip only while visible. Its
  content and Quick Look do not participate in window size requests; long titles
  and metadata ellipsize. Hiding the strip expands the file area without changing
  the outer window size. Clearing selection cancels obsolete metadata work.
- NAS dialog uses flat theme-colored controls, automatically searches Avahi/
  GVfs network advertisements, and offers explicit SMB share browsing, Refresh,
  saved/mounted locations, inline errors and cancellable mounting.
- Mounted-device clicks and successful NAS connections verify the local path
  on a worker thread, recover a missing GVfs FUSE bridge when available, and
  report unavailable folders. Credential prompts belong to the NAS dialog.

## Architecture

- `view_status.py` — the compact file-area bar, persisted grid sizing without
  rebuilding rows, and one cancellable worker for selected-file totals.
- `omarchy_file_picker/trash.py` / `trash_ui.py` — desktop Trash enumeration,
  safe original-location restoration and the inline Trash browser location.
- `omarchy_file_picker/context_menu.py` — shared hover navigation, delayed
  submenu handoff, native keyboard/pointer transitions and menu-bound cleanup.
- `omarchy_file_picker/tab_strip.py` — equal-width native tab allocation with
  clipped opening/closing slots, interruptible easing and reduced-motion cleanup.
- `omarchy_file_picker/search.py` / `search_ui.py` — bounded filename scanner,
  process cancellation, one active/latest pending request, native scope controls
  and generation-checked result rendering with parent locations.
- `omarchy_file_picker/toolbar.py` — compact, single-row explorer header controls
  and the responsive height-for-width toolbar used by Open/Save pickers.
- `omarchy_file_picker/archives.py` — streamed ZIP validation/extraction, private
  staging, collision naming and atomic publication; `FileManagement._extract_zip`
  owns background work and the shared operation notice.
- `omarchy_file_picker/sound_effects.py` / `sounds/` — optional `paplay` action
  audio, shared mute readback and original 170–320 ms PCM cues. Effects use the
  separate Gudfiles Sound Effects audio identity with half stream volume.
- `scripts/generate_sounds.py` — deterministic standard-library synthesis for
  the bundled sound assets; no external recordings or sound libraries.

- `omarchy_file_picker/list_navigation.py` — spatial arrow routing through GTK's
  native cursor/selection engine, view/sort handoff, row reveal and cursor-safe
  focus restoration shared with columns and Quick Look.
- `omarchy_file_picker/help_catalog.py` — feature descriptions, category metadata
  and search; the single content source for the in-app guide.
- `omarchy_file_picker/help_window.py` — native help window, category navigation,
  shortcut badges, search states and owner-bound lifetime.
- `omarchy_file_picker/about.py` / `LICENSE` — creator credit, website and the
  free-use license; shared by the About page and installed application.
- `omarchy_file_picker/thumbnails.py`, `thumbnail_decode.py`, `thumbnail_widgets.py`
  — source-version cache, isolated bounded decoder and viewport thumbnail lifecycle.
- `omarchy_file_picker/picker.py` — native chooser UI and result protocol.
- `omarchy_file_picker/portal.py` — XDG FileChooser D-Bus backend.
- `omarchy_file_picker/model.py` — request parsing, filters, filesystem helpers.
- `omarchy_file_picker/actions.py` — validated media commands, output naming,
  and NAS address normalization.
- `omarchy_file_picker/file_actions.py` — filesystem operations and sorting.
- `omarchy_file_picker/file_management.py` — file dialogs, clipboard, shared
  GTK bookmarks and persisted display preferences.
- `omarchy_file_picker/folder_watch.py` — visible-directory event monitors,
  deferred state-preserving refresh and cancellable unavailable-root recovery.
- `omarchy_file_picker/undo.py` — bounded session receipts and identity-checked
  inverse renames, including partial completion and retry.
- `omarchy_file_picker/transfers.py` — bounded Queue/All scheduling, resumable
  copies, checked staging ownership, atomic publication and cancellation cleanup.
- `omarchy_file_picker/transfer_journal.py` — private durable checkpoints,
  strict manifest validation, atomic writes and single-owner recovery locks.
- `omarchy_file_picker/move_cleanup.py` — verified cross-drive source removal
  and non-destructive retention of originals after an interrupted move.
- `omarchy_file_picker/transfer_ui.py` — native transfer window, progress/actions,
  ordered move receipts, clipboard ownership and Gudfiles/picker close guard.
- `omarchy_file_picker/theme.py` — active Omarchy palette to GTK CSS.
- `omarchy_file_picker/dialogs.py` — shared dialog shell, fields, file summaries,
  detail cards, bounded lists and explicit confirmation actions.
- `omarchy_file_picker/quicklook.py` — frame-clock animation and preview loading.
- `omarchy_file_picker/raw_preview.py` — RAW MIME detection and bounded,
  cancellable subprocess loading through the external `raw-preview` helper.
- `omarchy_file_picker/image_preview.py` — clipped image zoom and pan controllers.
- `omarchy_file_picker/hover_scrub.py` — bounded silent thumbnail extraction/cache.
- `omarchy_file_picker/media_details.py` — asynchronous media/EXIF probing and card.
- `omarchy_file_picker/ratings.py` / `creative.py` — local annotation store and controls.
- `omarchy_file_picker/batch_rename.py` — preview planning, no-overwrite apply and dialog.
- `omarchy_file_picker/breadcrumbs.py` — chevron drawing/allocation and wheel handling.
- `omarchy_file_picker/columns.py` — adjacent directory columns and active selection/focus.
- `omarchy_file_picker/selection_summary.py` — collective selection icon/count strip.
- `omarchy_file_picker/sidebar.py` — sidebar menus, shortcut visibility, independent
  explorer windows and asynchronous device removal.
- `omarchy_file_picker/drag_selection.py` — background selection and edge scrolling.
- `omarchy_file_picker/drag_copy.py` / `drag_policy.py` — native file dragging,
  asynchronous disk policy, folder/sidebar/tab targets, highlights and scrolling.
- `omarchy_file_picker/tabs.py` — explorer tab strip and independent browser state.
- `omarchy_file_picker/network.py` / `network_ui.py` — bounded service discovery
  and explicit server/share browsing in the NAS dialog.
- `data/` — user-local portal, D-Bus, desktop, and systemd templates.
- `install.sh` / `uninstall.sh` — reversible user installation.
- `scripts/user-install.py` — user-local development installation and migration.
- `scripts/install-system.py` — package layout staging, never user configuration.
- `scripts/prepare-release.py` / `scripts/verify-release.py` — deterministic
  archive, pinned AUR metadata, native package build and asset verification.
- `packaging/PKGBUILD.in`, `releases/`, `.github/workflows/package-check.yml` —
  release inputs and CI; `docs/INSTALL.md` / `docs/RELEASING.md` own distribution
  instructions. `dist/` contains ignored generated review artifacts.
- `omarchy_file_picker/updates.py`, `launcher.py`, `portal_setup.py`,
  `release.json` — manual updates, diagnostic commands and per-user portal choice.

## Development

Canonical repository: https://github.com/themediastandard/gudfiles (`main`).
The local `origin` remote points there and is the default push destination.
`main` tracks `origin/main`; the older `personal` remote remains a historical
reference. The primary application and portal IDs and installation paths remain
unchanged; picker windows add the dedicated child application ID documented above.

```bash
python -m unittest discover -v
PYTHONPATH=. python tests/ui_filename_display.py
PYTHONPATH=. python tests/ui_folder_locations.py
# With POINTER_QA_ISOLATED=1 and XDOTOOL on an isolated X11 display, this also
# tests physical folder right-clicks. FOLDER_LOCATIONS_SCREENSHOTS saves captures.
PYTHONPATH=. python tests/ui_list_details.py
# On a disposable Xvfb display with GDK_BACKEND=x11 and XDOTOOL available:
POINTER_QA_ISOLATED=1 PYTHONPATH=. python tests/ui_name_resize.py
POINTER_QA_ISOLATED=1 PYTHONPATH=. python tests/ui_view_status.py
POINTER_QA_ISOLATED=1 PYTHONPATH=. python tests/ui_rating_columns.py
POINTER_QA_ISOLATED=1 PYTHONPATH=. python tests/ui_mount_controls.py
POINTER_QA_ISOLATED=1 PYTHONPATH=. python tests/ui_trash_inline.py
THUMBNAIL_NEF=/path/to/sample.NEF PYTHONPATH=. python tests/ui_thumbnails.py
THUMBNAIL_MODE=open PYTHONPATH=. python tests/ui_thumbnails.py
THUMBNAIL_MODE=save PYTHONPATH=. python tests/ui_thumbnails.py
# Read-only local timings, nine links to a supplied JPEG; run each mode separately:
BENCH_MODE=browser PYTHONPATH=. python tests/benchmark_thumbnails.py /path/to/photo.jpg
# On a disposable Xvfb display with GDK_BACKEND=x11 and XDOTOOL available:
POINTER_QA_ISOLATED=1 PYTHONPATH=. python tests/ui_context_hover.py
POINTER_QA_ISOLATED=1 PYTHONPATH=. python tests/ui_context_dismiss.py
# Creates/restores only disposable fixtures in ~/.cache through the desktop Trash:
TRASH_QA_LIVE=1 PYTHONPATH=. python tests/ui_trash_browser.py
GDK_BACKEND=wayland G_DEBUG=fatal-warnings PYTHONPATH=. python tests/ui_context_switching.py
TAB_MOTION_SCREENSHOTS=/tmp/gudfiles-tab-motion PYTHONPATH=. python tests/ui_tab_motion.py
SEARCH_QA_SCREENSHOTS=/tmp/gudfiles-search PYTHONPATH=. python tests/ui_search_scope.py
TOOLBAR_QA_SCREENSHOTS=/tmp/gudfiles-toolbar PYTHONPATH=. python tests/ui_toolbar.py
PYTHONPATH=. python tests/ui_sorting.py
LIGHT_THEME_QA_SCREENSHOTS=/tmp/gudfiles-light PYTHONPATH=. python tests/ui_light_theme.py
SOUND_QA_SCREENSHOT=/tmp/gudfiles-sounds.png PYTHONPATH=. python tests/ui_action_sounds.py
HELP_QA_SCREENSHOTS=/tmp/files-help PYTHONPATH=. python tests/ui_help.py
PYTHONPATH=. python tests/ui_dialogs.py
PYTHONPATH=. python tests/ui_transfers.py
POINTER_QA_ISOLATED=1 PYTHONPATH=. python tests/ui_folder_watch.py
PYTHONPATH=. python tests/ui_undo.py
PYTHONPATH=. python tests/ui_transfer_recovery.py
PYTHONPATH=. python tests/ui_move_retention.py
PYTHONPATH=. python tests/ui_transfer_destination.py
PYTHONPATH=. python tests/ui_transfer_modes.py
PYTHONPATH=. python tests/ui_transfer_visibility.py
PYTHONPATH=. python tests/ui_drag_copy.py
PYTHONPATH=. python tests/ui_tabs_drag.py
PYTHONPATH=. python tests/ui_file_management.py
PYTHONPATH=. python tests/ui_quicklook.py
RAW_PREVIEW_SAMPLES=/path/to/known-good-raws PYTHONPATH=. python tests/ui_raw_preview.py
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
PYTHONPATH=. python tests/ui_preview_aspect.py
INITIAL_PREVIEW_SCREENSHOTS=/tmp/preview-initial PYTHONPATH=. python tests/ui_preview_initial_size.py
PYTHONPATH=. python tests/ui_nas.py
PYTHONPATH=. python tests/ui_layout.py
PYTHONPATH=. python tests/ui_selection.py
PYTHONPATH=. python tests/ui_selection_summary.py
PYTHONPATH=. python tests/ui_sidebar_menu.py
PYTHONPATH=. python tests/ui_sidebar_actions.py
PYTHONPATH=. python tests/ui_explorer.py
PYTHONPATH=. python tests/ui_folder_picker.py
PYTHONPATH=. python tests/ui_picker_chrome.py
MINIMAL_PICKER_SCREENSHOTS=/tmp/gudfiles-minimal PYTHONPATH=. python tests/ui_minimal_picker.py
REVEAL_QA_HYPRLAND=1 PYTHONPATH=. python tests/ui_external_reveal.py
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

- Transfer identity includes device, inode and file type. Filesystems can reuse
  an unlinked regular file's inode for a symlink; cleanup must reject that
  replacement. Move publication derives the same identity from the scanned
  entry. Regression coverage simulates inode reuse so it is independent of
  the filesystem running the tests. Mocked EXIF parsing tests also mock tool
  discovery, allowing headless CI to verify parsing without ImageMagick.

- Sound cues report successful batches, not individual files or action requests.
  Drag batches use the drop cue; other transfers/conversions use completion.
  Assets install with the Python package. Missing `paplay`, files or audio output
  fail silently without changing file-operation results. The saved `sound_effects`
  boolean defaults to true; unknown/malformed preference values use that default.
- Sound QA uses a disposable silent player for process/timeout checks and spies
  for native action routing. Actual Trash fixtures must live on the home
  filesystem, with isolated `XDG_DATA_HOME`; GIO refuses Trash on `/tmp`'s system
  mount. Use a separate client identity for any live audio checks. Never mute
  Gudfiles previews or the global output to silence tests.

- When restoring list keyboard navigation after rebuilding FlowBox children, use
  the FlowBox's `child_focus()` to initialize its native cursor. Direct child
  `grab_focus()` can leave the old internal cursor invalid; a subsequent native
  move reproduced a GTK crash in an isolated test. `tests/ui_list_navigation.py`
  exercises actual Up/Down/Shift/Ctrl/Enter keys using disposable Xvfb + xdotool,
  including view changes, full-row scrolling, boundaries, folder-only/Save modes
  and editable/sidebar safety. It uses the same `POINTER_QA_ISOLATED=1` guard and
  optional `XDOTOOL` path as the existing isolated pointer suite.
- `focus_file()` restores a specific file with the child's `child_focus()` while
  preserving selection and suppressing selection callbacks. Direct `grab_focus()`
  after stepping through Quick Look left GTK's cursor on the originally opened
  file, so the next arrow jumped from the wrong item. Column focus restoration
  shares the helper. `tests/ui_arrow_navigation.py` uses the same isolated Xvfb
  setup to exercise real spatial keys, Shift/Ctrl, view/sort handoff, menus,
  scrolling, sorted preview navigation/close and nested column transitions.
  Pointer fixtures scroll target rows into view and wait for GTK's scroll
  animation before clicking; stale coordinates can click a different row.
- `tests/ui_column_clicks.py` uses isolated Xvfb/xdotool to check first clicks in
  deeply scrolled columns (including transient adjustment changes), ancestor
  context clicks and visible populated/empty/reselected children. Set
  `COLUMN_CLICKS_QA_SCREENSHOT` for an optional native snapshot.
  `tests/ui_archives.py` uses the same `POINTER_QA_ISOLATED=1` / `XDOTOOL` setup
  for real ZIP double clicks in all views, output bytes, collision naming,
  running/success/error notices, duplicate and close guards, tab changes, post-
  refresh arrow navigation and Open/Save selection. `ARCHIVES_QA_SCREENSHOT`
  captures the completion notice. Unit checks: `python -m unittest tests.test_archives -v`.
  Refreshed column rows must initialize GTK's native cursor through `focus_file`
  after allocation. Directly setting root focus reproduced a SIGSEGV on the next
  Up key after ZIP extraction; the regression now exercises that actual key.
- `tests/ui_sorting.py` uses disposable timestamps and preferences to verify all
  eight sort choices in all views, native row order, selection, folder grouping,
  search/tabs and saved explorer/Open/Save choices. `SORT_QA_SCREENSHOTS=/tmp/sort`
  optionally captures the window and native menu for visual review.
- RAW support reuses the workstation's `raw-preview` helper rather than loading
  camera decoders into GTK. The helper, desktop RAW MIME database and decoder
  packages must already be installed; `install.sh` only installs the picker.
  Native RAW QA accepts supplied samples read-only, isolates app preferences,
  verifies Space/Escape, navigation, zoom/fit, responsive loading, orientation,
  cancellation and stable geometry. `RAW_PREVIEW_SCREENSHOTS=/tmp/raw-preview`
  captures its own widget tree. The tests float only their disposable window.
  Complete CR2/CR3/ARW/NEF/RAF/RW2/ORF/PEF/KDC/X3F samples and a DNG preview
  fixture passed. Decoder tests cover child-process cleanup, timeout, bounded
  concurrency and missing/failed helpers. File hashes and sidecars are checked.
- Keep `help_catalog.py` current whenever a user-facing capability or shortcut
  changes. Describe shipped behavior and its entry point; do not list planned
  features. The guide derives its navigation and counts from this catalog.
- Help QA uses disposable files/preferences and native GTK signals. It verifies
  light/active themes, categories, global and shortcut searches, long/no-result
  queries, repeat open/close, F1 across views and Quick Look, picker isolation,
  and owner teardown. About checks cover the exact creator/URL/license text,
  link activation without launching a browser, license search, expansion and
  bounded compact layouts. Optional captures show the actual GTK windows.
- No files under `/usr/share/omarchy` are modified.
- `theme.prepare_colors()` adapts light terminal palettes to native UI roles
  without rewriting the raw palette. Use accent fills for backgrounds and
  `accent_ink`/`error_ink` for small text; verify secondary text and label hues
  against both selection and hover surfaces. Native GTK `windowhandle.titlebar`,
  placeholder opacity, popup arrows and `video controls.osd` need explicit light
  styling; styling only the main window leaves inherited toolkit colors behind.
  `tests/ui_light_theme.py` checks actual GTK foregrounds and captures five light
  palettes, three views, menus, Help, Transfers, rename and previews. Its optional
  FFmpeg fixture has no audio and uses a distinct QA application identity.
  Xvfb is useful for isolated visual checks; Help's compact-window size assertions
  assume native Wayland geometry and should run on the desktop session.
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
- The transfer engine copies into private `.omarchy-transfer-<id>` directories
  beside the final outputs. It uses directory descriptors, no-follow opens,
  exclusive file creation, inode ownership checks, SHA-256 verification and
  Linux `renameat2(RENAME_NOREPLACE)`. Unsupported destination publication fails
  closed, without an overwrite-prone fallback. See the
  [Linux rename documentation](https://man7.org/linux/man-pages/man2/rename.2.html).
  Each selected top-level copy appears only after its entire tree is verified.
  Resume rechecks source device/inode, mode, size, mtime and ctime, compares saved
  bytes, and rescans folder membership before publication. An ambiguous rename
  receipt can be reconciled only against the exact owned inode. Cancellation and
  restart never remove final outputs or unknown/replaced staging entries.
- Transfer batches support regular files, directories and symlinks, capped at
  100,000 entries per batch and 100 visible jobs per window. Staging/scanning and
  filesystem I/O run off GTK's main thread; scanning starts when a job starts.
  File data, links, basic mode bits and mtime are copied; owner read/write (and
  folder traversal) remain enabled for recovery. ACLs, xattrs, original ownership,
  sparse allocation and hard-link relationships are not archived. Special files
  are rejected. Pause/cancel wait for the current OS call; they cannot interrupt
  an atomic rename or a blocked filesystem syscall. Queue ordering is per window.
- All mode reserves normalized source/target paths to serialize conflicting
  writes and nested move/copy dependencies, while read-only copies of the same
  source to different destinations can overlap. Dependent pending jobs cannot
  overtake blocked jobs. Saved partials reserve their paths until resolved or
  cancelled. Path comparisons do not perform filesystem I/O on GTK's thread;
  symlink/bind aliases and external processes still rely on the engine's source
  verification and atomic no-overwrite publication and can fail safely.
  Cleanup occupies the same bounded worker slots. Closing waits for every
  worker, drains move receipts and preserves the previous explicit cleanup exit.
- Move receipts reach GTK in actual commit order, even when individually started
  jobs run out of visible order. Confirmed partial moves migrate ratings and
  remove only those sources from an owned cut clipboard; full completion changes
  that clipboard to destination copies. Newer clipboard contents are preserved.
  Closing Gudfiles drains final receipts before returning a picker result/quitting.
  Failed/paused transfers with no completed outputs do not trigger automatic
  directory reloads, avoiding an unnecessary read of an unavailable destination.
- Transfer QA uses disposable generated data and injected short writes, full-disk
  errors, corrupted partials, changed sources/destinations, racing collisions,
  publication receipts and move-source replacement. Native QA emits real GTK
  signals for staging/start/pause/resume/restart/cancel, checks three-view browsing,
  partial move labels/clipboard, sequential execution, bounded geometry, blocked
  I/O close handling and cleanup failure/leave-partials behavior. Only its own
  windows are floated. `TRANSFERS_QA_SCREENSHOT=/tmp/transfers.png` captures the
  native manager and a `-paused.png` companion; both layouts were visually checked.
- Mode QA verifies overlapping real fixture copies, the three-worker limit,
  live Queue/All transitions, individual pause and verified resume, all-worker
  cancellation before close, stable geometry and preference restoration.
  `TRANSFER_MODES_QA_SCREENSHOT=/tmp/transfer-modes.png` captures the native All
  mode layout. Scheduler tests cover failure isolation, related paths, dependent
  ordering, cancellation cleanup slots and mode changes while scheduling is held.
- Drag-copy QA uses GTK prepare/drop signals and actual widget hit testing for
  three-view multi-selection, same-folder copies, folder/column destinations,
  clipboard preservation, recursive/nonlocal rejection and edge scrolling.
  GTK URI serialization is round-tripped with escaped names; the source's
  explicit `text/uri-list` MIME offer and exact bytes are also read back through
  `GdkContentProvider`. End-to-end inter-application pointer DND remains a
  separate manual check. Optional
  `DRAG_COPY_QA_SCREENSHOT=/tmp/drag-copy.png` captures the native drop highlight.
  Backend tests cover collision races, ambiguous receipts, long/hidden names,
  folders/symlinks, identical basenames, verified resume and cancellation.
- `tests/ui_pointer_drag.py` uses real xdotool mouse/key input on an isolated
  Xvfb display. Set `DISPLAY` to that display, `GDK_BACKEND=x11`,
  `POINTER_QA_ISOLATED=1`, and optionally `XDOTOOL` to the executable.
  Fast file gestures must survive GTK's 100 ms DragSource hold threshold without
  FlowBox capturing a rubber band. `POINTER_QA_SCREENSHOT` captures only the
  fixture window. The test does not modify system packages or configuration.
- `tests/ui_tabs_drag.py` checks independent history/view/query/selection/scroll,
  column trails, close/reopen/reorder/shortcuts, three-view multi-file drops,
  tab hover switching, sidebar copies, geometry and refreshed source tabs.
- Visibility QA uses real gated copies with controlled elapsed-time counters
  at 299/300 seconds, concurrent completion, manual history, pause/failure and
  completion during window construction. Realize a newly created Transfers
  surface before polling: GTK 4.22 Wayland session removal dereferences a null
  toplevel when an automatic panel completes before ever being presented.
- Portal routing changes are user-local and backed up before replacement.
- The stock GTK portal remains the fallback for all non-FileChooser interfaces.
- Context popovers are parented to the stable browser stack, not replaceable
  file tiles. Entry dialogs release focus/hide before deferred destruction to
  avoid queued Wayland input-method events reaching destroyed widgets.
- Sidebar/menu QA uses isolated preferences and native Paned positions, verifies
  restored width, and checks pointer/keyboard anchors against real GTK bounds.
  It restores all three views in Gudfiles/Open/Save windows and verifies that an
  older window's unrelated save preserves the latest explicit view choice.
  Present test windows before destroying them; an unshown second window triggered
  a GTK destruction crash on this desktop. No desktop rules are changed by QA.
- Sidebar action QA emits native GTK gesture signals and hit-tests real row
  bounds, including a scrolled sidebar, in grid/list/column views. It checks
  pointer/keyboard anchors, preserved selection/history, targeted actions, hidden
  location persistence, restoration, idempotent bookmark removal and an actual
  independent explorer process. Device capabilities, busy transfers, failure and
  completion use simulated mounts; no live share is disconnected during QA.
  `SIDEBAR_ACTIONS_QA_SCREENSHOT=/tmp/sidebar.png` captures the fixture window and
  a separate `-menu.png` native popover. The QA automation keeps its menus open
  despite desktop focus changes; normal menus dismiss on outside clicks.
- Device removal uses Gio asynchronous operations with no force flag or force
  prompt. File operations, media conversions and unfinished transfers in that
  Gudfiles session block removal. Busy-device errors are shown without forcing it;
  success returns an affected browser to Home. Pending operations cancel on
  window destruction. Open in New Window starts an independent explorer process
  so closing it cannot finish/cancel an originating portal request.
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
- Aspect QA checks portrait/landscape/square images and videos, attached control
  bounds, window resizing and stale decoder callbacks. Fitting follows GTK's
  reported paintable aspect; media orientation/pixel-aspect handling remains
  owned by its decoder rather than a separate container-dimension probe.
  `ASPECT_QA_SCREENSHOTS=/tmp/preview-aspect` captures its disposable windows.
  Aspect, geometry, image zoom, Quick Look, label-palette and five-codec timing
  checks passed. The installed module matches source; an actual portrait clip
  was verified in the installed player with correctly fitted bounds and an
  unmuted, nonzero system audio stream.
- Initial-size QA observes every painted opening frame, not only final geometry.
  It delays file reads and valid decoder dimensions, then checks stable target
  bounds for portrait/landscape/square videos, file switching, cancelled/stale
  results, reduced motion, audio-only containers and decode errors. A rotated
  fixture must match the decoder's displayed geometry; the installed GTK backend
  ignores that fixture's rotation tag, so metadata-only autorotation remains a
  separate decoder limitation. Keep native autoplay behavior: sizing gates paint
  and animation, without introducing a separate media playback state machine.
- `tests/ui_preview_navigation_size.py` sends actual Up/Down keys with an already
  open portrait preview on the isolated Xvfb/xdotool display. Every painted frame
  must retain the card's bounds and full visibility through image/image,
  image/video and video/video switches, including delayed reads/dimensions,
  rapid arrows and stale callbacks. It also checks initial image sizing, reduced
  motion and transitions to landscape/text/error/audio previews. Optional
  `NAVIGATION_PREVIEW_SCREENSHOTS` captures loading and decoded native snapshots.
- Playback QA compares media timestamps with monotonic elapsed time and sets a
  distinct GLib application name before creating a player. PipeWire/PulseAudio
  remembers stream mute and volume by application name outside the isolated home;
  muting QA under the generic `python` identity can silence subsequent Gudfiles
  previews even when GtkMediaStream reports unmuted at full volume. Inspect the
  actual sink input matched by process ID when diagnosing missing sound.
- Image zoom QA emits real GTK controller signals (not physical mouse events)
  and checks zoom limits, pointer anchoring, pan bounds, reset, loading spinner,
  clipped rendered bounds and unchanged layout for wide and tall fixtures.
- Creative QA uses generated media and isolated preferences/catalogs. It tests
  real hover frame differences, media/EXIF values, labels/filtering/culling,
  editable-shortcut safety, preserved selection/geometry, and real batch rename
  with collision/race/partial-failure protection. Native screenshots are inspected
  for controls, filter card and rename dialog; no physical pointer injection.
  Swatch QA asserts actual GTK label foregrounds for all five colors in metadata,
  Quick Look and filter palettes under light, active and an explicit dark theme.
  Light swatches also require at least 4.5:1 contrast on the selection surface.
  Palette CSS must outrank generic rating-control button colors because these
  popovers remain descendants of the controls, including under dark themes.
  `CREATIVE_QA_SCREENSHOTS=1` enables optional creative UI captures. GTK can
  return no paintable node when a widget is not drawable; keep its native
  surface visible for capture. Screenshots are separate from behavior QA.
- UI smoke tests require a desktop session and temporarily use the clipboard;
  file actions run only against a disposable fixture with isolated preferences.
- Dialog QA exercises light/active palettes, bounded long paths and names,
  zero-size files, folders, broken symlinks, mixed totals, collision recovery,
  Return/Escape, titlebar close, confirmed fixture deletion and Save replacement
  result semantics. `DIALOG_QA_SCREENSHOTS=/tmp/dialogs` saves native captures.
  To exercise Return, emit `activate` on the entry's native Gtk.Text child;
  emitting only Gtk.Entry's forwarding signal does not run the default action.
- Selection smoke tests exercise GTK's native range/toggle action signals in
  all three views, not injected mouse events; reuse native FlowBox pointer handling.
- Selection-summary QA checks folder/file/mixed stacks and counts, group labels,
  single/empty reset, no single-file media probe, and stable strip/browser/window
  geometry in all three views. `SELECTION_SUMMARY_QA_SCREENSHOT=/tmp/selection.png`
  optionally captures the native strip from disposable fixtures.
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

- September 21 conditional-preview verification: 295 unit tests pass. Isolated
  native tests exercise empty, folder, document, photo, video and mixed selections
  across grid/list/columns, browser/Open/Save and active/light palettes. They
  verify mapped visibility, independent totals, single-media rating scope,
  recovered browser height and stable outer dimensions. The existing compact
  picker and status-bar suites pass. All 64 installed runtime files match source;
  atomic replacement retains a rollback copy and leaves existing windows open.

- September 21 Recents replay fix: completed transfer receipts were being
  replayed into Recents on every launch. Recovery still applies annotation
  receipts, but ignores those historical events for folder activity; new
  completions still update Recents. A tabs/drag fixture had also persisted
  receipts through the real exported XDG_STATE_HOME despite mocking Path.home().
  That test now isolates its state directory. 295 unit tests pass, including
  real journal reopen followed by a new move. Installed tabs/drag and recovery
  tests pass, with the live history/receipt files unchanged before and after.
  No verified test-root entries remain in live Recents. Existing active windows
  retain their recovery locks; unrelated history and receipts were preserved.
  Installed empty-state labels measure 10 pixels and align with section titles.
- September 21 shortcut-removal follow-up: 294 unit tests pass. Installed native
  menus remove Favorites and Recents independently, preserve folder contents,
  and keep removed Recents absent after passive refresh in all three views,
  four window modes and active/light palettes. Persistence/revisit and locked
  deletion tests pass. The later empty-state styling request restores uppercase
  placeholders aligned with the section headings.
- September 21 Favorites/Recents verification: 293 unit tests pass, including
  concurrent SQLite connections, duplicate paths, five-folder eviction, reopen,
  locked writes, corruption preservation and shortcut-only removal. Native tests
  against source and installed code cover physical folder right-clicks, add/remove,
  selection preservation, cross-window refresh, navigation/clipboard/preview/
  annotation history, disabled-file folder pickers, actual Open/Save results,
  unavailable folders and write-error recovery in all three views and four window
  modes with active/light palettes. Screenshots were reviewed at the compact
  window size. Native Wayland sidebar actions also pass, including bookmark
  preservation, hide/restore, device guards and independent windows.
  Installed transfer-destination and tab/drag suites pass; real copy completion
  checks assert destination/source ordering in Recents. The portal remains active.
  All 64 installed runtime files match source; atomic package exchange retained
  a rollback backup and left existing windows open. Reopen to load the changes.
  The older `ui_columns.py` still fails its folder-only-entries assertion on both
  unchanged HEAD and this version: current folder pickers intentionally show
  disabled files. The new feature suite tests that current contract. The batch
  rename suite passes its action assertions but its dummy MOV fixtures produce
  expected thumbnail-decoder errors; these are distinct from GTK callback errors.
- September 21 filename truncation correction: reproduced a 120-pixel header
  with a 952-pixel filename cell in a wide window. Earlier resize checks used a
  narrow viewport and inspected only the first short-name row, missing spare-space
  allocation. The regression now physically narrows columns in an 1800-pixel
  window and compares every row/cell against its heading, including long offscreen
  Unicode names. Labels constrain their natural width while retaining native
  ellipsis; default widths stay compact and fitting does not become a new-window
  default. All 289 unit tests pass. Installed wide-window pointer checks pass in
  browser/Open/Save/folder modes and active/light palettes, including new-window
  defaults after fitting. Existing column reordering and metadata/alignment suites
  pass in three palettes. The narrowed long-name snapshot was visually checked;
  all 63 runtime files match source and the portal remains active.
- September 21 file-area bar verification: 289 unit tests pass. Isolated X11
  pointer/keyboard tests cover slider endpoints, real tile dimensions, row and
  selection preservation, grid-only sensitivity, persistence, center alignment,
  missing sizes and stale-result cancellation in browser/Open/Save and two themes.
  Native thumbnail regression covers 1,000 images (0.21-second grid switch,
  20 resident thumbnails), visible-only loading and cancellation. Existing popup
  thumbnail checks pass in all four modes/two themes; the native Wayland selection
  summary suite passes in grid/list/columns. Folder totals intentionally exclude
  directory contents, and mixed summaries label bytes as file sizes only.
  All 63 installed runtime files match source after an atomic package exchange
  with rollback backup. The installed bar passes the same pointer/keyboard suite;
  reopen existing windows to load it.
- September 21 name-resize and picker-size verification: 288 unit tests pass.
  Real isolated X11 drags/double-clicks cover fit of offscreen Unicode names,
  cancellation, persistence, view switching and horizontal alignment in browser,
  Open, Save and folder modes in active/light palettes. Existing list sorting
  and physical column-reordering suites pass in three palettes. Picker results,
  caller options and Copy/Move destination suites pass. The installed package
  matches all 62 source runtime files and passes resize/picker-chrome checks.
  A real Wayland picker opens floating at 1750×1200 with compact neutral actions;
  the portal stays active. The user-local picker rule now lets the app size itself
  instead of inheriting Omarchy's generic 875×600 floating-window rule. Reopen
  existing windows for updated code; no public release was published.
- September 21 minimal-popup/list-thumbnail verification: all 288 unit tests pass.
  Native isolated X11 checks cover browser/Open/Save/folder modes in active/light
  palettes, real PNG/video list textures, preserved compact rows, visible-only
  decoding, scrolling, view switching and worker cleanup. Popup footers without
  caller options remain at most 46 pixels tall; their preview strip is unmapped
  and empty. Header/picker checks at 820/960/1200 pixels preserve selection,
  filename entry, caller filters, custom choices and returned URIs. Folder-only
  dialogs, Copy/Move destination selection, list metadata/sorting/columns in three
  palettes, and the 1,000-image grid regression pass. Open/Save snapshots were
  visually inspected. Installed minimal-picker, header/results, folder-picker and
  explorer suites pass; all 62 runtime files match source after atomic package
  exchange with rollback backup. The portal stayed active; reopen existing
  browser/popup windows to load these UI changes.
- September 21 thumbnail performance verification: 288 unit tests pass, including
  preserved EXIF rotation and original dimensions with the single-pass decoder.
  Native Wayland checks pass in browser, Open and Save modes with 1,000 image
  entries, viewport loading, cancellation, corrupt-RAW fallback and navigation
  recovery. A controlled nine-tile fixture linked to one 6048×4032 NAS JPEG
  measured full visible thumbnail completion before/after: browser 4.07→2.17s
  cold and 0.436→0.044s cached; Open 3.95→2.12s and 0.446→0.054s; Save
  4.09→2.22s and 0.447→0.051s. Cold means no app thumbnail cache; OS/NAS caches
  were not flushed. These are local samples, not general latency guarantees.
  The native timing script owns fixture construction and measurement boundaries.
  Installed with an atomic package exchange and rollback backup; all 62 runtime
  files match source. All three native mode suites pass against the installed
  package, and its Save benchmark measured 2.17s uncached / 0.048s cached for
  nine tiles. The portal stayed active; no new core dumps were recorded during
  the performance checks. Reopen existing windows to load the scheduler changes.
- September 21 decoder verification: reproduced SIGABRT and the thread-creation
  error with the old limit on a NAS camera JPEG. The patched decoder passed that
  photo plus seven neighboring JPEGs with two concurrent workers and unchanged
  source hashes. All 287 unit tests pass, including camera-JPEG decoding, bounded
  failure diagnostics/retry, cache integrity, cancellation and descendant cleanup.
  Native Wayland thumbnail checks pass against source and installed code: 1,000
  large images, 16 resident thumbnails, about 0.22-second grid switching, scrolling,
  cancellation and corrupt-RAW icon fallback/recovery. The installed decoder also
  passed the original failing NAS photo. All 62 runtime files match source after
  an atomic package exchange with rollback backup under
  `~/.local/state/gudfiles/install-backups`; the portal stayed active. Existing
  windows should reopen for the updated parent-side diagnostic logging. No new
  core-dump events occurred during verification. This fixes the reproduced worker
  abort; it is not an exhaustive guarantee against other application crashes.
  Version 0.1.1 release notes are prepared; no new release has been published.
- September 20 friend preview verification: all 285 unit tests pass. Isolated
  X11 GTK folder-picker, picker-chrome, explorer, Help, transfer-destination and
  hover-scrub suites pass without callback exceptions. `makepkg` built the
  0.1.0-1 package; `verify-release.py` verified checksums, metadata, license and
  user-data boundaries. All 61 packaged runtime files match source; extracted
  package version/doctor commands pass. The distribution tests also verify
  deterministic archive bytes and install/remove preservation. These checks
  do not substitute for a fresh Omarchy install and portal logout/login test.
- September 20 popup verification: 285 unit tests pass. Native isolated GTK
  checks verify folder contents, disabled file activation, nested columns,
  folder-only returned URIs, irrelevant file filters, computer-search acceptance,
  empty-folder recovery and SaveFiles. Explorer/Open/Save/folder headers measure
  30 pixels at 820/960/1200 widths in active/light palettes; location editing,
  preview guards, caller choices and Open/Save result files pass. The Copy/Move
  destination suite passes across all views and both palettes. Snapshots were
  reviewed. The installed package was staged from the existing runtime with
  only model.py, picker.py and theme.py changed, then atomically exchanged with
  a rollback backup. Installed folder-picker and explorer/Open/Save checks also
  pass, and all 62 runtime files match the tested stage. Existing windows must
  reopen to use the new code.
- September 19 column-motion/sidebar/toolbar update: 234 unit tests pass.
  Isolated physical-input checks exercise live header/cell reordering before
  persistence, shaded slots, the floating drag label, fixed Name by mouse/key,
  cancellation by Escape/outside release, edge scrolling, keyboard boundaries,
  saved order and reopened windows in active/light/dark palettes. The drag
  gesture belongs to the stable viewport so moving headings do not distort
  pointer coordinates. Reordering retains row widgets, selection and sort.
  Native metadata alignment and sorting checks pass; toolbar checks cover
  820/1200 pixels, all controls, search, and preview sensitivity. Simulated
  mounts with real pointer clicks verify distinct navigation/removal targets,
  supported-only icons, duplicate/pending states, busy/error/retry, no-force
  unmount/eject and sidebar refresh. Existing native sidebar action checks pass.
  No user mount was disconnected during verification. Installed pointer suites
  also pass for column dragging and mount controls in all three palettes.
  Picker navigation/long-path checks retain the window size. All 58 installed
  runtime files match source; seven changed modules have a rollback backup.
  Existing windows need reopening to load these changes.

- September 19 menu/Trash update: 234 unit tests pass. Right-click menus now
  use 24-pixel rows, 14-pixel icons, 12-pixel Noto Sans labels, 4-pixel outer
  spacing, subtle 6-pixel corners and no anchor arrow; file, background,
  submenu and sidebar menus share these styles. Physical pointer checks cover
  inside/outside clicks after delayed hover close, sibling switching, Escape
  and toggling. The previously missed failure reproduced with an outside click
  450 ms after leaving a child: GTK routed it to the root without autohiding.
  A root capture gesture now dismisses clicks outside its allocation. Native
  Wayland checks cover popup ordering; isolated X11 checks cover real input.
  Desktop clicks and no click-through to Search are separately verified.
- Trash in the sidebar opens in the main browser, with original folders,
  deletion dates, multi-selection, Refresh and Restore Selected. It has its own
  breadcrumb, sidebar highlight and tab title, participates in Back/Forward,
  and supports independent tab selections and search of names/original paths.
  File-only toolbar controls and picker acceptance are disabled in Trash;
  hidden ordinary-folder selections cannot receive file actions. `trash.py`
  reads GIO's `trash:///` and restores only current entries to their recorded
  absolute destinations, with no overwrite. `trash_ui.py` performs reads/moves
  off the GTK thread, reports partial results inline, preserves failed rows,
  and cancels/discards reads after leaving the location. Restoration continues
  through navigation without pulling the user back; its receipt survives
  refresh or return. Window close is guarded during file operations. Existing
  files are never replaced. Missing original parent folders or unavailable
  mounted volumes produce a visible failure; no destination is guessed.
  Native active/light/dark tests use only uniquely named owned fixtures and
  verify real file/folder bytes, collisions, partial success, unavailable/retry,
  empty/reopen, leave-during-read and sidebar hide/restore. Isolated physical
  pointer/keyboard checks cover row selection, context dismissal, tabs/history,
  asynchronous search focus, restore during navigation, and Save/folder safety.
  Permanent deletion
  remains the existing confirmed file action; the new Trash browser is for
  recovery and does not offer Empty Trash. Installed real-GIO checks also pass;
  all 58 installed runtime files match source, with rollback backups. Existing
  windows need reopening to load the new sidebar and visual changes.

- September 19 rating/order/font update: 230 unit tests pass. Native isolated
  pointer/keyboard checks cover live and persisted ratings, failed saves,
  clearing labels, rating sort updates, selection preservation, dragging,
  Escape cancellation, edge scrolling, keyboard focus reveal,
  saved positions and reopened windows at 820/1200 pixels in active/light/dark
  palettes. The original update used Omarchy's monospace font; the subsequent
  Noto Sans change also passes the Pango-family and complete gesture checks. Existing native
  list metadata/alignment, toolbar, sorting and preview-aspect checks pass.
  Column moves use an internal GTK drag gesture and reorder existing widgets;
  the native cross-window DnD path showed a GDK lifecycle warning when test
  windows changed, so it is not used for this internal-only interaction.
  The final gesture suite passes with GTK warnings treated as fatal.
  The same complete suite passes against the installed package. All 56 runtime
  files match source; eight changed modules and display preferences have a
  rollback backup. Rating is enabled beside Name in the current user's saved
  layout. Existing windows need reopening to load the update.

- September 19 preview compacting: 228 unit tests pass. Native Wayland checks
  cover image/video aspect and stable parent geometry at 820, 1200 and 1400
  pixels, active/light/dark renderings, opening frames, delayed preparation,
  cancellation, stale results, Quick Look keys/focus, PDF/text/error fallback,
  image zoom/pan and five-codec real-time playback/pause/seek/resume/close.
  One initial-size run crashed in a GStreamer `GstPlay` worker while GTK was
  releasing objects; the unchanged baseline and a changed-source rerun passed.
  The intermittent cause remains unconfirmed; no playback-lifecycle code was
  changed. Physical arrow-navigation QA was unavailable without Xvfb.
  Updated preview/theme modules are installed with a rollback backup; existing
  windows need reopening. Installed aspect and Quick Look verification and
  final runtime parity are recorded with this change.

- September 19 icon/divider refinement: isolated native GTK checks confirm a
  11-pixel icon inset in list/columns, right-edge alignment of the last metadata
  column across column choices, and a 1-pixel sidebar divider with identical
  rendered pixels on hover, and real pointer dragging with persisted width in
  active/light/dark palettes. The native list assertions also pass under isolated
  X11 window resizing (alignment, scrolling, menus, saved settings, sorting and
  selection). Live Wayland geometry runs were inconclusive. Updated runtime
  modules are installed with a rollback backup; reopen existing windows.

- September 19 full-width file rows: native list/column bounds confirm zero
  horizontal outer inset while retaining 2-pixel vertical gaps. Pinned headings,
  column alignment, horizontal scrolling and list behavior pass at 820/1200
  pixels in active/light/dark palettes. Native selection snapshots were reviewed.
  The updated theme is installed with a rollback backup; reopen existing windows.

- September 19 edge/selection refinements: native bounds confirm zero outer
  tab-row gaps, + flush right, and no gap between the last tab and +. Tab-motion
  checks pass in active/light palettes at 820/1200 pixels. Toolbar QA passes with
  the requested 30-pixel heading and 14-pixel icons. Native list/column bounds
  measure exactly 2 pixels between rows; list pitch is 30 pixels. All-view range,
  toggle, discontiguous and Select All checks pass. Rendered top-bar/headings
  pixels still match before/after hover in active/light/dark palettes. The four
  changed runtime modules are installed with a rollback backup; all 56 runtime
  files match source. Reopen existing windows to load the refinements.

- September 19 hover correction: native rendered PNGs are identical before and
  after GTK hover state for the top toolbar, breadcrumbs and list headings in
  active/light/dark palettes. The native toolbar regression passes at 820/1200
  pixels. Both changed modules are installed with a rollback backup and complete
  runtime/source parity; reopen existing windows.

- September 19 compact surfaces: 228 unit tests pass. Native Wayland list and
  tab-motion suites pass at 820/1200 pixels; toolbar, destination picker and
  five-palette checks pass. Dialog QA now includes an explicit dark palette,
  alongside active/light, and verifies bounded long content, Enter/Escape,
  collision errors, safe confirmation defaults and disposable file outcomes.
  Batch Rename, NAS validation/discovery, Transfers pause/resume/cancel/close
  guards and Help/About/search/lifecycle checks pass. Native snapshots of the
  browser, dialogs, NAS, batch rename, Help/About, Transfers and destination
  picker were visually inspected. Help QA sizes only its own Wayland windows;
  minimum-size assertions use native surfaces to account for X11 decorations.
  The code package was atomically exchanged with a complete runtime rollback
  backup in `~/.local/state/gudfiles/install-backups`. All 56 installed runtime
  files match source. Installed dialog and Help suites pass on isolated Xvfb;
  an installed Wayland fixture confirms three 24-pixel tabs, a 25-pixel strip,
  live share-only mount labels and no indicators. Existing sessions are retained;
  reopen Gudfiles to load this update. System-owned credential prompts remain
  GTK/GVfs surfaces; no authentication flow or desktop theme was changed.
  The AI-OS project route already points here; unrelated dirty AI-OS files were
  preserved. No new shared procedure is needed for this visual pass.

- September 19 list headings: 227 unit tests passed, including numeric media
  sorting, unavailable birth time, versioned cache invalidation, changed sources,
  worker cancellation and replacement of queued batches. Native
  `PYTHONPATH=. python tests/ui_list_details.py` passed pinned heading/cell
  alignment, horizontal scrolling at 820/1200 pixels, pointer/keyboard column
  menus, preference restoration, real-video FPS/resolution sorting, retained
  selection and visible-only reads in active/light/dark themes. Set
  `LIST_QA_SCREENSHOTS` for native captures. Selection, sorting, search and compact
  toolbar regressions also passed. Tests present fixture windows before destroying
  them; destroying a never-presented PickerWindow triggered a GTK surface crash
  during test development. The combined runtime, including compact sidebar and
  flat top-bar controls, is installed with a rollback backup; all 56 runtime
  files match source. List-heading and all-view selection suites also passed
  against that installed package, measuring 28-pixel list rows. Reopen existing
  windows to load the update. Unrelated AI-OS changes remain untouched.

- September 19 sidebar cleanup: all 222 unit tests passed. Native Wayland
  sidebar-action QA passed across grid/list/columns, including selection and
  history preservation, bookmark hide/restore, mount actions and popup lifetime.
  Active/light/dark fixture snapshots were reviewed; grouping (including MTP
  cameras), + connection control, available icons, mount removal and
  180/220/280-pixel widths passed after the requested extra compaction. Native
  splitter persistence and Open/Save/browser view restoration also passed after
  correcting the QA selector to the current picker application ID. Explorer view
  icons now sit directly in the top-bar action row; icon buttons have no nested
  group surface, filled background or border, with accent hover/active feedback.
  The complete native toolbar suite passed in active/light palettes at 820–1200
  pixels. The verified sidebar/top-bar changes were isolated from concurrent list
  work, then installed as three atomic module replacements with a rollback backup.
  Installed bytes match the verified staging copy; a fresh installed Gudfiles
  window was opened and visually checked. The saved sidebar width is 220.
  The list-column task owns the later combined update and full source parity.

- Thumbnail verification (2026-09-19): the native fixture with 1,000 24-megapixel
  images switches list→grid in about 0.14 seconds, retains only visible thumbnails
  (16 in the measured viewport), keeps GTK timers responsive, releases textures
  when scrolling, cancels delayed workers on view changes and recovers on return.
  Real Nikon NEF thumbnails in the grid/selection strip pass with unchanged source
  hashes; corrupt RAW retains an icon and navigation recovers. Unit tests cover
  real image/video decoding, fresh cache reuse, changed sources, corrupt cache
  repair, timeouts and descendant cancellation. All 222 unit tests pass, alongside
  native selection, hover-scrub, file-management, selection-summary and preview-
  aspect regressions. The full thumbnail suite also passes against the installed
  runtime. Five modules were installed atomically with a rollback backup while
  the existing user window stayed open; reopen it to load this revision. All
  runtime files match source. Prior logs show a Gudfiles session
  reaching 5.3 GB; no matching core dump or OOM record establishes its exact exit
  cause. File enumeration/widget construction remains proportional to folder size;
  disk cache eviction and exceptionally large/network-stalled folders are not
  covered by the 1,000-file result.
  Decoder resource limits must allow memory-backed pixel files: Glycin's full
  decoded image uses `memfd`, so a small `RLIMIT_FSIZE` can hang an otherwise valid
  large-photo decode. The regression uses real 6000×4000 pixels for this reason.

- Resolve drag compatibility fix (2026-09-18): Gudfiles previously exposed its
  private marker plus the GTK-only `GdkFileList` type, but no explicit
  `text/uri-list` MIME format. DaVinci Resolve runs through Xwayland on the
  verified workstation and could not consume that in-process GTK type. Sources
  now offer standards-based, URI-escaped CRLF bytes alongside `GdkFileList`.
  The native three-view drag and tab-drag suites pass, including exact provider
  MIME/byte readback, as do all 216 unit tests. The guarded user installer made
  a rollback backup and the installed source advertises both formats. A real
  pointer drop into Resolve remains the final acceptance check because the live
  Wayland-to-Xwayland pointer path was not synthesized by the test harness.

- Context-menu outside-dismissal fix (2026-09-18): GTK closes the active modal
  child first for a click outside a nested popover. The root now enables native
  cascade popdown, while the hover controller temporarily suppresses cascading
  for sibling handoffs, delayed hover closes and Escape. The native Wayland
  regression checks child-to-root dismissal, repeated sibling switching,
  explicit teardown and subsequent actions in active/light palettes with GTK
  warnings fatal. It passes against source and the installed package; all 216
  unit tests pass, and all installed runtime files match source. Physical
  pointer injection was unavailable for this pass, so the native regression
  drives the same GTK child-popdown path directly rather than synthesizing the
  compositor click.

- Submenu-switching fix (2026-09-18): reproduced on native Wayland as
  `Tried to map a grabbing popup with a non-top most parent`; the first menu
  stayed open and siblings never mapped. The prior X11-only check missed the
  protocol restriction. MenuButton's pre-popup callback now unmaps the old
  sibling before GTK maps the new one, preserving hover/keyboard state.
  `tests/ui_context_switching.py` checks real native surface ordering through
  popup and action activation, repeated forward/backward switches, dismissals
  and subsequent actions for background/file/image menus in active/light
  palettes. It passes on Wayland with warnings fatal, including against the
  installed package. Extended physical-pointer tests pass on isolated X11 at
  820/1200 pixels in both themes; all 216 unit tests pass. Installed with the
  guarded installer and a backup; all 51 installed runtime files match source.

- Destination file visibility (2026-09-19): reproduced hidden existing files in
  the native destination test before the fix. All 234 unit tests pass; expanded
  `tests/ui_transfer_destination.py` verifies visible, disabled file rows,
  nested columns, whole-computer results and rejected file activation in all
  three views and active/light palettes, alongside real copy/move outcomes.
  Native search and explorer/Open/Save regressions pass. An isolated runtime
  staged from the installed package plus only this fix passes the same destination
  suite. The five-file fix was installed with the guarded installer and a rollback
  backup, without deploying the concurrent Trash changes. All 58 installed runtime
  files match that tested stage, and its installed destination suite passes.

- Destination-transfer verification (2026-09-18): all 216 unit tests pass.
  `tests/ui_transfer_destination.py` checks native context hit testing, single/
  multiple selection, both destination-selection methods, real recursive copy
  and move bytes, same-folder duplication, collision preservation, cross-volume
  move refusal, held-queue recovery, queue errors, unchanged clipboard, repeated
  completion, cancellation and owner cleanup in grid/list/columns and active/
  light themes. Dialog, file-management and explorer/Open/Save regressions pass,
  as do real-pointer context-menu checks at 820/1200 pixels in both themes.
  Native prompt snapshots were reviewed. These checks use an isolated Xvfb
  display and disposable data, not live-user transfers. Installed with the
  guarded `./install.sh` and an automatic backup; all 51 runtime files match
  source. The complete destination suite also passes against the installed
  package, as does a native Wayland launch/window-close/process-exit check.
  The later menu cleanup replaces unavailable folder-copy/folder-move icon
  names with existing neutral symbolic icons and removes More. Active/light
  native menu snapshots, icon availability, file-management regression and
  all 216 unit tests pass; the updated runtime is installed and matches source.

- Six older standalone browser processes were found without compositor windows
  or active transfer workers on September 18. After explicit user approval,
  those exact processes exited on SIGTERM before installation. Their stdout
  and stderr were `/dev/null`, with no matching journal diagnostics, so the
  original cause is unconfirmed. Fresh installed launches and normal closes
  pass. If this recurs, capture startup/close errors before assuming that no
  visible window means no retained queue; paused state may still exist.

- Context-hover verification (2026-09-17): real pointer/keyboard input on an
  isolated Xvfb display passes in active/light themes at 820/1200 pixels, with
  submenus opening both left and right. Checks cover hover, crossing popup
  boundaries, sibling switching, quick pass-through, disabled rows, click
  toggling, keyboard opening/Escape, resuming the mouse, an actual right-click
  and action, menu replacement and destruction during a delayed open. GTK
  callback exceptions fail the test. All 216 unit tests pass. The same pointer
  suite passes against the installed package; all 51 runtime files match source.
  Updated modules have backups, and existing windows need reopening. These
  physical-input checks use X11; live Wayland pointer input remains separate.

- Tab-motion verification (2026-09-17): native after-paint samples check gradual
  width/fade changes, equal final sizes and no final spacing jump when closing
  first/middle/last tabs. Active/light themes pass at 820/1200 pixels, including
  rapid close/reopen, reorder during motion, overflow reveal, disabling animations
  mid-transition, immediate reduced-motion actions, final-tab close and callback
  cleanup. Existing native tab/drag behavior passes; the 216 unit tests pass.
  Only fixture windows are floated/resized; native signals and rendered frames
  are exercised, without injecting keyboard/pointer events on the live desktop.
  The same motion suite passes against the installed package. All 50 installed
  runtime files match source; the three new/updated modules were installed with
  backups without closing user windows. Reopen existing windows for the update.

- Search scope verification (2026-09-17): 216 unit tests pass, including real
  subprocess recursion, hidden/type/directory constraints, duplicate basenames,
  symlink loops, overlap, permission failures, limits, timeout partial results,
  cancellation and latest-only scheduling. Native active/light 820-pixel checks
  cover all views, locations, external-result opening, tab scope/selection,
  query/scope/tab invalidation, clear, sorting, refresh, partial/error states and
  Open/Save/folder semantics. Native callbacks are checked for swallowed errors;
  result rendering/sorting uses worker metadata, with live probing reserved for
  selected-item previews/actions. Toolbar, sorting, columns, tabs/drag and transfer
  regressions pass. A real Home/system/mounted-root scan found a disposable Home
  fixture in 6.91 seconds, with 57 unreadable locations reported and no limit.
  Search is a bounded live scan, not an index; refine the query if incomplete.
  Active/light scope and result screenshots were visually reviewed.
  All 49 installed runtime files match source; the complete native scope suite
  also passes against the installed package. Eleven updated/new modules were
  installed with backups while existing user windows stayed open. Reopen those
  windows to load the feature. No desktop configuration or user data changed.

- Breadcrumb verification (2026-09-17): single-click column navigation now
  includes the opened child folder while preserving the parent's selected row
  for file operations. Up/location entry follow the displayed folder. A second
  reproduced lag came from changing the horizontal adjustment during GTK
  viewport allocation: the value reached the end while the child retained its
  previous translation. Reveal now runs after layout. The native regression
  checks actual breadcrumb bounds as well as adjustment values, equal-width
  siblings, nested/empty columns, deselection, tabs, Up and full-name tooltips.
  Breadcrumb, column, tab/drag and active/light toolbar checks pass, along with
  all 206 unit tests. Updated modules are installed with backups; all 47 runtime
  files match source. Reopen existing windows to load the changes.

- Toolbar verification (2026-09-17): 206 unit tests and native toolbar checks
  passed, including active/light layouts at 820, 960 and 1200 pixels, sidebar
  resizing, path entry, all-view Up/search, root/Recent and per-tab filters.
  Source sorting, breadcrumbs and explorer/Open/Save checks passed; tab/drag
  checks passed on rerun after an initial selection-restoration timing failure.
  The toolbar checks also pass against the installed package; all 47 runtime
  files match source. Updated runtime files were backed up without closing
  existing user windows; those windows need reopening to load the update.
  The broader Help test stops at its native geometry assertion on both unchanged
  HEAD and this version in the current desktop session. Physical X11 input
  suites were not run because Xvfb/xdotool are unavailable here.

- Portrait navigation verification (2026-09-08): actual isolated Up/Down input
  reproduced the open image card reverting to a 940-pixel-wide loading frame.
  The fix retains decoded aspect through replacement and avoids restarting the
  video entry animation. Every painted navigation frame now keeps the same
  portrait bounds through image/image, image/video and video/video switches.
  Delayed reads/dimensions, rapid arrows, stale results, close during loading,
  reduced motion and landscape/text/error/audio fallbacks passed. Loading and
  decoded snapshots were reviewed. All 206 unit tests, five-codec playback,
  image zoom, Quick Look, real all-view arrows, and Wayland aspect/window-geometry
  checks passed. All 46 installed runtime files match source; navigation,
  initial-frame and Quick Look checks also passed against the installed package.
  The portal remains active and existing NAS-transfer changes remain intact.

- NAS Trash verification (2026-09-08): both mounted SMB shares returned GIO
  `NOT_SUPPORTED` for disposable files through both their local GVfs path and
  native SMB URI; originals were preserved. Native GTK fixture checks on both
  actual shares verified the unavailable-Trash dialog, Cancel preservation and
  explicitly confirmed permanent deletion. Only fixture-owned paths were changed.
  No server recycle-bin configuration or recoverable NAS Trash was added.
  206 unit tests passed, including mixed-location selection, partial failures,
  permission/I/O errors, changed/replaced targets and symlink target preservation.
  Native all-view removal, action-sound, file-management and ZIP regressions
  passed; the NAS confirmation snapshot was reviewed. `tests/ui_trash.py` accepts
  newline-separated `TRASH_QA_MOUNT_PATHS` for unique fixtures on live shares and
  optional `TRASH_QA_SCREENSHOT`; use the established isolated Xvfb workflow.
  Installed/source parity passed for all 46 runtime files, and the native live
  NAS Cancel/delete checks passed again against the installed package.

- Column/ZIP verification (2026-09-08): 197 unit tests passed. Isolated native
  Xvfb/xdotool checks cover single and double folder clicks after deep scrolling,
  ancestor context clicks, populated/empty/reselected-child reveal, ZIP double
  clicks in all views, original/output bytes, collision naming, visible working/
  completion/error states, duplicate/close guards, tab changes and post-extraction
  arrow navigation. Folder double-click previously rebuilt the parents at scroll
  zero; horizontal reveal was also undone by viewport focus following. Both are
  covered by physical-input regressions. Column, arrow, tab/drag, transfer,
  conversion-notice and explorer/Open/Save suites passed; the original column
  suite also passed natively on Wayland. Empty-column and extraction screenshots
  were reviewed. All 46 installed runtime files match source; the column-click
  and ZIP suites also passed against the final installed package. ZIPs with links,
  special files or encryption are explicitly unsupported; real user archives
  and physical Wayland pointer input remain separate from these fixture checks.
  Existing NAS-transfer changes were preserved.

- NAS metadata fix (2026-09-07): a real SMB/GVfs copy reproduced `EOPNOTSUPP`
  from `fchmod` after successful byte verification. Copies now tolerate only
  unsupported mode/timestamp metadata; permission, I/O and flush failures still
  stop the transfer. All 185 unit tests pass. Disposable fixtures on both mounted
  NAS shares passed file/folder/empty-folder copies, duplicate naming, byte
  comparisons and injected interruption/resume, with originals preserved and
  staging cleaned. Tab drop policy selects copy for the actual NAS mount.
  Installed with `./install.sh` after the existing failed job was cancelled via
  Transfers → Cancel unfinished & close. The idle FileManager1 service was
  stopped for installation; it reactivates on demand. Installed/source transfer
  modules match, and fresh installed-engine copies passed on both NAS shares.
  Downloads was reopened with the original file selected. Failed jobs count as
  unfinished, so ordinary window close opens Transfers; use its explicit cancel
  and close control rather than repeatedly closing the panel.

- External reveal verification (2026-09-07): 182 unit tests passed. Native
  reveal QA verifies grid/list/columns, offscreen items, hidden files, multiple
  siblings, directory entries, symlinks, missing targets and cancelled startup
  navigation. It checks full-row visibility, root focus and active-window native
  cursor movement. The suite also passed against the installed package. Live
  session-bus `ShowItems` activated the updated service and a floating external
  browser with the exact escaped target; separate live launches confirmed tiled
  ordinary browsing and floating Save pickers. Native desktop-entry launches
  also verified floating file/folder targets and a tiled no-argument launcher.
  Hyprland reload/config validation
  passed. The shared `focus_file()` helper initializes GTK’s cursor;
  frame-clock reveal waits for compositor and metadata layout to settle before
  clamping scrolling. Ordinary explorer and Open/Save behavior checks also pass.

- Sort/keyboard verification (2026-09-07): 175 unit tests passed. Native sorting
  QA passed in grid/list/columns and restored explorer/Open/Save preferences.
  Real Xvfb + xdotool checks passed for spatial keys, Shift/Ctrl, view/sort
  handoff, menus/search, scrolling/edges, preview arrows/close and nested column
  transitions; the existing list and explorer/picker regressions also passed.
  Sorting, arrow and explorer suites passed against the installed runtime.
  The top bar and menu were visually inspected at desktop and 1200-pixel sizes.
  Physical keyboard testing used X11; native Wayland sorting signals also passed.
  Six updated modules were backed up before installation; runtime matches source.
- Xvfb QA must use an explicit unused high display after checking its socket,
  lock and abstract Unix endpoint. Do not use automatic `-displayfd` allocation
  on this Hyprland desktop: it claimed `:0` and disrupted the live Xwayland
  endpoint used by Parsec. The separate recovery task restored that endpoint;
  installed-copy QA on `:97` completed without touching it. Canonical isolation
  procedure: AI-OS `skills/desktop-media-qa/SKILL.md`.
- Release-preparation verification (2026-09-07): 168 unit tests passed,
  including stable version ordering, malformed/unavailable/rate-limited release
  responses, deterministic archive bytes, installer upgrades/removal with
  ratings/WAL/SHM/settings/bookmarks retained, legacy routing restoration and
  preserving later portal edits. `makepkg --cleanbuild` produced the native
  package with dependency and SHA-256 checks; `verify-release.py` verified its
  metadata, licenses and data boundaries. Packaged explorer/Open/Save, transfer
  and native Wayland Help checks passed, including asynchronous update checks
  while changing Help categories and retrying errors. Help screenshots were
  visually inspected. An isolated Bubblewrap overlay verified the real
  `/usr/lib/gudfiles` launcher layout without modifying the host. Desktop-file,
  shell syntax, workflow YAML and Git whitespace checks passed. The live
  anonymous update check correctly reports no public release. These are local
  checks, not evidence of remote CI or fresh-machine portal/login acceptance.
- The installed user-local runtime now matches source, including release/update
  UI, sorting and keyboard improvements. Generated native release packages remain
  the earlier packaging artifacts until rebuilt for publication. Close Gudfiles
  before using the development installer or migrating to the system package.

- Public distribution is pending. Confirm public hosting, tag the
  reviewed version, and verify an install plus portal activation across a login
  on a disposable current Omarchy machine before public launch. Publish the
  official assets first, then the AUR recipe using an authorized AUR account;
  neither AUR account access nor a public listing is currently established.
  Check the packaging workflow's result for the source commit being released. Developer installation
  and rollback are not substitutes for a fresh-machine package acceptance test.

- Light-theme verification (2026-09-07): 158 unit tests and native five-palette
  visual/contrast checks passed, including all three views, menus, Help, Transfers,
  rename, text preview and video-control ink. Dialog, explorer/Open/Save, native
  Wayland Help, Queue/All transfer, label-palette and NAS discovery/validation
  checks passed. Screenshots were visually reviewed. Installed `theme.py` and
  `picker.py` match source; the five-palette suite also passed against the installed
  package. A fresh installed Gudfiles window was opened and visually checked in
  the active light theme. Physical pointer interaction and full accessibility
  compliance are outside this visual pass.

- Initial video sizing verification (2026-09-07): 154 unit tests and native
  opening-frame, aspect, geometry, image zoom, Help and Quick Look checks passed.
  H264, HEVC, ProRes, VP9 and AV1 playback passed play/pause/seek/resume/stop
  checks. Loading and portrait snapshots were visually inspected. The installed
  package matches source and passes the opening-frame regression, including
  delayed dimensions, cancellation, file switching and reduced motion.

- Action-sound verification (2026-09-07): 154 unit tests passed, including real
  silent subprocess timing, cleanup, mute and asset checks. Native action QA
  exercised actual fixture Trash/delete/drop/copy operations, partial failure,
  cancellation, repeated polling and the View-menu toggle. Drag, transfer,
  Queue/All, panel visibility, conversion, Help, sidebar and explorer regressions
  passed with audio playback mocked. All four cues played successfully through
  a separate, unmuted QA stream at half volume without mixer changes. The native
  sound menu was visually inspected. Installed action/transfer checks passed;
  all 38 installed package files, including the WAVs, match source.

- Gudfiles rename verification (2026-09-07): 147 unit tests, native Help in
  light/active themes, explorer/Open/Save and transfer suites passed. Help
  snapshots were inspected. Installed modules and the desktop entry match
  source; the installed app reports Gudfiles and Gudfiles Help with the existing
  application ID. The FileChooser portal remains active and exposes OpenFile,
  SaveFile and SaveFiles.

- Tabs/drag verification (2026-09-07): 142 unit tests passed. Native drag-copy,
  tab/state, background selection, keyboard selection, columns, explorer/picker,
  transfers, Queue/All, visibility and Help suites passed. An isolated Xvfb
  display with actual xdotool input verified plain/Shift/Ctrl clicks, fast
  multi-file drags in all three views, Alt-copy, folder double-clicks, tab hover
  switching and reordering, and a real cross-filesystem tab copy to `/dev/shm`.
  Native GTK snapshots of the tab strip were visually inspected. Wayland
  handler/payload checks passed; pointer automation was isolated from Tommy's
  live desktop. External-application receivers remain a separate manual check.
  Tabs/drag changes were installed locally; tab, explorer/picker and selection
  QA also passed against the installed package. Tabs do not
  persist between app sessions. Existing explicit cut/paste across volumes
  still refuses a move; drag-and-drop chooses a verified copy automatically.
- Transfer verification: 136 unit tests and native drag-copy, transfer-visibility,
  transfer-mode/transfer/file-management,
  columns, selection, drag selection, layout, preview geometry, Quick Look,
  sidebar/menu, active filters, breadcrumbs, explorer and selection-summary
  suites passed. Live NAS copies and injected interruption/resume are now verified
  as described above; physical reconnect and real user media remain unverified.
  Resume after reconnect requires stable identities; it deliberately
  refuses to trust an unrelated replacement mount/source/partial file.
  A real disposable cross-filesystem copy and move refusal were also verified
  between the local fixture filesystem and `/dev/shm`.
  The changed Python modules were installed locally; drag-copy, visibility,
  transfer-mode, transfer, columns, file-management, explorer/picker-mode and
  selection-summary QA passed against that installed package. Installed
  modules match the source, including the concurrent selection-summary updates.
- Transfer recovery requires its private state directory to remain readable and
  writable. Unsupported safe publication or changed mount/file identities stop
  work visibly. A stopped cross-drive move may retain a held source folder;
  Resume or Keep remaining originals resolves it without guessing or overwriting.
  Journal records are limited to 100 jobs and 64 MiB per job. These safeguards
  do not make every remote filesystem support verified publication.
- Apps that bypass XDG portals keep their toolkit-native chooser.
- A NAS must be reachable and provide valid credentials for a live mount test;
  live passive discovery is verified, while authenticated share browsing and
  mounting require a user-selected server/login and remain unverified here.
  Browsing an existing authenticated mount and entering a subfolder are verified.
- Sandboxed-app and native-app Open/Save flows must both be smoke-tested after
  each portal protocol change.
