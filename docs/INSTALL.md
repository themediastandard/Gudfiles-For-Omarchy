# Install Gudfiles on Omarchy

Designed and built by [The Media Standard](https://themediastandard.com) for
creatives using Linux. Free for personal and commercial use. Modification and
redistribution require written permission; read the included LICENSE.

## Availability

Release preparation is in progress. Public GitHub releases and the AUR entry
must be published before the online commands below work. The intended AUR
package name is `gudfiles`; no AUR listing is claimed by this guide.

## Friend preview builds

For a directly shared package or a private GitHub prerelease, follow
the separately supplied `TESTING.md` guide. These builds install locally with pacman
and receive updates by downloading another package; no AUR entry is required.

## Install and update

Once the official AUR entry is available, install with:

```bash
yay -S gudfiles
```

Review the recipe and its download origin. Omarchy's normal Update action
checks installed AUR packages; new Gudfiles versions arrive when The Media
Standard publishes a release and updates the AUR recipe. Updates are installed
when you run the updater, not silently while the app is open. Finish transfers
and close Gudfiles before updating, then reopen it.

An official downloaded `gudfiles-<version>-1-any.pkg.tar.zst` can also be installed
with `sudo pacman -U ./gudfiles-<version>-1-any.pkg.tar.zst` (replace the filename).
That local install joins AUR updates only after a matching official `gudfiles`
entry exists. Until then, install each newer official package the same way.
Use the release's SHA256SUMS to check downloads with `sha256sum -c SHA256SUMS`.

Launch **Gudfiles** from the application menu, or run `gudfiles`. The old
`omarchy-file-picker` command remains compatible. **Help → About & License**
shows the installed version and a manual **Check for Updates** button. Checking
contacts GitHub only when requested; it sends no filenames, settings or ratings.
It reports public releases and links to notes; it does not install anything.

## Optional system Open/Save dialogs

The package installs the app without changing your portal preferences. To use
Gudfiles for other applications' Open/Save dialogs on Omarchy/Hyprland:

```bash
gudfiles --enable-portal
```

Run this as your normal user. It preserves your previous FileChooser preference
and other portal choices. Finish your work, then log out and back in. GTK stays
the fallback. Restore your prior choice before uninstalling with:

```bash
gudfiles --disable-portal
```

Log out and back in afterward. Existing apps may cache portal choices.

## Migrating an older user-local installation

Finish transfers, close Gudfiles and other applications with open file dialogs.
Use the **updated** development checkout's `./uninstall.sh` first. It backs up
the legacy app files, removes its user-local launchers and services, restores
legacy portal routing and keeps ratings, settings and GTK bookmarks. The old
uninstaller from before release preparation must not be used: it removed ratings.
Then install the package and optionally enable its portal as above. Do not run
the user installer on top of the package: user-local files can shadow updates.

## Dependencies and removal

Pacman installs the required Python, PyGObject, Cairo, GTK4, icons and portal
dependencies. `gudfiles --doctor` checks basic runtime support and optional tools.
For a fuller creative workflow, install:

```bash
omarchy pkg add ffmpeg ffmpegthumbnailer imagemagick poppler-glib gst-plugins-good gst-plugins-bad gst-plugins-ugly gst-libav gvfs gvfs-smb gvfs-nfs avahi libpulse
```

Camera RAW support is optional and needs an external `raw-preview` helper.
Codec and camera-format availability depends on the installed system tools.
This release targets Omarchy; other Linux distributions have not been validated.

To remove the package, disable its portal first if enabled, then run
`sudo pacman -R gudfiles`. Application files live under `/usr/lib/gudfiles`.
Removal and upgrades leave these user-owned paths intact:

- Preferences: `~/.config/omarchy-file-picker/preferences.json`
- Ratings: `~/.local/share/omarchy-file-picker/ratings.sqlite3`
- Shared bookmarks: `~/.config/gtk-3.0/bookmarks`

An older official package can be installed with `pacman -U` for rollback.
Keep a backup of user settings and ratings before any future release that
announces a data-format migration; downgrades across such changes may be limited.
