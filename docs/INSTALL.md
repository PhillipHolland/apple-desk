# Installation

Use an existing checkout or clone the repository with access granted by its maintainer. Do not publish a private checkout as part of installation.

Requirements: macOS 14+, Python 3.9+, and Xcode Command Line Tools (Swift 6.0+). `xcode-select --install` opens Apple's installer if the tools are absent.

```sh
cd /path/to/apple-desk
./scripts/install.sh
```

The installer builds `native/dist/apple-desk-calendar` and links all 13 commands into both `~/bin` and `~/.local/bin`. Put one of those directories on your shell PATH. It refuses to overwrite an unrelated executable or link. A different link directory can be selected with `./scripts/install.sh --bin-dir /your/bin`; repeat the option for multiple directories.

To install an already built helper without rebuilding its signature, use `./scripts/install.sh --skip-build`. Keep the checkout in a stable location: links point into it. Development signing is local and ad hoc; rebuilding or moving the helper can require renewed macOS permission approval.

```sh
apple-desk capabilities
apple-desk doctor
apple-desk mail --help
apple-desk calendar --help
```

Installation, version discovery, and offline dry runs do not require Mail or Calendar access. `doctor` checks permission status without requesting it. Run permission requests explicitly as described in [ONBOARD.md](ONBOARD.md). Do not repeatedly launch setup or kill apps to try to force a grant.

`./scripts/onboard.sh` remains a convenience wrapper for build/install followed by passive onboarding. It no longer automatically collects personal data or builds indexes. Run a deliberate `apple-desk desk reindex --only calendar` (or another supported surface) when wanted.

For testing, use a temporary `APPLE_DESK_STATE_DIR` so fixture drafts and journals cannot mix with real operations. The installed state directory is private to the current Mac user. Do not share it with other users or store it in this checkout.
