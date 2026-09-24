"""CMP-121: own Secure Boot keys, signed boot chain and enrollment in Setup Mode."""

import json
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "archiso/airootfs/usr/local/share/agi-os/installer"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(ROOT / "web"))
sys.path.insert(0, str(ROOT / "tests"))
from controller import DemoProvider
from domain import Configuration, ValidationError
from system import demo_inventory
import hardware
import verify
import worker
from test_installer import FakeRunner, specification

UNSIGNED = "Verifying file database and EFI images in /boot...\n✓ /boot/vmlinuz-linux is signed\n✗ /boot/EFI/Linux/x.efi is not signed\n"
SIGNED = "Verifying file database and EFI images in /boot...\n✓ /boot/vmlinuz-linux is signed\n✓ /boot/EFI/BOOT/BOOTX64.EFI is signed\n"


def pe_image(certificate_size, pe32_plus=True):
    """A minimal PE header with the certificate data directory (index 4) set."""
    data = bytearray(0x200)
    data[:2] = b"MZ"
    data[0x3C:0x40] = struct.pack("<I", 0x80)
    data[0x80:0x84] = b"PE\0\0"
    optional = 0x80 + 24
    data[optional:optional + 2] = struct.pack("<H", 0x20B if pe32_plus else 0x10B)
    directories = optional + (112 if pe32_plus else 96)
    data[directories + 32:directories + 40] = struct.pack("<II", 0x180 if certificate_size else 0, certificate_size)
    return bytes(data)


class HardwareTests(unittest.TestCase):
    def test_setup_mode_is_read_from_efivars(self):
        with tempfile.TemporaryDirectory() as tmp:
            efivars = Path(tmp) / "firmware/efi/efivars"
            efivars.mkdir(parents=True)
            (efivars / hardware.SETUP_MODE_VAR).write_bytes(b"\x06\x00\x00\x00\x01")
            (efivars / hardware.SECURE_BOOT_VAR).write_bytes(b"\x06\x00\x00\x00\x00")
            self.assertTrue(hardware.efi_flag(hardware.SETUP_MODE_VAR, Path(tmp)))
            self.assertFalse(hardware.efi_flag(hardware.SECURE_BOOT_VAR, Path(tmp)))
            self.assertIsNone(hardware.efi_flag("Missing-8be4df61-93ca-11d2-aa0d-00e098032b8c", Path(tmp)))

    def test_profile_bounds_setup_mode_and_describes_it(self):
        self.assertIsNone(hardware.profile({"setup_mode": "yes"})["setup_mode"])
        described = hardware.describe(hardware.profile({"secure_boot": False, "setup_mode": True}))
        self.assertTrue(any("Setup Mode" in line for line in described))


class WorkerSigningTests(unittest.TestCase):
    def install(self, secure_boot, verify_output=SIGNED):
        config = Configuration.parse(specification())
        snapshot = demo_inventory()
        disk = snapshot["disks"][0]
        request = {"configuration": config.as_dict(), "fingerprint": disk["fingerprint"],
                   "consent_digest": config.digest(), "password": "private-password", "secure_boot": secure_boot}

        class Runner(FakeRunner):
            def run(self, args, input_text=None, timeout=1800):
                if args[-1:] == ["verify"] and "sbctl" in args:
                    self.calls.append(args)
                    return verify_output
                if "-Qq" in args:
                    self.calls.append(args)
                    return "\n".join(worker.packages_for(config, snapshot["hardware"], secure_boot))
                return super().run(args, input_text, timeout)

        runner, events, record = Runner(), [], {}
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "target"
            # kbd is part of the base system; the worker checks the console files exist there (CMP-122).
            for name in (f"keymaps/i386/qwerty/{config.effective_keymap()}.map.gz",
                         f"consolefonts/{config.effective_console_font()}.psfu.gz"):
                (target / "usr/share/kbd" / name).parent.mkdir(parents=True, exist_ok=True)
                (target / "usr/share/kbd" / name).touch()
            preset = target / "etc/mkinitcpio.d/linux.preset"
            preset.parent.mkdir(parents=True, exist_ok=True)
            preset.write_text("ALL_kver='/boot/vmlinuz-linux'\nPRESETS=('default')\ndefault_image='/boot/initramfs-linux.img'\n")
            with patch.object(worker, "TARGET", target), patch.object(worker, "preflight", return_value=(config, snapshot, disk)), \
                 patch.object(worker, "inventory", return_value=snapshot), patch.object(worker.Catalog, "validate", side_effect=lambda p: p), \
                 patch.object(worker, "emit", side_effect=lambda kind, **data: events.append({"kind": kind, **data})), \
                 patch.object(worker.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)):
                try:
                    worker.install(request, runner)
                except ValidationError as exc:
                    events.append({"kind": "error", "text": str(exc)})
                path = target / "var/lib/agi-os/installation.json"
                if path.exists():
                    record = json.loads(path.read_text())
        return runner.calls, events, record

    def test_keys_are_created_before_the_kernel_is_signed_and_bootctl_takes_the_signed_copy(self):
        calls, events, record = self.install(True)
        self.assertEqual(events[-1]["kind"], "installed")
        joined = [" ".join(c) for c in calls]
        pacstrap = next(i for i, c in enumerate(joined) if c.startswith("pacstrap"))
        self.assertNotIn("sbctl", calls[pacstrap])  # its hooks must not run before keys exist
        keys = next(i for i, c in enumerate(joined) if c.endswith("sbctl create-keys"))
        signed_boot = next(i for i, c in enumerate(joined) if "--output " + worker.SBCTL_EFI + ".signed" in c)
        bootctl = next(i for i, c in enumerate(joined) if "bootctl" in c)
        kernel = next(i for i, c in enumerate(joined) if c.endswith("sbctl sign --save /boot/vmlinuz-linux"))
        mkinitcpio = next(i for i, c in enumerate(joined) if c.endswith("mkinitcpio -P"))
        self.assertLess(pacstrap, keys)
        self.assertLess(keys, mkinitcpio)
        self.assertLess(signed_boot, bootctl)
        self.assertLess(bootctl, kernel)
        self.assertEqual(record["secure_boot"], {"signed": True, "enrolled": False})

    def test_unsigned_file_fails_the_installation(self):
        _, events, _ = self.install(True, UNSIGNED)
        self.assertEqual(events[-1]["kind"], "error")
        self.assertIn("/boot/EFI/Linux/x.efi", events[-1]["text"])
        self.assertNotIn("installed", [e["kind"] for e in events])

    def test_without_secure_boot_nothing_is_signed(self):
        calls, events, record = self.install(False)
        self.assertEqual(events[-1]["kind"], "installed")
        self.assertFalse(any("sbctl" in c for c in calls))
        self.assertIsNone(record["secure_boot"])

    def test_secure_boot_needs_uefi_and_systemd_boot(self):
        grub = specification()
        grub["bootloader"] = "grub"
        for data, value in ((grub, True), (specification(), "yes"), (specification(), 1)):
            config = Configuration.parse(data)
            snapshot = demo_inventory()
            disk = snapshot["disks"][0]
            request = {"configuration": config.as_dict(), "fingerprint": disk["fingerprint"],
                       "consent_digest": config.digest(), "password": "private-password", "secure_boot": value}
            with self.subTest(bootloader=data["bootloader"], value=value), \
                 patch.object(worker, "live_environment", return_value=True), patch.object(worker.os, "geteuid", return_value=0), \
                 patch.object(worker, "inventory", return_value=snapshot), self.assertRaisesRegex(ValidationError, "Secure Boot"):
                worker.preflight(request)

    def test_sbctl_unsigned_parsing(self):
        self.assertEqual(worker.sbctl_unsigned(UNSIGNED), ["/boot/EFI/Linux/x.efi"])
        self.assertEqual(worker.sbctl_unsigned(SIGNED), [])
        shared = "✗ /efi/EFI/Microsoft/Boot/bootmgfw.efi is not signed\n✓ /efi/EFI/systemd/systemd-bootx64.efi is signed\n"
        self.assertEqual(worker.sbctl_unsigned(shared), [])  # Microsoft's own loader next to Windows (CMP-151)
        self.assertEqual(worker.sbctl_unsigned(shared + UNSIGNED), ["/boot/EFI/Linux/x.efi"])

    def test_sbctl_is_added_only_when_chosen(self):
        config = Configuration.parse(specification())
        hw = demo_inventory()["hardware"]
        self.assertNotIn("sbctl", worker.packages_for(config, hw))
        self.assertIn("sbctl", worker.packages_for(config, hw, True))


class FinalizeEnrollTests(unittest.TestCase):
    def request(self, enroll):
        config = Configuration.parse(DemoProvider().reply("", [])["configuration"])
        return {"target": config.disk, "fingerprint": "x", "configuration": config.as_dict(), "passphrase": "",
                "image": {"format": "qcow2", "path": "/x.qcow2"}, "layout": "erase", "confirmation": config.disk,
                "enroll_keys": enroll}

    def test_enrollment_requires_setup_mode_before_touching_disks(self):
        import finalize_worker
        snapshot = demo_inventory()
        request = self.request(True)
        request["fingerprint"] = snapshot["disks"][0]["fingerprint"]
        with patch.object(finalize_worker.os, "geteuid", return_value=0), \
             patch.object(finalize_worker, "live_environment", return_value=True), \
             patch.object(finalize_worker, "inventory", return_value=snapshot), \
             patch.object(finalize_worker, "restrict_test_targets", side_effect=lambda s: s), \
             patch.object(finalize_worker, "checked_image", side_effect=lambda image, *a: image):
            with patch.object(finalize_worker, "efi_flag", return_value=False), self.assertRaisesRegex(ValidationError, "Setup Mode"):
                finalize_worker.checked_request(dict(request))
            with patch.object(finalize_worker, "efi_flag", return_value=True):
                finalize_worker.checked_request(dict(request))
            for value in ("yes", 1):
                with self.assertRaises(ValidationError):
                    finalize_worker.checked_request({**request, "enroll_keys": value})

    def test_enroll_verifies_signatures_first_and_keeps_microsoft_keys(self):
        import finalize_worker

        class Runner:
            def __init__(self, output): self.calls, self.output = [], output
            def run(self, args, **kw):
                self.calls.append(args)
                return self.output if args[-1] == "verify" else ""
        with patch.object(finalize_worker, "emit"):
            runner, record = Runner(SIGNED), {"secure_boot": {"signed": True, "enrolled": False}}
            finalize_worker.enroll_keys(runner, ["arch-chroot", "/t"], record)
            self.assertEqual(runner.calls[-1], ["arch-chroot", "/t", "sbctl", "enroll-keys", "--microsoft"])
            self.assertTrue(record["secure_boot"]["enrolled"])
            self.assertTrue(record["secure_boot"]["verified"])
            runner, record = Runner(UNSIGNED), {"secure_boot": {"signed": True, "enrolled": False}}
            with self.assertRaises(ValidationError):
                finalize_worker.enroll_keys(runner, ["arch-chroot", "/t"], record)
            self.assertFalse(any("enroll-keys" in c for c in runner.calls))
            with self.assertRaises(ValidationError):
                finalize_worker.enroll_keys(Runner(SIGNED), ["arch-chroot", "/t"], {"secure_boot": None})


    def test_failed_enrollment_is_a_warning_not_a_failed_installation(self):
        import finalize_worker

        class Runner:
            def run(self, args, **kw):
                if "enroll-keys" in args:
                    raise ValidationError("sbctl: could not enroll keys\nfailed to write PK")
                return SIGNED if args[-1] == "verify" else ""
        events, record = [], {"secure_boot": {"signed": True, "enrolled": False}}
        with patch.object(finalize_worker, "emit", side_effect=lambda kind, **d: events.append((kind, d["text"]))):
            finalize_worker.enroll_or_warn(Runner(), ["arch-chroot", "/t"], record)
        self.assertFalse(record["secure_boot"]["enrolled"])
        self.assertIn("sbctl enroll-keys --microsoft", record["warnings"][0])
        self.assertIn("failed to write PK", record["warnings"][0])
        self.assertEqual(events[-1][0], "final-warning")


class VerifyTests(unittest.TestCase):
    def test_pe_signature_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name, data, expected in (("signed", pe_image(0x400), True), ("unsigned", pe_image(0), False),
                                         ("pe32", pe_image(0x400, False), True), ("text", b"#!/bin/sh\n", False)):
                path = Path(tmp) / name
                path.write_bytes(data)
                self.assertEqual(verify.pe_signed(path), expected, name)
            self.assertFalse(verify.pe_signed(Path(tmp) / "missing"))

    def test_unreadable_esp_falls_back_to_firmware_or_finalization(self):
        """Run B: after a copy /boot is vfat fmask=0077; the user cannot read the images."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            efivars = root / "sys/firmware/efi/efivars"
            efivars.mkdir(parents=True)
            with patch.object(verify.Path, "read_bytes", side_effect=PermissionError):
                self.assertIsNone(verify.pe_signed(root / "boot/vmlinuz-linux"))
            with patch.object(verify, "pe_signed", return_value=None):
                self.assertFalse(verify.boot_chain_signed({"signed": True}, root))
                self.assertTrue(verify.boot_chain_signed({"signed": True, "verified": True}, root))
                (efivars / verify.SECURE_BOOT_VAR).write_bytes(b"\x06\x00\x00\x00\x01")
                self.assertTrue(verify.boot_chain_signed({"signed": True}, root))

    def test_shared_esp_loader_is_checked_where_it_boots_from(self):
        """CMP-151: next to Windows systemd-boot lives on the shared ESP at /efi."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for relative in verify.SIGNED_BOOT_FILES:
                (root / relative).parent.mkdir(parents=True, exist_ok=True)
                (root / relative).write_bytes(pe_image(0x400))  # stale copies on the XBOOTLDR /boot
            for relative in ("efi/EFI/BOOT/BOOTX64.EFI", "efi/EFI/systemd/systemd-bootx64.efi"):
                (root / relative).parent.mkdir(parents=True, exist_ok=True)
                (root / relative).write_bytes(pe_image(0))
            self.assertFalse(verify.boot_chain_signed({"signed": True}, root))
            for relative in ("efi/EFI/BOOT/BOOTX64.EFI", "efi/EFI/systemd/systemd-bootx64.efi"):
                (root / relative).write_bytes(pe_image(0x400))
            self.assertTrue(verify.boot_chain_signed({"signed": True}, root))

    def test_secure_boot_checks_follow_the_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for relative in verify.SIGNED_BOOT_FILES:
                (root / relative).parent.mkdir(parents=True, exist_ok=True)
                (root / relative).write_bytes(pe_image(0x400))
            efivars = root / "sys/firmware/efi/efivars"
            efivars.mkdir(parents=True)
            (efivars / verify.SECURE_BOOT_VAR).write_bytes(b"\x06\x00\x00\x00\x01")
            self.assertTrue(verify.secure_boot_enabled(root))
            (root / verify.SIGNED_BOOT_FILES[2]).write_bytes(pe_image(0))
            self.assertFalse(all(verify.pe_signed(root / f) for f in verify.SIGNED_BOOT_FILES))


if __name__ == "__main__":
    unittest.main()
