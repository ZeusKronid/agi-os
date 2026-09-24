# Download and verify AGIOS

AGIOS is published as a Live ISO on the
[GitHub releases page](https://github.com/ZeusKronid/agi-os/releases). Every
release is built by CI from a tagged commit (`docs/ci.md`) and carries:

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

## Release signing key

> **Not created yet.** Until the project owner creates the key and publishes its
> fingerprint here, releases are not signed and cannot be verified by signature;
> the CI refuses to publish a release without a key unless
> `AGIOS_ALLOW_UNSIGNED_RELEASE=1` is set on purpose.

Fingerprint: *to be published here, in the README and in every release note.*

A fingerprint is only trustworthy when it comes from a place other than the
download itself: check that the fingerprint in the release notes, this page in
the Git repository and (when published) the key server agree.

## Verify on Linux

With the repository at hand:

```sh
python3 scripts/release/verify-iso.py agi-os-2026.10.01-x86_64.iso --fingerprint <FINGERPRINT>
```

It imports `agios-release-key.asc` into a temporary keyring (yours is not
touched), accepts only signatures made by that fingerprint and compares the
ISO's SHA-256 with `SHA256SUMS`. Without the repository, the same with gpg:

```sh
gpg --import agios-release-key.asc
gpg --fingerprint <FINGERPRINT>                 # must match the published fingerprint
gpg --verify SHA256SUMS.sig SHA256SUMS          # "Good signature from AGIOS release key"
gpg --verify agi-os-*.iso.sig agi-os-*.iso
sha256sum --check --ignore-missing SHA256SUMS    # agi-os-…iso: OK
```

"Good signature" from a key with a different fingerprint means nothing: compare
the fingerprint gpg prints with the published one. The warning *This key is not
certified with a trusted signature* only says that you have not signed the key
yourself; the fingerprint check is what matters.

## Verify on Windows

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

## Verify on macOS

Install GnuPG (`brew install gnupg` or GPG Suite), then run the gpg commands from
the Linux section; for the checksum use `shasum -a 256 -c SHA256SUMS --ignore-missing`.

## For maintainers: signing a release

CI signs in the `release` job of `.github/workflows/iso.yml`:
`scripts/release/sign-iso.py out --export-key` writes `SHA256SUMS`, the two
`.sig` files and `agios-release-key.asc`, verifies them, and the same
`verify-iso.py` users run checks the result before publishing. The job needs:

| Setting | Kind | Content |
| --- | --- | --- |
| `AGIOS_SIGNING_KEY` | secret | ASCII-armored secret key (preferably only the signing subkey, `gpg --export-secret-subkeys --armor FPR!`) |
| `AGIOS_SIGNING_PASSPHRASE` | secret | its passphrase, if it has one (passed to gpg over a pipe, loopback pinentry) |
| `AGIOS_SIGNING_FINGERPRINT` | variable | full 40-hex fingerprint of the primary key |
| `AGIOS_ALLOW_UNSIGNED_RELEASE` | variable | `1` only to publish without signatures on purpose |

Signing by hand (key in your own keyring, e.g. on a hardware token):

```sh
python3 scripts/release/sign-iso.py out --key <FINGERPRINT> --export-key
```

The script never creates or picks a key.

### What the project owner must provide

Nothing is signed until these exist (the build scripts never create a key):

1. A decision on how the key is kept (options below).
2. The key: an OpenPGP key whose primary fingerprint is published; for CI, its
   ASCII-armored **signing subkey** (`gpg --armor --export-secret-subkeys FPR`)
   as the secret `AGIOS_SIGNING_KEY`, plus `AGIOS_SIGNING_PASSPHRASE` if it has one.
3. The repository variable `AGIOS_SIGNING_FINGERPRINT` (40 hex, primary key).
4. The fingerprint in this page (section *Release signing key*), in
   `RELEASE_FINGERPRINT` of `scripts/release/verify-iso.py`, in the README and on
   keys.openpgp.org.
5. A revocation certificate stored offline.

### Decisions left to the project owner

The key is a trust anchor for everyone who installs AGIOS, so how it is kept is
not decided by the build scripts. Options, from simplest to safest:

1. **One key, stored as a CI secret.** Easy; anyone with admin access to the
   repository (or a compromised workflow) can sign.
2. **Offline primary key + signing subkey in CI (recommended).** The primary key
   (certification only) stays offline or on a hardware token; CI holds only the
   subkey with an expiry (for example one year). A leaked subkey is revoked and
   replaced without changing the published fingerprint.
3. **Signing only by a maintainer on a hardware token** (YubiKey / Nitrokey). CI
   builds and uploads unsigned artifacts; the maintainer downloads, verifies the
   checksum against `build-info.json`, signs locally and uploads the signatures.

For any option: algorithm Ed25519 (or RSA 4096 for very old verifiers), an
expiry date, a revocation certificate stored offline, and the fingerprint
published in the README, on this page, in every release note and on
keys.openpgp.org.
