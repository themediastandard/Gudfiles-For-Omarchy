"""The in-app guide. Add a Feature here whenever a user-facing capability ships.

Keep descriptions actionable and shortcuts aligned with their actual handlers.
The guide builds navigation, search, sections and counts from this catalog.
"""
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class Category:
    key: str
    title: str
    icon: str
    description: str


@dataclass(frozen=True)
class Feature:
    category: str
    title: str
    description: str
    shortcut: str = ''
    keywords: str = ''
    requires: str = ''


CATEGORIES = (
    Category('browse', 'Browse & find', 'folder-open-symbolic',
             'Find your way around, then make the view your own.'),
    Category('preview', 'Preview media', 'view-reveal-symbolic',
             'Take a closer look without leaving your folder.'),
    Category('organize', 'Organize & label', 'starred-symbolic',
             'Name, select and mark the files that matter.'),
    Category('transfers', 'Copy & transfer', 'folder-download-symbolic',
             'Copy and move files with progress you can follow.'),
    Category('create', 'Create & convert', 'document-new-symbolic',
             'Make something new. Media tools keep the original.'),
    Category('locations', 'Locations & NAS', 'network-server-symbolic',
             'Keep favorite folders and connected drives close.'),
    Category('picker', 'Open & save', 'document-save-symbolic',
             'The same familiar browser when another app needs a file.'),
)

FEATURES = (
    Feature('browse', 'Show in Files from another app',
            'Use Show in Files or Show in Folder in another app to open the containing folder with the requested items selected and scrolled into view. Hidden targets are shown too.',
            keywords='chromium downloads reveal external selection'),
    Feature('browse', 'Folder tabs',
            'Use + or Ctrl + T to open a tab. Each tab keeps its folder, history, view, filters, selection and scroll. Ctrl + W closes it; Ctrl + Shift + T reopens it. Drag tabs to reorder them. Tabs share the strip width and respect reduced-motion settings.',
            'Ctrl + T / W', 'finder tabs close reopen'),
    Feature('browse', 'Switch tabs and open folders',
            'Ctrl + Tab and Ctrl + Shift + Tab switch tabs. Alt + 1–8 selects a tab; Alt + 9 selects the last. Middle-click a folder or sidebar location to open a background tab, or use Open in New Tab in its menu.',
            'Ctrl + Tab', 'middle click new tab'),
    Feature('browse', 'Three ways to browse',
            'Use the toolbar to switch between thumbnail grid, compact list and side-by-side columns. Your last view is remembered.',
            keywords='layout finder theme'),
    Feature('browse', 'Move through files',
            'Up / Down moves between visible rows in every view; Left / Right moves across grid tiles. In lists and columns, Up / Down selects the previous or next item and keeps it visible. Shift extends a range; Ctrl moves focus without changing selection. Enter opens the focused folder.',
            '↑ / ↓', 'keyboard arrows navigation'),
    Feature('browse', 'Follow folders in columns',
            'Up / Down selects items within the current column. Select a folder to open the next column; Left and Right move between columns. Each column scrolls independently.',
            '← / →'),
    Feature('browse', 'Search this folder or whole computer',
            'Click the magnifying glass or press Ctrl + F. This folder filters names here; Whole computer searches accessible folders and mounted drives recursively. Results show their locations. The eye toggle controls hidden files. Each tab remembers its scope. Enter shows results; Escape closes search. Remove its chip to clear it.', 'Ctrl + F', 'find filename scope search'),
    Feature('browse', 'Computer search limits',
            'Whole computer searches for up to 15 seconds or 500 matches. It skips virtual system folders and does not follow folder symlinks. A status message reports limits or unreadable folders; refine your search when results are incomplete.',
            keywords='search timeout partial recursive permissions'),
    Feature('browse', 'Jump to a path',
            'Enter a folder path directly. Escape returns to the breadcrumb trail.', 'Ctrl + L', 'location address'),
    Feature('browse', 'Breadcrumbs & history',
            'The trail includes the folder you just opened, including single-click navigation in columns. Hover a breadcrumb for its full folder name, click one to visit it, or scroll over the trail to reveal ancestors. Use the Up arrow or Alt + Up for the displayed folder’s parent. Up is unavailable at the filesystem root and in Recent. Alt + Left / Right goes back / forward.',
            'Alt + ← / → / ↑'),
    Feature('browse', 'Show hidden files',
            'Use the eye button to reveal or hide dotfiles and hidden folders.', 'Ctrl + H'),
    Feature('browse', 'Clear active filters',
            'Search, file type, stars, colors and hidden-file settings appear as chips below the toolbar. Remove one chip or choose Clear all.'),
    Feature('browse', 'Sort & list details',
            'Click a list heading to sort; click again to reverse. Right-click headings to choose details, including Rating, Color Label and Rejected. Drag headings to rearrange them; Name stays first. Your layout and sort order are remembered. The top-bar Sort menu also controls ordering and Folders first.',
            keywords='columns header metadata customize reorder positions stars rating color rejected fps resolution created modified'),
    Feature('browse', 'Reorder list columns',
            'Drag a heading left or right, or focus it and press Alt + Left / Right. The shaded column shows its new position. Name stays first; Escape cancels a drag. Your column choices and positions are remembered.',
            keywords='header move arrange metadata'),
    Feature('browse', 'Resize and fit list columns',
            'Drag a heading’s right edge to resize its column. Double-click the edge to fit its contents. Narrow names truncate instead of widening the window. Column widths are remembered; new windows keep a compact default for Name.',
            keywords='width filename size fit double click'),
    Feature('browse', 'Thumbnail size',
            'In grid view, use the slider at the bottom left to make thumbnails smaller or larger. The size is remembered and updates without reopening the folder.',
            keywords='zoom tiles grid slider bottom bar'),
    Feature('browse', 'Folder sizes',
            'Folder sizes include nested and hidden files and load in the background in every view. Linked contents are excluded. An ellipsis means calculating; ≥ means incomplete; Unavailable means unreadable. Size sorting places incomplete results last. F5 recalculates. These are content sizes, not disk space used.',
            keywords='recursive directory bytes totals calculate', requires='folder_sizes'),
    Feature('browse', 'Refresh the folder',
            'Visible folders update automatically when files change elsewhere, preserving selection and scroll position. F5 reloads manually, including network locations that cannot report changes.', 'F5'),
    Feature('browse', 'Action sounds',
            'Quiet sounds confirm completed drops, copies, Trash, permanent deletion and media conversions. Right-click → View → Sound Effects turns them on or off. The choice is remembered across windows. Cancelled or failed actions stay silent.',
            keywords='audio mute volume feedback'),
    Feature('browse', 'An app that follows your theme',
            'Gudfiles reads your active Omarchy colors at launch, including its previews, menus and dialogs.'),

    Feature('preview', 'Quick Look',
            'Select a file and press Space for an in-window preview. Space or Escape closes it. Down / Right previews the next file; Up / Left previews the previous file in the current sort order. Text fields and playback sliders keep their own arrow controls.',
            'Space', 'preview quicklook'),
    Feature('preview', 'Zoom in on images',
            'Scroll over an image preview to zoom up to 8× its fitted size. Drag to pan and double-click to fit again. Each image starts fitted.',
            keywords='photo picture magnify'),
    Feature('preview', 'Camera RAW photos',
            'Camera RAW photos, including Nikon NEF, show thumbnails in the grid and selection strip. Thumbnails load in the background as you scroll. Press Space for zoom, pan and fit controls. Previewing keeps the original unchanged; supported cameras depend on the installed RAW reader.',
            'Space', 'raw camera cr2 cr3 arw nef nrw raf rw2 dng orf pef x3f'),
    Feature('preview', 'Video & audio playback',
            'Open Quick Look to play, pause and seek with the media controls. Playback needs the appropriate installed codecs; closing the preview stops it.',
            keywords='movie music sound'),
    Feature('preview', 'Skim video thumbnails',
            'Pause the pointer over a video thumbnail, then move across it to skim silently. Move away to restore the poster. Also works in the selection strip.',
            keywords='hover scrub scrubbing'),
    Feature('preview', 'Text & PDF previews',
            'Quick Look shows read-only UTF-8 text up to 128 KB and the first page of a PDF with its page count. PDF support requires Poppler.'),
    Feature('preview', 'Media details at a glance',
            'Select a photo, camera RAW file or video to show the compact media preview below the file area. Its information button opens available dimensions, frame rate, codec, duration and camera details. With mixed selections, the preview shows the first selected media file.',
            keywords='fps exif bit depth dimensions'),
    Feature('browse', 'Selection summaries',
            'The slim bottom bar shows the selected file/folder count and combined size. Folder totals update in the background. Selecting a folder or document keeps the large media preview hidden, leaving more room for browsing.',
            keywords='multiple metadata bytes'),

    Feature('organize', 'Select a little or a lot',
            'Shift-click selects a range; Ctrl-click toggles individual items. Ctrl + A selects all when the window allows multiple selection.',
            'Ctrl + A'),
    Feature('organize', 'Draw a selection',
            'Drag from blank folder space to select a rectangle in any view. Shift adds, Ctrl toggles, and Escape cancels. Drag near an edge to scroll.'),
    Feature('organize', 'Rename a file or folder',
            'Select one item and press F2. The filename stem is selected for editing; existing names are never overwritten.', 'F2'),
    Feature('organize', 'Batch rename',
            'Select multiple items and press F2 for a Before / After preview. Use {name}, {n} and {date} patterns, sequence padding or Find & replace. Extensions stay intact; {date} uses the modification date.',
            'F2', 'number numbering replace sequence'),
    Feature('organize', 'Undo renames and moves',
            'Ctrl + Z or right-click → Undo reverses a rename, batch rename or same-drive move from this window. Changed items and existing destination names stop Undo safely. History lasts for this window; cross-drive moves and permanent deletion cannot be undone here. Text fields keep their own Undo.',
            'Ctrl + Z', 'undo recover rename move'),
    Feature('organize', 'Stars & rejects',
            'Press 1–5 to rate selected files, 0 to clear stars, or X to toggle rejected. The same controls work in Quick Look. Rejecting marks a file without deleting it.',
            '1–5 / 0 / X', 'rating cull culling'),
    Feature('organize', 'Color labels & filters',
            'Use the color dot in the media preview or Quick Look to label files. The toolbar star filters by rating, rejected status or color; folders stay navigable.',
            keywords='tag mark'),
    Feature('organize', 'Your labels stay local',
            'Ratings and colors belong to Gudfiles, not embedded media metadata. They follow renames and cut/paste moves made here; external moves are not tracked.',
            keywords='annotations xmp'),
    Feature('organize', 'Properties & location',
            'Alt + Enter shows file details, readable permissions and selection totals. Ctrl + Shift + C copies the selected location, or the current folder when nothing is selected.',
            'Alt + Enter', 'Ctrl Shift C copy path'),
    Feature('organize', 'Trash or delete',
            'Press Delete, Super + Backspace or Super + Delete to move selected items to Trash after confirmation. If a location such as a NAS does not support Trash, Gudfiles explains this and offers a separate permanent-delete confirmation for those items. Cancel keeps them in place. Shift + Delete permanently deletes after confirmation. All destructive dialogs start on Cancel.',
            'Del / Super+Backspace'),
    Feature('organize', 'Restore from Trash',
            'Open Trash in the sidebar and browse it with the normal Grid, List or Column controls. Select items and use Restore to put them back. Existing files are never replaced; failures stay in Trash. Back, Forward, tabs and name/location search work here too. F5 refreshes the list.',
            keywords='recover deleted restore trash bin'),
    Feature('organize', 'Empty Trash',
            'In Trash, choose Empty Trash… from the action bar or right-click menu. Confirm to permanently remove the listed items, including items hidden by search. This cannot be undone. Items added after confirmation are kept; failures are reported and remain in Trash.',
            keywords='bin delete permanently clear all', requires='empty_trash'),
    Feature('organize', 'Right-click actions',
            'Right-click a file, blank folder space or a sidebar location for its actions. Hover over a row with an arrow to open its submenu. Shift + F10 opens the menu for the focused item.',
            'Shift + F10', 'context menu'),

    Feature('transfers', 'Copy, cut & paste',
            'Copy with Ctrl + C or cut with Ctrl + X, visit the destination, then paste with Ctrl + V. Transfers shows progress. Filename collisions are not overwritten.',
            'Ctrl + C / X / V', 'clipboard move'),
    Feature('transfers', 'Copy to or Move to a folder',
            'Select one or more files or folders, right-click and choose Copy to… or Move to…. Browse to a destination in Gudfiles, then choose Copy here or Move here. Cancelling the folder picker leaves everything in place. Progress appears in Transfers and your clipboard stays unchanged. Copies use an available name; moves stop on name collisions. Cross-drive moves verify the copied data before removing unchanged originals.',
            keywords='destination choose folder multiple selection copy move'),
    Feature('transfers', 'Drag files between folders',
            'Drag files or a selection onto a folder, sidebar location or tab. Files move on the same disk and copy to a different disk. Hover over a tab to switch to it while dragging. A drop in the original folder does nothing.',
            keywords='drag drop move disk volume'),
    Feature('transfers', 'Alt-drag to copy',
            'Hold Alt / Option before dragging a file or selection. Drop on blank space to duplicate, or on a folder to copy there. Existing names get copy / copy 2 suffixes.',
            'Alt + drag', 'duplicate option'),
    Feature('transfers', 'Stage work for later',
            'Ctrl + Shift + V adds clipboard files to the transfer queue without starting. Open Transfers from the header, then start when ready.',
            'Ctrl + Shift + V'),
    Feature('transfers', 'Queue or All',
            'In Transfers, Queue runs one batch at a time. All runs up to three independent batches together. Start queue / Start all starts waiting work; switching modes does not start staged batches.',
            keywords='parallel concurrent'),
    Feature('transfers', 'Pause, resume & recover',
            'Use a transfer’s Pause, Resume, Retry or Cancel controls. Resume checks retained bytes against the source. If the source or partial copy changed, use Restart unfinished. Completed files remain.',
            keywords='failure verification'),
    Feature('transfers', 'Recover transfers after closing',
            'Closing the Transfers panel keeps work running. Choose Save queue & close to stop Gudfiles with unfinished transfers saved. After relaunch or a crash, recovered transfers wait for Resume; saved bytes and source identities are checked before continuing. A saved transfer belongs to only one open window at a time.',
            keywords='restart recovery crash quit journal'),
    Feature('transfers', 'Move between drives',
            'Cut/paste and Move to support different drives. Gudfiles copies, verifies and publishes each item before removing its unchanged original. If cleanup stops, Resume continues safely. Keep remaining originals stops cleanup and preserves the copy plus any remaining original data, using an available name when necessary. Dragging across drives still copies by default.',
            keywords='nas disk cross volume keep originals'),
    Feature('transfers', 'A panel that gets out of the way',
            'Automatically opened panels hide after quick transfers finish. Manually opened panels, pauses, errors and transfers with five minutes of running time stay visible. Reopen Transfers for history.'),

    Feature('create', 'New folder',
            'Create a folder in the current location from the right-click menu or keyboard.', 'Ctrl + Shift + N'),
    Feature('create', 'New text file',
            'Right-click blank space and choose New Text File. An empty untitled.txt is created and selected immediately, with a numbered name if needed. Press F2 to rename it.'),
    Feature('create', 'Extract a ZIP',
            'In the file browser, double-click a ZIP to extract its contents into a new folder beside it. The folder uses the ZIP’s name, with a number if that name already exists. The ZIP stays intact. Extraction runs in the background; keep Gudfiles open until it finishes. Password-protected archives, links and special files are not supported. In Open/Save dialogs, ZIPs remain ordinary selectable files.',
            keywords='archive unzip decompress'),
    Feature('create', 'Resize images',
            'Right-click an image and choose a resize preset: Small (1080 px), Medium (2160 px) or Large (3160 px). A new file is saved beside the original.',
            keywords='scale photo picture'),
    Feature('create', 'Convert images',
            'Use the image conversion submenu for JPEG, PNG, WebP or AVIF. ImageMagick creates a uniquely named output beside the original.',
            keywords='format export'),
    Feature('create', 'Convert videos',
            'Use the video conversion submenu for MP4, WebM, MOV or GIF. FFmpeg creates a new output; the original stays intact. Completion appears as a dismissible in-window notice.',
            keywords='movie format export'),

    Feature('locations', 'Favorite folders',
            'Right-click a folder and choose Add to Favorites. Favorites stay in the sidebar across windows and launches. Remove from Favorites removes only the shortcut, never the folder.'),
    Feature('locations', 'Recent folders and Recent Files',
            'Recents keeps the five latest folders you used, newest first, including folders used for previews, file operations and choosing files. Right-click → Remove from Recents forgets an entry without deleting it; using that folder again can bring it back. Recent Files is a separate view of recent files.',
            keywords='history favorites sidebar last used'),
    Feature('locations', 'Shared bookmarks',
            'Shared GTK bookmarks appear under Places. Favorites belong to Gudfiles and stay in their own sidebar section.',
            keywords='places GTK bookmark'),
    Feature('locations', 'Make the sidebar yours',
            'Drag its divider to resize; the width is remembered. Right-click a location to Remove from Sidebar without deleting it. Restore Default Locations brings hidden defaults back.'),
    Feature('locations', 'Open another Gudfiles window',
            'Right-click a sidebar folder and choose Open in New Window. The same menu offers Copy Location, Properties and Show in Enclosing Folder for local folders.'),
    Feature('locations', 'Connect to NAS',
            'Choose Connect to NAS in the sidebar for SMB or NFS. Pick a discovered server, browse SMB shares or enter an address, then Connect. Credentials are requested when needed.',
            keywords='network server mount share samba'),
    Feature('locations', 'Discover & refresh servers',
            'The NAS dialog looks for advertised servers, saved locations and mounted shares. Refresh scans again. A server that does not advertise may need a typed address.',
            keywords='network smb nfs'),
    Feature('locations', 'Eject or disconnect',
            'Right-click a mounted device for its supported Eject, Unmount or Disconnect action. Finish or cancel this session’s active file operations and transfers first.',
            keywords='drive remove volume'),

    Feature('picker', 'Gudfiles as your everyday browser',
            'When launched directly, Gudfiles opens files in their default apps and stays open. Escape clears the search or selection. There is no Open / Save footer in this mode.'),
    Feature('picker', 'Choose files for another app',
            'An app’s Open dialog includes its file-type filters, choices and Open / Cancel buttons. Single or multiple selection follows what that app allows.'),
    Feature('picker', 'Choose a folder',
            'Folder dialogs show files for context, but those files are disabled. Select a folder and use the footer action to return it to the requesting app.'),
    Feature('picker', 'Save a file',
            'Choose a destination and enter a name in the Save dialog. Replacing an existing file requires confirmation. Save requests can also supply several filenames.'),
    Feature('picker', 'Update notices',
            'Ordinary browser launches check for newer stable packages in the background, at most daily. View download opens the release page; installing is up to you. Dismiss hides that version. Open/Save dialogs and temporary reveals stay quiet. Help → About & License can check again, even for a dismissed version.',
            keywords='automatic launch updater release notification download', requires='launch_updates'),
    Feature('picker', 'Help, always close by',
            'Click Help in the header or press F1 to open this guide. Search by feature or shortcut. In this window, Ctrl + F focuses search and Escape closes the guide.',
            'F1', 'keyboard shortcuts guide manual'),
    Feature('picker', 'About Gudfiles & its license',
            'Choose About & License in Help for the installed version, Check for Updates, The Media Standard credit, website and full license. Gudfiles is free for personal and commercial use; modification and redistribution require written permission.',
            keywords='free use copyright linux creatives themediastandard.com version updates release'),
)


def available_features(capabilities):
    return [feature for feature in FEATURES
            if not feature.requires or feature.requires in capabilities]


def matching_features(query='', category=None, *, features=None):
    # Treat punctuation in shortcuts as spacing: Ctrl+Shift+V and Ctrl Shift V
    # find the same entry. All words must match; case and whitespace do not matter.
    def normalize(value):
        return re.findall(r'\w+|[←→↑↓]', value.casefold())
    words = normalize(query)
    titles = {group.key: group.title for group in CATEGORIES}
    def matches(feature):
        tokens = normalize(' '.join((feature.title, feature.description,
                                    feature.shortcut, feature.keywords, titles[feature.category])))
        searchable = ' '.join(tokens)
        # A shortcut's single letter must be a whole token: "V" must not
        # match the v in "view" and turn Ctrl+Shift+V into unrelated results.
        return all(word in tokens if len(word) == 1 else word in searchable for word in words)
    return [feature for feature in (FEATURES if features is None else features)
            if (category is None or feature.category == category)
            and matches(feature)]
