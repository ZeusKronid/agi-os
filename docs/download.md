# Download and verify AGIOS

Download a versioned, signed image from the
[GitHub releases page](https://github.com/ZeusKronid/agi-os/releases). Each
release is built by CI from a `v*` tag (`docs/ci.md`) and carries:

| File | What it is |
| --- | --- |
| `agi-os-YYYY.MM.DD-x86_64.iso` | the Live image; write it to a USB stick or boot it in a VM |
| `agi-os-YYYY.MM.DD-x86_64.iso.sig` | OpenPGP signature of the ISO |
| `SHA256SUMS` | SHA-256 of the ISO and `build-info.json` |
| `SHA256SUMS.sig` | OpenPGP signature of `SHA256SUMS` |
| `agios-release-key.asc` | the project's public signing key |
| `agi-os-…iso.sha256`, `build-info.json` | checksum alone; build inputs (commit, Arch snapshot, container) |
| `CHANGELOG` | in the release notes: what changed since the previous tag |

Versions are named after the release tag (`v2026.10.0` …) and the ISO after the
commit date. Older releases stay on the page; `build-info.json` tells how to
rebuild any of them byte for byte (`docs/ci.md`).

For the latest development build from `main`, open a successful run in the
[Live ISO workflow](https://github.com/ZeusKronid/agi-os/actions/workflows/iso.yml?query=branch%3Amain)
and select **agi-os-iso** under **Artifacts**. Sign in to GitHub to download it.
The ZIP contains the ISO, its `.sha256` file, and `build-info.json`; CI
artifacts expire after seven days. After extracting the ZIP, check the image
with `sha256sum --check agi-os-*.iso.sha256`. This checksum detects a damaged
download but is not a signature.

## Release signing key

Fingerprint: **`BA1D BAF6 09C7 6719 47DD A5E4 D1DF F581 C1F8 77D3`**.
The [public key](agios-release-key.asc) is committed to this repository. The
primary key certifies a separate CI signing subkey. Compare the fingerprint
shown by your verification tool with this value from a trusted copy of the
repository; the key bundled with a download alone does not establish trust.

## Verify a signed release on Linux

With the repository at hand:

```sh
python3 scripts/release/verify-iso.py agi-os-*.iso
```

It imports `agios-release-key.asc` into a temporary keyring (yours is not
touched), accepts only signatures made by that fingerprint and compares the
ISO's SHA-256 with `SHA256SUMS`. Without the repository, the same with gpg:

```sh
gpg --import agios-release-key.asc
gpg --fingerprint BA1DBAF609C7671947DDA5E4D1DFF581C1F877D3
gpg --verify SHA256SUMS.sig SHA256SUMS          # "Good signature from AGIOS release key"
gpg --verify agi-os-*.iso.sig agi-os-*.iso
sha256sum --check --ignore-missing SHA256SUMS    # agi-os-…iso: OK
```

"Good signature" from a key with a different fingerprint means nothing: compare
the fingerprint gpg prints with the published one. The warning *This key is not
certified with a trusted signature* only says that you have not signed the key
yourself; the fingerprint check is what matters.

## Verify a signed release on Windows

1. Install [Gpg4win](https://www.gpg4win.org/) and open Kleopatra.
2. *File → Import* `agios-release-key.asc`; in the key's details compare the
   fingerprint with the published one.
3. *File → Decrypt/Verify* `agi-os-…iso.sig` (the ISO must be in the same folder):
   Kleopatra reports a valid signature by the AGIOS release key. A note that the
   key is *not certified* only means you have not certified it yourself; the
   fingerprint comparison in step 2 is what matters. An *expired* or *revoked*
   key is a failure: do not use the image.
4. Optionally the checksum in PowerShell:
   `Get-FileHash .\agi-os-…-x86_64.iso -Algorithm SHA256` and compare with the line
   in `SHA256SUMS`.

## Verify a signed release on macOS

Install GnuPG (`brew install gnupg` or GPG Suite), then run the gpg commands from
the Linux section; for the checksum use `shasum -a 256 -c SHA256SUMS --ignore-missing`.

## For maintainers: signing a release

CI signs in the `release` job of `.github/workflows/iso.yml`:
`scripts/release/sign-iso.py out --export-key` writes `SHA256SUMS`, the two
`.sig` files and `agios-release-key.asc`, verifies them, and the same
`verify-iso.py` users run checks the result before publishing. The job needs:

| Setting | Kind | Content |
| --- | --- | --- |
| `AGIOS_SIGNING_KEY` | secret | ASCII-armored signing subkey (`gpg --armor --export-secret-subkeys FPR`), without the primary secret key |
| `AGIOS_SIGNING_PASSPHRASE` | secret | its passphrase, if it has one (passed to gpg over a pipe, loopback pinentry) |
| `AGIOS_SIGNING_FINGERPRINT` | variable | full 40-hex fingerprint of the primary key |
| `AGIOS_ALLOW_UNSIGNED_RELEASE` | variable | `1` only to publish without signatures on purpose |

Signing by hand (key in your own keyring, e.g. on a hardware token):

```sh
python3 scripts/release/sign-iso.py out --key BA1DBAF609C7671947DDA5E4D1DFF581C1F877D3 --export-key
```

The script never creates or picks a key.

### Key custody and rotation

The Ed25519 primary key is certification-only and kept out of CI. GitHub
Actions holds only a one-year signing subkey; the primary key, signing subkey,
passphrase, and revocation certificate are backed up in the project owner's
secret manager. Renew the signing subkey before it expires and update the
`AGIOS_SIGNING_KEY` secret. If the signing key is compromised, revoke it and
publish the revocation and replacement fingerprint before another release.
