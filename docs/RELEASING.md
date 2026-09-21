# Publishing and maintaining Gudfiles

## Prepared distribution

`omarchy_file_picker/__init__.py` owns the stable `major.minor.patch` version,
currently **0.1.2**. `omarchy_file_picker/release.json` owns the public release
repository used by launch checks, Help and the generated PKGBUILD. It targets
`themediastandard/Gudfiles-For-Omarchy`, the public source repository. Its existing
0.1.0 friend preview is a prerelease; no stable release or official AUR listing
has been published. Source pushes do not replace downloadable packages.

The downloadable Python application contains its runtime Python files.
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
6. Commit the reviewed source and tag it `v<version>` in the source repository.
   Keep that tag tied to the exact archive that was built. Do not put private
   source credentials in the app, PKGBUILD or release repository.

The GitHub packaging workflow validates tests and builds review artifacts. It
does not publish releases or update the AUR automatically.

## First publication (external actions require the owner's go-ahead)

Use the canonical repository above. Publication still requires the owner's
go-ahead; preparing artifacts or configuring the checker does not publish them.
Confirm `gudfiles` is available on the AUR before any AUR submission and use the
owner's authorized account; AUR Git requires that account's SSH key.

Create a **draft** GitHub release for `v<version>` tied to the reviewed source
commit. Attach the generated runtime archive, `gudfiles-<version>-1-any.pkg.tar.zst`
and `SHA256SUMS`, using `dist/<version>/RELEASE-NOTES.md` as its body. Include the
installation guide. Review and publish as a stable release; the update check
ignores prereleases and requires an uploaded, nonempty matching Arch package
before offering a newer version. Download the assets anonymously and verify
checksums before publishing the AUR recipe. Publish only PKGBUILD and `.SRCINFO`
to the AUR; source downloads must use the official immutable version URL.

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

Ordinary browser launches check anonymously in the background. Successful checks
are cached for 24 hours; failures retry on a launch after one hour. Open/Save,
folder pickers and temporary external reveals do not check automatically.
The notice appears at most once per version per day across windows/processes;
its close button dismisses that version persistently. Help → About & License
can always request a fresh check, including for a dismissed version. Automatic
checks stay silent on failure or when no eligible newer stable package exists.
The View download action opens the verified release page; downloading and
installation remain explicit user actions. Checks send the app version, no
filenames, settings or ratings. No in-app installer replaces running files.

Existing 0.1.0 preview users must install a newer package containing this feature
once to receive future launch notices. A source push cannot add it to their old
installation. Settings and file data remain in their existing paths. Explain any
future storage migration and rollback limits in release notes before shipping.

Reference: [Arch PKGBUILD manual](https://man.archlinux.org/man/PKGBUILD.5.en.html)
and [GitHub releases API](https://docs.github.com/en/rest/releases/releases).

## Friend previews

The existing `v0.1.0-preview.1` prerelease is publicly downloadable from the
canonical source repository. For future authorized previews, build and verify
the same allowlisted artifacts and use a distinct preview tag tied to the source
commit. Keep it marked prerelease, attach `docs/TESTING.md` separately, and never
replace published assets. The shipped preview reports 0.1.0 and predates launch
notices. Stable checks intentionally ignore previews; testers install each
supplied package with pacman. No AUR entry is required for direct installation.
