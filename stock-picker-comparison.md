# Stock picker comparison

Baseline: installed GTK 3.24.52 / xdg-desktop-portal-gtk 1.15.3. Inspected the
installed chooser resource and the upstream GTK 3 `file_list_build_popover`
implementation in [gtkfilechooserwidget.c](https://raw.githubusercontent.com/GNOME/gtk/gtk-3-24/gtk/gtkfilechooserwidget.c).

| Stock GTK action | Omarchy picker location |
| --- | --- |
| Visit File | Recent-file context menu |
| Open With File Manager | More (file) / Folder (background) |
| Copy Location | File menu / Folder submenu; Ctrl+Shift+C |
| Add to Bookmarks | More for a folder / background Folder submenu |
| Rename | File menu; F2 |
| Delete | More → Delete Permanently; Shift+Delete; confirmation |
| Move to Trash | File menu; Delete; confirmation |
| Show Hidden Files | View submenu; Ctrl+H |
| Show Size / Type Column / Time | View submenu |
| Sort Folders before Files | Sort By submenu |
| New Folder | Background menu; Ctrl+Shift+N |

Additional actions: New Text File, Cut/Copy/Paste, Properties, Refresh, Select
All (multi-select requests), Grid/List, Name/Modified/Size/Type sorting and
ascending/descending order, plus the existing media tools.

The stock GTK chooser restricts rename/delete/trash to save-oriented modes;
this picker deliberately exposes them during Open too, as requested. Permanent
deletion is behind More and an explicit confirmation. The background menu
works on both populated blank space and the empty-state surface. NAS connection
remains in the sidebar only.

This is chooser-action coverage, not a claim to replace every Nautilus feature.
Clipboard operations accept local file URIs; remote-only URIs require mounting
first. Cross-filesystem directory moves depend on Gio/backend support and report
failure rather than deleting a source as a fallback. Failed multi-item jobs can
leave already completed items in their destination, with an explicit error.
