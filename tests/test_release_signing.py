"""Release signing round trip with a throwaway key in a temporary GNUPGHOME."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scripts/release" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sign_iso, verify_iso = load("sign-iso"), load("verify-iso")


@unittest.skipUnless(shutil.which("gpg") and shutil.which("gpgconf"), "gpg is not installed")
class SigningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agios-sign-test-")
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.home = base / "gnupg"
        self.home.mkdir(mode=0o700)
        # No passphrase caching: each signature must get the passphrase from the environment.
        (self.home / "gpg-agent.conf").write_text("default-cache-ttl 0\nmax-cache-ttl 0\n")
        self.addCleanup(subprocess.run, ["gpgconf", "--homedir", str(self.home), "--kill", "all"], capture_output=True)
        patcher = patch.dict(os.environ, {"GNUPGHOME": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.fingerprint = self.new_key("AGIOS test release key <release-test@invalid>")
        self.release = base / "out"
        self.release.mkdir()
        self.iso = self.release / "agi-os-2026.09.23-x86_64.iso"
        self.iso.write_bytes(os.urandom(300_000))
        (self.release / "build-info.json").write_text('{"iso": "agi-os-2026.09.23-x86_64.iso"}\n')

    def new_key(self, uid):
        subprocess.run(["gpg", "--batch", "--passphrase", "", "--quick-gen-key", uid, "ed25519", "sign", "1d"],
                       check=True, capture_output=True)
        listing = subprocess.run(["gpg", "--with-colons", "--list-keys", uid], check=True, capture_output=True, text=True).stdout
        return next(line.split(":")[9] for line in listing.splitlines() if line.startswith("fpr:"))

    def test_sign_then_verify_round_trip(self):
        written = sign_iso.sign(self.release, self.fingerprint, export_key=True)
        self.assertEqual({p.name for p in written}, {"SHA256SUMS", "SHA256SUMS.sig", self.iso.name + ".sig", "agios-release-key.asc"})
        sums = (self.release / "SHA256SUMS").read_text()
        self.assertIn(self.iso.name, sums)
        self.assertIn("build-info.json", sums)
        # The sums file is in sha256sum --check format.
        subprocess.run(["sha256sum", "--check", "--quiet", "SHA256SUMS"], cwd=self.release, check=True)
        key = self.release / "agios-release-key.asc"
        self.assertEqual(verify_iso.verify(self.iso, key, self.fingerprint), [])

    def test_tampered_iso_fails(self):
        sign_iso.sign(self.release, self.fingerprint, export_key=True)
        with open(self.iso, "r+b") as stream:
            stream.seek(1000)
            stream.write(b"\x00tampered")
        failures = verify_iso.verify(self.iso, self.release / "agios-release-key.asc", self.fingerprint)
        self.assertTrue(any("ISO" in f for f in failures), failures)

    def test_signature_by_another_key_fails(self):
        sign_iso.sign(self.release, self.fingerprint, export_key=True)
        other = self.new_key("Somebody else <other@invalid>")
        # An attacker re-signs the files and ships their own key under the expected name.
        for target in (self.release / "SHA256SUMS", self.iso):
            subprocess.run(["gpg", "--batch", "--yes", "--local-user", other, "--detach-sign", "--output",
                            str(target) + ".sig", str(target)], check=True, capture_output=True)
        forged = subprocess.run(["gpg", "--armor", "--export", other], check=True, capture_output=True, text=True).stdout
        (self.release / "agios-release-key.asc").write_text(forged)
        failures = verify_iso.verify(self.iso, self.release / "agios-release-key.asc", self.fingerprint)
        self.assertEqual(len(failures), 2, failures)

    def test_refuses_without_a_full_fingerprint_or_the_secret_key(self):
        with self.assertRaises(sign_iso.SigningError):
            sign_iso.sign(self.release, self.fingerprint[-16:])
        with self.assertRaises(sign_iso.SigningError):
            sign_iso.sign(self.release, "0" * 40)
        self.assertFalse((self.release / "SHA256SUMS.sig").exists())
        self.assertIn("отпечаток", verify_iso.verify(self.iso, self.release / "x.asc", "")[0])

    def test_refuses_ambiguous_release_directory(self):
        (self.release / "agi-os-2026.09.24-x86_64.iso").write_bytes(b"x")
        with self.assertRaises(sign_iso.SigningError):
            sign_iso.sign(self.release, self.fingerprint)

    def test_offline_primary_key_with_signing_subkey(self):
        """The recommended setup: CI holds only the signing subkey; the primary key is offline."""
        uid = "AGIOS offline primary <offline@invalid>"
        subprocess.run(["gpg", "--batch", "--passphrase", "", "--quick-gen-key", uid, "ed25519", "cert", "1d"],
                       check=True, capture_output=True)
        listing = subprocess.run(["gpg", "--with-colons", "--list-keys", uid], check=True, capture_output=True, text=True).stdout
        primary = next(line.split(":")[9] for line in listing.splitlines() if line.startswith("fpr:"))
        subprocess.run(["gpg", "--batch", "--passphrase", "", "--quick-add-key", primary, "ed25519", "sign", "1d"],
                       check=True, capture_output=True)
        subkeys = subprocess.run(["gpg", "--batch", "--armor", "--export-secret-subkeys", primary],
                                 check=True, capture_output=True, text=True).stdout
        ci = Path(self.temp.name) / "ci-gnupg"
        ci.mkdir(mode=0o700)
        self.addCleanup(subprocess.run, ["gpgconf", "--homedir", str(ci), "--kill", "all"], capture_output=True)
        with patch.dict(os.environ, {"GNUPGHOME": str(ci)}):
            subprocess.run(["gpg", "--batch", "--import"], input=subkeys, check=True, capture_output=True, text=True)
            secret = subprocess.run(["gpg", "--with-colons", "--list-secret-keys"], capture_output=True, text=True).stdout
            sec = next(line for line in secret.splitlines() if line.startswith("sec:"))
            self.assertEqual(sec.split(":")[14], "#")  # the primary key's secret is really absent (stub)
            sign_iso.sign(self.release, primary, export_key=True)
        self.assertEqual(verify_iso.verify(self.iso, self.release / "agios-release-key.asc", primary), [])

    def test_expired_or_revoked_signatures_are_rejected(self):
        good = "[GNUPG:] NEWSIG\n[GNUPG:] GOODSIG 1 x\n[GNUPG:] VALIDSIG a b c d e f g h i FPR\n"
        self.assertEqual(sign_iso.signer_fingerprint(good), "FPR")
        for bad in ("EXPKEYSIG", "REVKEYSIG", "EXPSIG"):
            status = good.replace("GOODSIG", bad)
            self.assertIsNone(sign_iso.signer_fingerprint(status))
            self.assertIsNone(verify_iso.signer_fingerprint(status))

    def test_passphrase_protected_key_via_environment(self):
        uid = "AGIOS protected <protected@invalid>"
        subprocess.run(["gpg", "--batch", "--pinentry-mode", "loopback", "--passphrase", "release-test-pass",
                        "--quick-gen-key", uid, "ed25519", "sign", "1d"], check=True, capture_output=True)
        listing = subprocess.run(["gpg", "--with-colons", "--list-keys", uid], check=True, capture_output=True, text=True).stdout
        fingerprint = next(line.split(":")[9] for line in listing.splitlines() if line.startswith("fpr:"))
        with patch.dict(os.environ, {"AGIOS_SIGNING_PASSPHRASE": "release-test-pass"}):
            self.assertEqual(sign_iso.main([str(self.release), "--key", fingerprint]), 0)
        self.assertEqual(sign_iso.main([str(self.release), "--key", fingerprint]), 1)


if __name__ == "__main__":
    unittest.main()
