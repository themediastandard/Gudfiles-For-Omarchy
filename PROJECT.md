# Omarchy File Picker

## Purpose

Provide a fast, visual, theme-aware Open/Save dialog for Omarchy and expose it
as the desktop's XDG FileChooser portal backend.

## Current state

- List Up/Down moves the native row cursor immediately after switching views,
  keeps the entire row visible and stops at the list edges. Shift extends ranges;
  Ctrl moves focus without replacing selection. Search, filename fields, sidebar,
  Quick Look and Alt navigation retain their own keyboard behavior.
- Help and Transfers use matching 32-pixel header icon buttons with quiet idle
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
- Tab styling follows Tommy's compact Finder preference: 28-pixel rounded pills,
  bounded labels that do not expand across the strip, and a 20-pixel circular
  close button on the left. A small New Tab control stays at the right edge.
  New-tab scrolling waits for GTK layout before revealing the selected pill.
- Header Help / F1 opens a compact, searchable feature guide with seven categories,
  shortcut badges, empty-search recovery and active Omarchy colors. Ctrl+F focuses
  help search; Escape closes only help. Each browser owns one reusable guide,
  cleaned up when its Files/picker window ends. Quick Look, selection and file
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
  The last chosen view is saved immediately and restored in new Files windows
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
  the existing background selection overlay owns blank drags. Native FileList /
  URI payloads support other windows/apps; Alt advertises COPY only. Files uses
  a marker to negotiate MOVE internally, acknowledges outside sources as COPY
  so they cannot delete before queued work, and never deletes URI sources based
  solely on GDK's delete-data flag. Hover checks are bounded/latest-only;
  publication and identity verification remain the transfer engine's authority.
- Image and cached video thumbnails, selection metadata, search, file filters,
  multi-select, folder selection, Open, Save, and SaveFiles modes.
- Multi-selection metadata shows a theme-colored stack of folders/documents,
  the selected item count and a folder/file breakdown, rather than previewing
  only the first item. Shared rating controls still apply to the whole selection.
  Counts refer to selected entries, not recursively scanned folder contents.
- Multi-file summaries show the combined logical file size value without a
  "Combined size" heading, including zero-byte totals. Mixed selections exclude
  folder contents (clarified in the byte-value tooltip); unavailable
  entries mark the total as partial/unavailable instead of silently undercounting.
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
  The separate window scrolls its rows without resizing the Files browser.
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
  use atomic no-overwrite renames; cross-volume moves stop without copying or
  deleting their sources, explaining how to use Copy instead.
- Queues belong to the open Files session. Closing the transfer panel hides it;
  closing Files/finishing a picker pauses scheduling and asks whether to keep the
  session or cancel unfinished work. It waits for active I/O/cleanup to stop.
  Failed cleanup offers an explicit leave-partials exit. No automatic reconnect,
  credentials, persisted queue, background service or restart recovery is added.
- SMB/NFS NAS connection dialog backed by Gio/GVfs with native credential
  prompts; mounted shares are refreshed into the Devices sidebar.
- Reads the active Omarchy `colors.toml` on every launch.
- User-local portal installation with GTK retained as the fallback backend.
- Sidebar uses the same application background, not a contrasting white panel.
- Sidebar items have native pointer/keyboard context menus for Open, a separate
  Files window, enclosing-folder reveal, Copy Location and Properties. Right-click
  preserves the current directory, browser selection, column trail and geometry.
  Remove from Sidebar hides default locations in display preferences or removes
  only the shared GTK bookmark. Restore Default Locations is available from the
  sidebar context menu. Recent has Open/removal actions; devices expose supported
  Eject/Unmount/Disconnect actions and the NAS entry opens its connection dialog.
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
  controls. Video dimensions update when the decoder reports its display size;
  text, audio-only and unavailable previews retain the general-purpose frame.
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
  Empty, single-file and multi-selection text blocks remain vertically centered,
  with the text rows in each block sharing the same left edge.
- NAS dialog uses flat theme-colored controls, automatically searches Avahi/
  GVfs network advertisements, and offers explicit SMB share browsing, Refresh,
  saved/mounted locations, inline errors and cancellable mounting.
- Mounted-device clicks and successful NAS connections verify the local path
  on a worker thread, recover a missing GVfs FUSE bridge when available, and
  report unavailable folders. Credential prompts belong to the NAS dialog.

## Architecture

- `omarchy_file_picker/list_navigation.py` — list arrow routing through GTK's
  native cursor/selection engine, with view-button focus handoff and row reveal.
- `omarchy_file_picker/help_catalog.py` — feature descriptions, category metadata
  and search; the single content source for the in-app guide.
- `omarchy_file_picker/help_window.py` — native help window, category navigation,
  shortcut badges, search states and owner-bound lifetime.
- `omarchy_file_picker/picker.py` — native chooser UI and result protocol.
- `omarchy_file_picker/portal.py` — XDG FileChooser D-Bus backend.
- `omarchy_file_picker/model.py` — request parsing, filters, filesystem helpers.
- `omarchy_file_picker/actions.py` — validated media commands, output naming,
  and NAS address normalization.
- `omarchy_file_picker/file_actions.py` — filesystem operations and sorting.
- `omarchy_file_picker/file_management.py` — file dialogs, clipboard, shared
  GTK bookmarks and persisted display preferences.
- `omarchy_file_picker/transfers.py` — bounded Queue/All scheduling, resumable
  copies, checked staging ownership, atomic publication and cancellation cleanup.
- `omarchy_file_picker/transfer_ui.py` — native transfer window, progress/actions,
  ordered move receipts, clipboard ownership and Files/picker close guard.
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

## Development

```bash
python -m unittest discover -v
HELP_QA_SCREENSHOTS=/tmp/files-help PYTHONPATH=. python tests/ui_help.py
PYTHONPATH=. python tests/ui_dialogs.py
PYTHONPATH=. python tests/ui_transfers.py
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
PYTHONPATH=. python tests/ui_nas.py
PYTHONPATH=. python tests/ui_layout.py
PYTHONPATH=. python tests/ui_selection.py
PYTHONPATH=. python tests/ui_selection_summary.py
PYTHONPATH=. python tests/ui_sidebar_menu.py
PYTHONPATH=. python tests/ui_sidebar_actions.py
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

- When restoring list keyboard navigation after rebuilding FlowBox children, use
  the FlowBox's `child_focus()` to initialize its native cursor. Direct child
  `grab_focus()` can leave the old internal cursor invalid; a subsequent native
  move reproduced a GTK crash in an isolated test. `tests/ui_list_navigation.py`
  exercises actual Up/Down/Shift/Ctrl/Enter keys using disposable Xvfb + xdotool,
  including view changes, full-row scrolling, boundaries, folder-only/Save modes
  and editable/sidebar safety. It uses the same `POINTER_QA_ISOLATED=1` guard and
  optional `XDOTOOL` path as the existing isolated pointer suite.
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
  and owner teardown. Optional captures show the actual GTK windows.
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
  Closing Files drains final receipts before returning a picker result/quitting.
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
  GTK URI serialization is round-tripped with escaped names. Inter-application
  DND remains a separate manual check. Optional
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
  It restores all three views in Files/Open/Save windows and verifies that an
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
  Files session block removal. Busy-device errors are shown without forcing it;
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
- Playback QA compares media timestamps with monotonic elapsed time and sets a
  distinct GLib application name before creating a player. PipeWire/PulseAudio
  remembers stream mute and volume by application name outside the isolated home;
  muting QA under the generic `python` identity can silence subsequent Files
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
  Quick Look and filter palettes under light and the active desktop theme.
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
  suites passed. Live NAS transfer failure/recovery and real user media remain
  unverified. Resume after reconnect requires stable identities; it deliberately
  refuses to trust an unrelated replacement mount/source/partial file.
  A real disposable cross-filesystem copy and move refusal were also verified
  between the local fixture filesystem and `/dev/shm`.
  The changed Python modules were installed locally; drag-copy, visibility,
  transfer-mode, transfer, columns, file-management, explorer/picker-mode and
  selection-summary QA passed against that installed package. Installed
  modules match the source, including the concurrent selection-summary updates.
- Transfer queues and recovery metadata are in memory. An app crash/forced exit
  can leave hidden partial folders and does not restore the queue on relaunch.
  Normal close guards against losing it. Cross-volume copy works when the mounted
  filesystem supports the required safe publication; cross-volume move is an
  explicit limitation of this first version. A later milestone can add a durable
  journal and separately verified copy-and-delete moves.
- Apps that bypass XDG portals keep their toolkit-native chooser.
- A NAS must be reachable and provide valid credentials for a live mount test;
  live passive discovery is verified, while authenticated share browsing and
  mounting require a user-selected server/login and remain unverified here.
  Browsing an existing authenticated mount and entering a subfolder are verified.
- Sandboxed-app and native-app Open/Save flows must both be smoke-tested after
  each portal protocol change.
