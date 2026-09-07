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
    Feature('browse', 'Folder tabs',
            'Use + or Ctrl + T for a new Gudfiles tab. Each tab keeps its folder history, view, filters, selection and scroll. Ctrl + W closes a tab; Ctrl + Shift + T reopens it. Drag tabs to reorder them.',
            'Ctrl + T / W', 'finder tabs close reopen'),
    Feature('browse', 'Switch tabs and open folders',
            'Ctrl + Tab and Ctrl + Shift + Tab switch tabs. Alt + 1–8 selects a tab; Alt + 9 selects the last. Middle-click a folder or sidebar location to open a background tab, or use Open in New Tab in its menu.',
            'Ctrl + Tab', 'middle click new tab'),
    Feature('browse', 'Three ways to browse',
            'Use the toolbar to switch between thumbnail grid, compact list and side-by-side columns. Your last view is remembered.',
            keywords='layout finder theme'),
    Feature('browse', 'Move through a list',
            'In list view, Up / Down moves the selection through files and folders and keeps the current row visible. Shift extends a range; Ctrl moves focus without changing the selection. Enter opens the focused folder.',
            '↑ / ↓', 'keyboard arrows navigation'),
    Feature('browse', 'Follow folders in columns',
            'Select a folder to open the next column. Left and Right move between columns; each column scrolls independently.',
            '← / →'),
    Feature('browse', 'Search this folder',
            'Type in the toolbar search to filter names in the current folder. Search does not scan subfolders.', 'Ctrl + F', 'find filename'),
    Feature('browse', 'Jump to a path',
            'Enter a folder path directly. Escape returns to the breadcrumb trail.', 'Ctrl + L', 'location address'),
    Feature('browse', 'Breadcrumbs & history',
            'Click a breadcrumb to visit an ancestor. Scroll over the trail to reveal longer paths. Alt + Left / Right goes back / forward; Alt + Up opens the parent.',
            'Alt + ← / → / ↑'),
    Feature('browse', 'Show hidden files',
            'Use the eye button to reveal or hide dotfiles and hidden folders.', 'Ctrl + H'),
    Feature('browse', 'Clear active filters',
            'Search, file type, stars, colors and hidden-file settings appear as chips below the toolbar. Remove one chip or choose Clear all.'),
    Feature('browse', 'Sort & list details',
            'Right-click and use Sort By for name, modified date, size or type, either direction, and folders first. The View menu toggles list detail columns.'),
    Feature('browse', 'Refresh the folder',
            'Reload the current folder to see changes made elsewhere.', 'F5'),
    Feature('browse', 'Action sounds',
            'Quiet sounds confirm completed drops, copies, Trash, permanent deletion and media conversions. Right-click → View → Sound Effects turns them on or off. The choice is remembered across windows. Cancelled or failed actions stay silent.',
            keywords='audio mute volume feedback'),
    Feature('browse', 'An app that follows your theme',
            'Gudfiles reads your active Omarchy colors at launch, including its previews, menus and dialogs.'),

    Feature('preview', 'Quick Look',
            'Select a file and press Space for an in-window preview. Videos open at their correct display aspect; a slow load shows a spinner until dimensions are ready. Space or Escape closes it; Left / Right browses neighboring files.',
            'Space', 'preview quicklook'),
    Feature('preview', 'Zoom in on images',
            'Scroll over an image preview to zoom up to 8× its fitted size. Drag to pan and double-click to fit again. Each image starts fitted.',
            keywords='photo picture magnify'),
    Feature('preview', 'Camera RAW photos',
            'Press Space on a camera RAW photo to preview it with the same zoom, pan and fit controls. Previewing keeps the original unchanged; supported cameras depend on the installed RAW reader.',
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
            'The selection strip shows a summary. Its information button reveals available resolution, frame rate, codec, duration, audio and camera metadata.',
            keywords='fps exif bit depth dimensions'),
    Feature('preview', 'Selection summaries',
            'Select several items to see their file/folder count and combined file size. Folder contents are excluded from the total.',
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
    Feature('organize', 'Stars & rejects',
            'Press 1–5 to rate selected files, 0 to clear stars, or X to toggle rejected. The same controls work in Quick Look. Rejecting does not delete a file.',
            '1–5 / 0 / X', 'rating cull culling'),
    Feature('organize', 'Color labels & filters',
            'Use the color dot in the selection strip or Quick Look to label files. The toolbar star filters by rating, rejected status or color; folders stay navigable.',
            keywords='tag mark'),
    Feature('organize', 'Your labels stay local',
            'Ratings and colors belong to Gudfiles, not embedded media metadata. They follow renames and cut/paste moves made here; external moves are not tracked.',
            keywords='annotations xmp'),
    Feature('organize', 'Properties & location',
            'Alt + Enter shows file details, readable permissions and selection totals. Ctrl + Shift + C copies the selected location, or the current folder when nothing is selected.',
            'Alt + Enter', 'Ctrl Shift C copy path'),
    Feature('organize', 'Trash or delete',
            'Delete moves selected items to Trash after confirmation. Shift + Delete permanently deletes after confirmation. Both dialogs start on Cancel.',
            'Delete / Shift + Delete'),
    Feature('organize', 'Right-click actions',
            'Right-click a file, blank folder space or a sidebar location for its actions. Shift + F10 opens the menu for the focused item.',
            'Shift + F10', 'context menu'),

    Feature('transfers', 'Copy, cut & paste',
            'Copy with Ctrl + C or cut with Ctrl + X, visit the destination, then paste with Ctrl + V. Transfers shows progress. Filename collisions are not overwritten.',
            'Ctrl + C / X / V', 'clipboard move'),
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
    Feature('transfers', 'Transfers belong to this session',
            'Closing the Transfers panel keeps work running. Closing Gudfiles asks about unfinished work. The queue is not restored after relaunch. Dragging across disks copies automatically; cut/paste moves require the same filesystem.',
            keywords='nas disk cross volume quit'),
    Feature('transfers', 'A panel that gets out of the way',
            'Automatically opened panels hide after quick transfers finish. Manually opened panels, pauses, errors and transfers with five minutes of running time stay visible. Reopen Transfers for history.'),

    Feature('create', 'New folder',
            'Create a folder in the current location from the right-click menu or keyboard.', 'Ctrl + Shift + N'),
    Feature('create', 'New text file',
            'Right-click blank space and choose New Text File. An empty untitled.txt is created and selected immediately, with a numbered name if needed. Press F2 to rename it.'),
    Feature('create', 'Resize images',
            'Right-click an image and choose a resize preset: Small (1080 px), Medium (2160 px) or Large (3160 px). A new file is saved beside the original.',
            keywords='scale photo picture'),
    Feature('create', 'Convert images',
            'Use the image conversion submenu for JPEG, PNG, WebP or AVIF. ImageMagick creates a uniquely named output beside the original.',
            keywords='format export'),
    Feature('create', 'Convert videos',
            'Use the video conversion submenu for MP4, WebM, MOV or GIF. FFmpeg creates a new output; the original stays intact. Completion appears as a dismissible in-window notice.',
            keywords='movie format export'),

    Feature('locations', 'Favorites & recent files',
            'Use the sidebar for common folders, Recent and mounted devices. Right-click a folder and choose More → Add to Bookmarks to pin it. Bookmarks are shared with GTK apps.'),
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
            'A folder request shows directories and returns the selected destination. The dialog’s footer tells you what the requesting app needs.'),
    Feature('picker', 'Save a file',
            'Choose a destination and enter a name in the Save dialog. Replacing an existing file requires confirmation. Save requests can also supply several filenames.'),
    Feature('picker', 'Help, always close by',
            'Click Help in the header or press F1 to open this guide. Search by feature or shortcut. In this window, Ctrl + F focuses search and Escape closes the guide.',
            'F1', 'keyboard shortcuts guide manual'),
)


def matching_features(query='', category=None):
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
    return [feature for feature in FEATURES
            if (category is None or feature.category == category)
            and matches(feature)]
