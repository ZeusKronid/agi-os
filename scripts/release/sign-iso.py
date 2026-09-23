#!/usr/bin/env python3
"""Checksums and OpenPGP signatures for an AGIOS release.

    sign-iso.py --key FINGERPRINT DIR

DIR holds one agi-os-*.iso (and optionally build-info.json). The script writes

    SHA256SUMS            sha256 of every release file, `sha256sum --check` format
    SHA256SUMS.sig        detached signature of SHA256SUMS
    agi-os-*.iso.sig      detached signature of the ISO itself
    agios-release-key.asc the public key, for the release page (with --export-key)

and verifies each signature before it exits. The key is never created or chosen
here: it is named by its full 40-hex fingerprint (--key or AGIOS_SIGNING_FINGERPRINT)
and must already be in the keyring (GNUPGHOME). A passphrase, when the key has one,
is read from AGIOS_SIGNING_PASSPHRASE and passed to gpg over a pipe, never on the
command line. In CI the private key comes from a secret; see docs/download.md.
"""
import argparse
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys

FINGERPRINT = re.compile(r"[0-9A-F]{40}")
EXTRA = ("build-info.json",)


class SigningError(RuntimeError):
    pass


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def release_files(directory):
    isos = sorted(directory.glob("agi-os-*.iso"))
    if len(isos) != 1:
        raise SigningError(f"В {directory} должен быть ровно один agi-os-*.iso, найдено: {len(isos)}")
    return isos + [directory / name for name in EXTRA if (directory / name).is_file()]


def gpg(args, passphrase=None, secret=False):
    command = ["gpg", "--batch", "--yes", "--no-tty", "--status-fd", "2"]
    if secret:
        # Loopback: the passphrase (possibly empty) comes from this process; gpg-agent
        # never opens a graphical pinentry, and a missing passphrase fails instead of hanging.
        command += ["--pinentry-mode", "loopback", "--passphrase-fd", "0"]
    result = subprocess.run(command + args, input=((passphrase or "") + "\n") if secret else "",
                            capture_output=True, text=True)
    if result.returncode:
        raise SigningError("gpg: " + result.stderr.strip()[-1500:])
    return result


REJECT = {"EXPSIG", "EXPKEYSIG", "REVKEYSIG", "BADSIG", "ERRSIG"}


def signer_fingerprint(status):
    """The primary-key fingerprint of a good, current signature from gpg's status lines,
    or None. VALIDSIG alone is not enough: gpg also reports it for an expired or revoked key."""
    words = [line.split() for line in status.splitlines() if line.startswith("[GNUPG:] ")]
    kinds = {w[1] for w in words if len(w) > 1}
    if "GOODSIG" not in kinds or kinds & REJECT:
        return None
    return next((w[-1] for w in words if len(w) >= 3 and w[1] == "VALIDSIG"), None)


def check_key(fingerprint):
    result = gpg(["--with-colons", "--list-secret-keys", fingerprint])
    lines = result.stdout.splitlines()
    if not any(line.startswith("fpr:") and fingerprint in line for line in lines):
        raise SigningError("Секретного ключа " + fingerprint + " нет в брелоке GNUPGHOME")


def sign(directory, fingerprint, export_key=False, passphrase=None):
    if not FINGERPRINT.fullmatch(fingerprint):
        raise SigningError("Укажите полный отпечаток ключа: 40 шестнадцатеричных символов в верхнем регистре")
    files = release_files(directory)
    check_key(fingerprint)
    sums = directory / "SHA256SUMS"
    sums.write_text("".join(f"{sha256(path)}  {path.name}\n" for path in files))
    outputs = []
    for target in (sums, files[0]):
        signature = target.with_name(target.name + ".sig")
        # No "!": gpg picks the signing subkey, so the primary key may stay offline.
        gpg(["--local-user", fingerprint, "--detach-sign", "--output", str(signature), str(target)],
            passphrase, secret=True)
        status = gpg(["--verify", str(signature), str(target)]).stderr
        if signer_fingerprint(status) != fingerprint:
            raise SigningError(f"Подпись {signature.name} не проверилась ключом {fingerprint}")
        outputs.append(signature)
    if export_key:
        key = directory / "agios-release-key.asc"
        key.write_text(gpg(["--armor", "--export", fingerprint]).stdout)
        outputs.append(key)
    return [sums, *outputs]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--key", default=os.environ.get("AGIOS_SIGNING_FINGERPRINT", ""),
                        help="full fingerprint of the signing key (default: $AGIOS_SIGNING_FINGERPRINT)")
    parser.add_argument("--export-key", action="store_true", help="also write agios-release-key.asc")
    args = parser.parse_args(argv)
    try:
        written = sign(args.directory, args.key.replace(" ", "").upper(), args.export_key,
                       os.environ.get("AGIOS_SIGNING_PASSPHRASE") or None)
    except SigningError as exc:
        print(exc, file=sys.stderr)
        return 1
    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
