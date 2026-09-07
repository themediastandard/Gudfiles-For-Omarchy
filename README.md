# Gudfiles

A visual, keyboard-friendly file manager and file picker that follows the active
Omarchy theme and serves as an XDG desktop portal backend.

Launching it directly opens explorer mode: no bottom filter/action bar, files
open with their default applications, and the explorer stays open. App-requested
Open/Save dialogs retain their filter, Cancel and Open/Save controls. Explicit
CLI `--result`, `--directory` and Save requests also retain picker controls.

## Features

- Quiet action sounds for completed file drops, copies, Trash, permanent deletion
  and media conversions. **Right-click → View → Sound Effects** toggles them;
  the choice is remembered across windows. Cancelled, failed and no-op actions
  stay silent, and rapid completions do not build an audio backlog.

- Folder tabs with separate history, view, filters, selection and scroll position
- Drag files to folders, sidebar locations or tabs: move on the same disk, copy
  between disks; hold Alt / Option to copy anywhere
- Ctrl+T for a new tab, Ctrl+W to close, Ctrl+Shift+T to reopen, Ctrl+Tab to switch
- Drag tabs to reorder; middle-click folders to open them in background tabs
Click **Help** in the header or press **F1** for a searchable, theme-matched
feature guide with categories and keyboard shortcuts. It opens in a separate
compact window, including from Quick Look and Open/Save dialogs. **Ctrl+F**
focuses its search; **Escape** closes only the guide.

The guide is maintained in `omarchy_file_picker/help_catalog.py`. Add or update
its entries whenever a user-facing feature or shortcut changes; navigation,
search results and feature counts are generated from that catalog.

- Thumbnail-first grid and compact list views
- Dense list rows with no gaps between files
- Image previews and freedesktop video thumbnail cache support
- Silent hover-scrubbing across video thumbnails, with a subtle position indicator
- Media details: dimensions, frame rate, codec, duration, bit depth, audio and
  camera metadata when available
- Stars, color labels and rejects with compact controls, thumbnail badges and filters
- Preview-first batch rename with naming patterns, numbering and find/replace
- Pinned folders, recent files, and mounted volumes
- Drag the divider beside the sidebar to resize it; width is remembered, with
  a 280-pixel minimum and a 300-pixel default
- Compact, icon-led right-click menu with grouped media submenus
- Right-click creation of folders and text files
- New Text File immediately creates `untitled.txt`, then `untitled (1).txt`, etc.,
  without a naming prompt; use Rename or F2 whenever you want to name it
- Background right-click works in blank areas and empty folders
- Mouse context menus anchor at the click; keyboard menus anchor at the selected file
- Rename, Cut/Copy/Paste, Copy Location, Properties, and confirmed Trash/Delete
- Consistent, theme-aware dialogs with file summaries, labeled fields and inline
  validation; readable Properties cards with permissions and combined file sizes
- GTK-shared bookmarks, hidden files, configurable list details, and sorting
- Non-destructive image resizing: Small (1080 px), Medium (2160 px), Large (3160 px)
- Image conversion to JPEG, PNG, WebP, and AVIF
- Video conversion to MP4, WebM, MOV, and GIF
- SMB and NFS NAS mounting with native credential prompts
- Search, breadcrumb navigation, typed paths, and history
- Connected chevron breadcrumbs; scroll the wheel over them to move along the path
- Eye toggle for hidden files and removable active-filter chips below the toolbar
- No full-path hover tooltips on file rows or breadcrumbs
- Open, multi-open, select-folder, Save, and SaveFiles flows
- Portal file filters and caller-supplied choices
- `Ctrl+F`, `Ctrl+L`, `Ctrl+H`, `Alt+Left`, `Alt+Right`, and `Escape`
- Automatic colors from the active Omarchy theme
- Cohesive sidebar, browser, previews and dialogs using the same Omarchy palette
- Space-bar Quick Look: animated expansion from the selected file and return
- Camera RAW photos in Quick Look, including CR2/CR3, ARW, NEF, RAF, RW2,
  DNG, ORF, PEF and X3F when supported by the installed RAW reader
- Image, UTF-8 text and first-page PDF previews; arrow keys browse adjacent files
- NAS dialog automatically discovers advertised SMB/NFS servers and GVfs
  network locations; select an SMB server to browse its shares, then Connect

All media operations create a new, uniquely named file beside the original.
Image work uses ImageMagick; video work uses FFmpeg. NAS connections use the
installed GVfs SMB/NFS backends and appear in the Devices section after mount.
NAS connection is sidebar-only, not a context-menu action.

Press `Space` on a selected file to preview it, and `Space` again or `Escape`
to close. The preview restores file focus and respects GTK's reduced-motion
setting. Images initially fit without cropping: scroll up/down over the image
to zoom in/out (up to 8× the fitted size), drag to pan, and double-click to fit
again. Each newly opened image resets to fit; zoom uses the bounded preview
texture, not a full-resolution image editor. Loading displays a spinner.
Camera RAW photos use these same controls through the `raw-preview` command
from the workstation's camera RAW setup. The desktop MIME database identifies
RAW files, including types Python's default image list omits. Decoding runs in
the background with at most two processes, stops when the preview is closed or
superseded, and keeps output in temporary storage. It never edits the original
or creates sidecar files. The helper and its decoder packages are optional
system dependencies and are not installed by `install.sh`; without the helper,
Quick Look reports that RAW preview support is missing. Exact camera and
compression support depends on the installed reader. Reopen Gudfiles after updating.
Text is read-only and
limited to 128 KB, and PDFs show their first page with the total page count.
The selection preview strip and Space-bar preview stay within the existing
window layout; switching files or opening/closing previews does not resize it.
Video previews open at their decoded display aspect from the first visible frame.
A slow-loading video shows a small spinner until its dimensions are ready, rather
than opening a wide player and reshaping it afterward.
Video/audio playback uses GTK/GStreamer and needs the appropriate codecs
on Arch. Install the playback stack with:

```bash
omarchy pkg add gst-plugins-good gst-plugins-bad gst-plugins-ugly gst-libav
```

Missing codecs show an explanation instead of opening another app. These system
packages are not installed by `install.sh`. Restart the picker after installing
them. `PYTHONPATH=. python tests/ui_video_playback.py` verifies H.264/AAC MP4,
HEVC MP4, ProRes MOV, VP9/Opus WebM and AV1 MP4 playback, pause, seeking and
cleanup using generated test clips; it requires the codec stack to be installed.
The picker defaults to GTK's OpenGL renderer to avoid a Vulkan video-texture
crash observed on this desktop. An explicit `GSK_RENDERER` override is respected;
no desktop-wide renderer setting is changed.

Network search starts every time Connect to NAS opens; Refresh scans again.
Discovery uses Avahi DNS-SD and GVfs, plus mounted shares and GTK-saved network
bookmarks. It does not port-scan the subnet or connect to servers automatically.
Selecting a server explicitly browses shares and may prompt for credentials;
selecting a share fills the address for Connect. Non-advertising servers may
still require a typed address. No passwords are saved by the picker.
Mounted shares need GVfs's local filesystem bridge. The picker checks it when
opening a mounted device and starts the installed bridge if missing, without
reconnecting or changing NAS credentials. Unavailable folders show an error.

Rename and paste refuse filename collisions instead of overwriting existing
files. Trash and permanent deletion both require confirmation. Clipboard file
operations support local file URIs, including mounted shares exposed as paths.

Open **Transfers** from the header to choose **Queue** (one transfer at a time)
or **All** (up to three independent transfer batches together). The choice is
remembered. Related file operations stay in order; switching back to Queue lets
active transfers finish before starting more. Use `Ctrl+Shift+V` to stage a
clipboard batch without starting it, then **Start queue** or **Start all** when
ready. A mode change does not start staged batches or resume paused transfers.
Each transfer has its own pause/resume/cancel controls, and All includes
**Pause all**. Queues last for the current Gudfiles session; closing Gudfiles asks
before cancelling unfinished work. Moves are limited to the same filesystem;
verified copies can cross volumes when the destination supports safe publication.
Automatically opened transfer panels close when quick transfers finish. Once a
transfer reaches five minutes of running time, its panel stays open afterward.
Manually opened panels, pauses and errors stay visible. Tiny
copies that finish before the panel opens do not flash a completed window;
their history remains available from **Transfers**.
Display preferences persist in `~/.config/omarchy-file-picker/preferences.json`;
bookmarks use the shared GTK `~/.config/gtk-3.0/bookmarks` file.
Your last chosen grid, list, or column view is saved as soon as you select it
and restored when you open Gudfiles or an Open/Save dialog again.

Right-click a sidebar location for **Open**, **Open in New Window**, **Copy
Location**, and **Properties**. Local folders also offer **Show in Enclosing
Folder**. **Remove from Sidebar** hides a default location or removes a shared
bookmark without deleting its folder. Right-click the sidebar and choose
**Restore Default Locations** to bring hidden defaults back. Mounted devices
offer **Eject**, **Unmount**, or **Disconnect** when supported; unfinished
transfers and file operations must finish or be cancelled first. Right-click
keeps the current folder and file selection; `Shift+F10` opens the menu for a
focused sidebar item.

Keyboard actions include `F2` Rename, `Delete` Trash, `Shift+Delete` permanent
delete, `Ctrl+X/C/V` Cut/Copy/Paste, `Ctrl+Shift+C` Copy Location,
`Ctrl+Shift+N` New Folder, `F5` Refresh, `Alt+Enter` Properties, and
`Shift+F10` context menu. `Ctrl+A` selects all when the caller permits multiple
files. Text-entry editing retains its normal clipboard shortcuts.

In list view, **Up / Down** moves through file and folder selections, including
immediately after switching views. **Shift** extends a range and **Ctrl** moves
focus without changing the selection. The focused row stays visible; **Enter**
opens a focused folder. Arrows in search, filename fields and the sidebar keep
their usual behavior.

Standalone Open enables multi-selection by default: click replaces the selection,
Shift-click selects a continuous range in display order, and Ctrl-click adds or
removes individual files. Grid, list and column views support these gestures. Use
`--single` for a single-selection standalone picker. Portal dialogs honor the
calling application's single/multiple setting; Save stays a single destination.
Click and drag from blank folder background to draw a selection rectangle in
all three views. Shift-drag adds to the selection, Ctrl-drag toggles covered items,
and Escape cancels the drag. Dragging near the top/bottom edge scrolls the folder.

Drag files normally to **move them on the same disk** or **copy them to another
disk**. Drop onto a folder, sidebar location or tab. Hover over a tab to switch
to it while dragging. Dropping in the original folder does nothing.

Hold **Alt / Option** before dragging a file or selected group to copy it. Drop
on blank space to duplicate in that folder, or onto another folder/column to
copy there. This works in grid, list and column views. Copies use the remembered
Queue/All mode and its pause/resume controls; originals and the clipboard stay
intact. Existing names get `copy`, `copy 2`, and so on, preserving file extensions.
Ordinary file clicks and background selection keep their existing behavior.

Successful conversions show a compact theme-matched notification inside the
picker, not a modal popup. It disappears after eight seconds or when dismissed.

## Creative workflow

Move across a video thumbnail to skim it silently after a short hover delay;
move away to restore its poster. This also works on the selected thumbnail in
list view. Press Space for normal playback. Hover uses bounded background FFmpeg
extraction rather than starting an audio/video player for every tile.

The selection strip shows a compact media summary; its information button
opens a two-column details card. Only metadata actually available is shown.

Use the stars and color dot beneath the filename, or in Quick Look's header,
to mark selects. Press `1`–`5` to rate, `0` to clear stars, and `X` to toggle
rejected. These actions apply to selected files (the current file in Quick Look)
and do not delete or alter media. The toolbar star opens rating/color filters;
folders remain visible for navigation. When culling a filtered selection in
Quick Look, a file that stops matching advances to a remaining neighbor, or
closes the preview when no matching files remain.
Active search, file-type, rating, color and hidden-file settings are shown below
the toolbar. Click a chip to remove just that setting, or **Clear all** to reset
them. The row disappears when no filters are active. The eye button shows whether
hidden files are visible; `Ctrl+H` toggles the same state.

Annotations are local to this app in
`~/.local/share/omarchy-file-picker/ratings.sqlite3`, not embedded metadata or
XMP sidecars. They follow renames and cut/paste moves performed in the picker,
including descendants of renamed folders. External moves/renames are not tracked;
annotations are associated with paths, not a portable asset database.

Select multiple items and press `F2` or choose **Batch Rename…**. The dialog
previews Before/After names before enabling Rename. Patterns support `{name}`,
`{n}` and `{date}` (modification date), with sequence start/padding; Find & replace
changes the filename stem. Extensions are preserved. Duplicate/existing targets
are blocked, including rename swaps. Renames use Linux's no-overwrite operation;
unsupported filesystems fail safely. Stop/failure keeps completed renames and
reports what happened; the batch is not an all-or-nothing transaction.

See [stock-picker-comparison.md](stock-picker-comparison.md) for the stock GTK
action comparison and intentional differences.

## Try it

```bash
./bin/omarchy-file-picker --demo ~/Pictures
```

## Install

```bash
./install.sh
```

This installs entirely in `~/.local` and `~/.config`. It backs up an existing
Hyprland portal routing file, makes this picker the FileChooser backend, leaves
the GTK portal as fallback, and restarts the affected user services.

Revert with:

```bash
./uninstall.sh
```

## Action sounds

Action sounds use the optional `paplay` command already available on this desktop.
If it or audio output is unavailable, file operations continue silently. The four
short original WAVs ship inside the package; `python scripts/generate_sounds.py`
regenerates them. Effects have their own **Gudfiles Sound Effects** mixer identity
and half stream volume, separate from media previews and system volume.

## Naming and compatibility

The application is named **Gudfiles**. The existing `omarchy-file-picker` command,
`org.omarchy.FilePicker` desktop/application ID, portal service IDs and storage
paths remain stable, preserving existing shortcuts, portal routing, preferences
and ratings across the rename.
