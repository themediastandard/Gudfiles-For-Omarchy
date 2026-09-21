# Try Gudfiles on Omarchy

This preview is for **Omarchy on Arch Linux**. It has not been validated on a
fresh machine yet; this is an early tester build. It is not a Windows or macOS
installer. The 0.1.0 preview is publicly downloadable; stable releases and AUR updates are not available yet.

## Install

1. Download all assets from the [public preview](https://github.com/themediastandard/Gudfiles-For-Omarchy/releases/tag/v0.1.0-preview.1),
   or get the files directly from the developer. Keep the package,
   runtime archive and SHA256SUMS together in one folder.
2. Open a terminal in that folder and run:

   ```bash
   sha256sum -c SHA256SUMS
   sudo pacman -U ./gudfiles-0.1.0-1-any.pkg.tar.zst
   gudfiles --doctor
   gudfiles
   ```

   Both checksum lines should say `OK`. Pacman installs required dependencies.
   If you already use a development copy, follow the migration instructions in
   INSTALL.md before installing; user-local launchers can shadow the package.

For video previews, thumbnails, conversions and network shares, optionally run:

```bash
sudo pacman -S --needed ffmpeg ffmpegthumbnailer imagemagick poppler-glib gst-plugins-good gst-plugins-bad gst-plugins-ugly gst-libav gvfs gvfs-smb gvfs-nfs avahi libpulse
```

Camera RAW previews need a separate `raw-preview` helper and are not included.
Use the app launcher entry **Gudfiles**, or run `gudfiles` from a terminal.

## Things to try

Start with a folder of disposable copies. Browse in grid, list and columns;
open tabs; preview an image or video with Space; copy files to another folder;
rename a file and undo it with Ctrl+Z. Try a folder chooser and confirm files
are visible but only folders can be accepted.

Using Gudfiles as other apps' Open/Save dialog is optional. Run
`gudfiles --enable-portal` as your normal user, finish your work, then log out
and back in. Restore your previous dialog with `gudfiles --disable-portal`,
then log out and back in again.

## Feedback and updates

Send the developer your `gudfiles --version` and `gudfiles --doctor` output,
what you tried, what happened, and what you expected. Include a screenshot or
terminal error if useful; remove personal paths or filenames before sharing.

This 0.1.0 preview predates automatic launch notices and does not auto-update.
Install a newer supplied package once to gain launch-time stable-release notices.
Stable checks intentionally ignore prereleases. Finish transfers and close
Gudfiles before installing a newer package; publishing source alone cannot
update an existing installation.

## Remove

If you enabled the portal, first run `gudfiles --disable-portal`. Then run:

```bash
sudo pacman -R gudfiles
```

Log out and back in if you changed portal routing. Settings, ratings, bookmarks
and transfer recovery records stay in your user directories.

Free for personal and commercial use under the included Gudfiles Free Use
License. Modification and redistribution require the developer's permission.
