# Publishing and maintaining Gudfiles

## Prepared distribution

`omarchy_file_picker/__init__.py` owns the stable `major.minor.patch` version,
currently **0.1.0**. `omarchy_file_picker/release.json` owns the public release
repository used by Help and the generated PKGBUILD. It currently targets
`themediastandard/gudfiles-releases`, a proposed separate public distribution
repository. Confirm that choice before publication. The development repository
`themediastandard/gudfiles` remains private.

The downloadable Python application necessarily contains its runtime Python
files. A separate release repository keeps development history, tests and
internal project documents private; it does not conceal the shipped Python.
The Gudfiles Free Use License reserves modification and redistribution rights.
Do not replace it with an open-source license during packaging.

## Prepare each release

1. Safely synchronize the development checkout, then implement and verify the
   change. Update the version in `__init__.py` and add `releases/<version>.md`.
   Use a new version for changed app contents; never replace an already published
   archive. A packaging-only fix increments `pkgrel` and its release tooling.
2. Run `python -m unittest discover -q`, then the native GTK checks in PROJECT.md
   appropriate to the changes. At minimum check Help, explorer/Open/Save and a
   transfer before each public release. Run interactive GTK tests on a desktop
   using disposable data, not in the headless packaging job.
3. Build with `python scripts/prepare-release.py --build-package`. This creates
   `dist/<version>/` containing a deterministic runtime archive, an Arch package,
   SHA256SUMS, pinned PKGBUILD, `.SRCINFO` and release notes. It uses only
   allowlisted runtime files and public installation docs; Git, PROJECT.md,
   development tests and user data are excluded. No services are restarted.
4. Run `python scripts/verify-release.py dist/<version>`. Install and exercise
   the package on a disposable current Omarchy machine before the first public
   release, including FileChooser enable/disable across a login. This machine's
   local package build and GTK smoke checks do not substitute for that test.
5. Review the exact artifacts and public notes. For the first release, remove
   the preparation-only Availability paragraph in `docs/INSTALL.md` only after
   confirming the distribution destination and publish sequence; rebuild so the
   shipped guide accurately describes availability. Keep manual download
   instructions until AUR submission is live.
6. Commit the reviewed source and tag it `v<version>` in the private repository.
   Keep that tag tied to the exact archive that was built. Do not put private
   source credentials in the app, PKGBUILD or release repository.

The GitHub packaging workflow validates tests and builds review artifacts. It
does not publish releases or update the AUR automatically.

## First publication (external actions require the owner's go-ahead)

Confirm the destination, then create the public release repository under The
Media Standard with a minimal public README linking to the website, downloads,
installation instructions and license. Do not mirror the private repository or
its history. Confirm `gudfiles` is available on the AUR and use the owner's
authorized AUR account; AUR Git requires that account's SSH key.

Create a **draft** GitHub release for `v0.1.0` in that destination, attach exactly:

- `gudfiles-0.1.0.tar.gz`
- `gudfiles-0.1.0-1-any.pkg.tar.zst`
- `SHA256SUMS`

Use `dist/0.1.0/RELEASE-NOTES.md` for its body. Review the draft and publish it as
a stable release (the update check deliberately ignores prereleases). Download
all three assets anonymously and verify checksums before publishing the AUR
recipe. Publish only PKGBUILD and `.SRCINFO` to the AUR; source downloads must
come from The Media Standard's official immutable version URL.

Run a fresh `yay -S gudfiles` and confirm `gudfiles --version`. Confirm the
anonymous GitHub latest-release endpoint returns the expected tag. The first
time through, also test updating from the previous package with user settings
and ratings in place. Publish the official download link on themediastandard.com
only after verifying it. No website editing is part of the local build script.

## Future updates

Build and verify the next version, publish its GitHub release, then update the
official AUR PKGBUILD's version and SHA-256 using the generated recipe and
`.SRCINFO`. Omarchy's updater runs `yay -Sua` for installed AUR packages, so
users receive the newer package on their next normal update after AUR publication.
Direct package downloads also participate once the official matching AUR entry
is live. A GitHub release by itself does not update an AUR recipe.

No in-app installer replaces files while the app runs. Help checks GitHub only
when asked, times out on network failure, and distinguishes unpublished,
up-to-date, newer-public and ahead-of-public versions. Data remains in the
existing user paths. Explain any future storage migration and rollback limits
in release notes before shipping it.

Reference: [Arch PKGBUILD manual](https://man.archlinux.org/man/PKGBUILD.5.en.html)
and [GitHub releases API](https://docs.github.com/en/rest/releases/releases).
