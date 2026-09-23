#!/usr/bin/env python3
"""Check a downloaded AGIOS image before writing it to a USB stick.

    verify-iso.py agi-os-YYYY.MM.DD-x86_64.iso [--key agios-release-key.asc] [--fingerprint FPR]

Next to the ISO it expects SHA256SUMS, SHA256SUMS.sig and the ISO's own .sig
(all from the release page). The public key is imported into a temporary
keyring, never into yours, and a signature counts only when it was made by the
expected fingerprint: the one given with --fingerprint, else the one published
in docs/download.md (RELEASE_FINGERPRINT below). Then the ISO's sha256 is
compared with SHA256SUMS. Exit code 0 means both checks passed.
"""
import argparse
import hashlib
from pathlib import Path
import importlib.util
import re
import subprocess
import sys
import tempfile

# The release key's fingerprint, published together with docs/download.md.
# Empty until the project's signing key is created (see docs/download.md).
RELEASE_FINGERPRINT = ""
FINGERPRINT = re.compile(r"[0-9A-F]{40}")


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def verified_by(home, signature, data):
    """The primary fingerprint of a valid signature, or None."""
    result = subprocess.run(["gpg", "--homedir", home, "--batch", "--no-tty", "--status-fd", "1",
                             "--verify", str(signature), str(data)], capture_output=True, text=True)
    if result.returncode:
        return None
    return signer_fingerprint(result.stdout)


def signer_fingerprint(status):
    """Shared with sign-iso.py: a good, current signature only (not expired or revoked)."""
    spec = importlib.util.spec_from_file_location("sign_iso", Path(__file__).with_name("sign-iso.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.signer_fingerprint(status)


def verify(iso, key, fingerprint):
    """A list of human-readable failures; empty when the image is authentic and intact."""
    if not FINGERPRINT.fullmatch(fingerprint):
        return ["Не задан отпечаток ключа проекта (--fingerprint): сверить подпись не с чем"]
    directory = iso.parent
    sums, sums_sig, iso_sig = directory / "SHA256SUMS", directory / "SHA256SUMS.sig", iso.with_name(iso.name + ".sig")
    missing = [p.name for p in (iso, key, sums, sums_sig, iso_sig) if not p.is_file()]
    if missing:
        return ["Нет файлов: " + ", ".join(missing)]
    failures = []
    with tempfile.TemporaryDirectory(prefix="agios-verify-") as home:
        imported = subprocess.run(["gpg", "--homedir", home, "--batch", "--no-tty", "--import", str(key)],
                                  capture_output=True, text=True)
        if imported.returncode:
            return ["Не удалось прочитать открытый ключ " + key.name]
        for signature, data in ((sums_sig, sums), (iso_sig, iso)):
            signer = verified_by(home, signature, data)
            if signer != fingerprint:
                failures.append(f"Подпись {signature.name} не подтверждена ключом {fingerprint}"
                                + (f" (подписано {signer})" if signer else ""))
        subprocess.run(["gpgconf", "--homedir", home, "--kill", "all"], capture_output=True)
    expected = None
    for line in sums.read_text().splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == iso.name:
            expected = parts[0].lower()
    if expected is None:
        failures.append(f"В SHA256SUMS нет строки для {iso.name}")
    elif sha256(iso) != expected:
        failures.append("Контрольная сумма ISO не совпадает: файл повреждён или подменён. Скачайте заново.")
    return failures


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("iso", type=Path)
    parser.add_argument("--key", type=Path, help="public key file (default: agios-release-key.asc next to the ISO)")
    parser.add_argument("--fingerprint", default=RELEASE_FINGERPRINT)
    args = parser.parse_args(argv)
    key = args.key or args.iso.with_name("agios-release-key.asc")
    failures = verify(args.iso, key, args.fingerprint.replace(" ", "").upper())
    for failure in failures:
        print("ОШИБКА: " + failure, file=sys.stderr)
    if failures:
        print("Не записывайте этот образ на носитель.", file=sys.stderr)
        return 1
    print(f"OK: {args.iso.name} подписан ключом проекта {args.fingerprint} и не изменён.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
