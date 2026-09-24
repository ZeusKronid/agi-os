"""Read-only hardware inventory of this computer and the driver packages it needs.

The preview VM runs on virtual devices, so a system that works there says nothing
about the real GPU, Wi-Fi, sound or battery. This module gives the model and the
user the real inventory as data, derives the driver/firmware packages from it
deterministically (never from the model), and names what the preview cannot check.
Only unprivileged sources are read: lspci, sysfs and /proc. Device strings are
untrusted (a USB descriptor is written by the device): they are cut to one line
and bounded before they reach a prompt, the review or a record.
"""

import hashlib
import json
import math
import re
import subprocess
import unicodedata
from pathlib import Path

VENDORS = {"8086": "Intel", "1002": "AMD", "1022": "AMD", "10de": "NVIDIA", "14e4": "Broadcom", "10ec": "Realtek",
           "168c": "Qualcomm Atheros", "17cb": "Qualcomm", "14c3": "MediaTek", "1af4": "virtio", "1234": "QEMU",
           "1b36": "Red Hat", "15ad": "VMware", "1414": "Microsoft Hyper-V", "80ee": "VirtualBox", "1969": "Qualcomm Atheros",
           "8087": "Intel", "0489": "Foxconn", "0bda": "Realtek", "0a5c": "Broadcom", "0cf3": "Qualcomm Atheros"}
VIRTUAL_VENDORS = {"1af4", "1234", "1b36", "15ad", "1414", "80ee"}
# SMBIOS chassis types that mean a battery-powered portable computer.
PORTABLE_CHASSIS = {8: "Portable", 9: "Laptop", 10: "Notebook", 14: "Sub Notebook", 30: "Tablet", 31: "Convertible", 32: "Detachable"}
CHASSIS = {3: "Desktop", 4: "Low Profile Desktop", 5: "Pizza Box", 6: "Mini Tower", 7: "Tower", 11: "Hand Held",
           13: "All In One", 15: "Space-saving", 16: "Lunch Box", 17: "Main Server Chassis", 23: "Rack Mount Chassis",
           35: "Mini PC", 36: "Stick PC", **PORTABLE_CHASSIS}
USB_CLASSES = {"01": "audio", "02": "modem", "03": "input", "06": "camera", "07": "printer", "08": "storage",
               "0e": "video", "e0": "wireless", "ff": "device"}
# First NVIDIA device ID of the Turing generation: nvidia-open (the open kernel
# modules) supports Turing and newer only; older chips use nouveau from mesa.
NVIDIA_OPEN_FROM = 0x1E00
NVIDIA_MODULES = ("nvidia", "nvidia_modeset", "nvidia_uvm", "nvidia_drm")
# Packages that already provide the NVIDIA kernel module: a user's choice among them wins.
NVIDIA_MODULE_PACKAGES = {"nvidia", "nvidia-dkms", "nvidia-lts", "nvidia-open", "nvidia-open-dkms", "nvidia-open-lts"}
# Power managers that replace (or conflict with) power-profiles-daemon.
POWER_MANAGERS = {"tlp", "auto-cpufreq", "tuned", "tuned-ppd"}
EXTRA_KERNELS = ("linux-lts", "linux-zen", "linux-hardened", "linux-rt", "linux-rt-lts")
SECURE_BOOT_VAR = "SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c"
# Setup Mode: no platform key is enrolled, so the firmware accepts new Secure Boot keys.
SETUP_MODE_VAR = "SetupMode-8be4df61-93ca-11d2-aa0d-00e098032b8c"


def efi_flag(name, root=None):
    """A one-byte UEFI global variable (after the 4 attribute bytes) as True/False, None if absent."""
    try:
        return ((root or SYS) / "firmware/efi/efivars" / name).read_bytes()[4:5] == b"\x01"
    except OSError:
        return None
SYS = Path("/sys")
DEVICE_KEYS = ("class", "class_name", "vendor", "vendor_id", "device_id", "name", "driver", "bus")


def clean(value, limit=120):
    """One bounded line: control, format (bidi), separator and private characters become
    spaces. This is the only way device text gets into prompts, reviews and records."""
    if not isinstance(value, str):
        return ""
    value = "".join(" " if unicodedata.category(c) in ("Cc", "Cf", "Co", "Cs", "Zl", "Zp") else c for c in value)
    return re.sub(r" {2,}", " ", value).strip()[:limit]


def read_text(path, default=""):
    try:
        return clean(Path(path).read_text(errors="replace"), 400)
    except (OSError, ValueError):
        return default


def lspci_records():
    """PCI devices as dicts of the `lspci -vmmk -nn` record fields (empty when lspci is unavailable)."""
    try:
        output = subprocess.run(["lspci", "-vmmk", "-nn"], text=True, capture_output=True, timeout=20,
                                env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"}).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    return parse_lspci(output)


def parse_lspci(output):
    records = []
    for block in output.strip().split("\n\n"):
        fields = {}
        for line in block.splitlines():
            key, _, value = line.partition(":")
            fields.setdefault(key.strip(), value.strip())  # -k repeats Module:; the first Driver: is the bound one
        if fields.get("Slot"):
            records.append(fields)
    return records


def split_id(value):
    """'Raptor Lake-S UHD Graphics [a788]' -> ('Raptor Lake-S UHD Graphics', 'a788')."""
    match = re.fullmatch(r"(.*?)\s*\[([0-9a-f]{4})\]", value or "")
    return (match.group(1), match.group(2)) if match else (value or "", "")


def device_entry(record):
    class_name, class_id = split_id(record.get("Class", ""))
    vendor_name, vendor_id = split_id(record.get("Vendor", ""))
    device_name, device_id = split_id(record.get("Device", ""))
    return {"class": clean(class_id, 4), "class_name": clean(class_name, 60), "vendor": clean(VENDORS.get(vendor_id, vendor_name), 60),
            "vendor_id": clean(vendor_id, 4), "device_id": clean(device_id, 4), "name": clean(device_name),
            "driver": clean(record.get("Driver", ""), 40), "bus": "pci"}


def usb_devices():
    """USB devices except hubs, by device class or the first interface class; Bluetooth is E0."""
    found = []
    for device in sorted(SYS.glob("bus/usb/devices/*")):
        if not (device / "idVendor").exists():
            continue  # interface nodes
        klass = read_text(device / "bDeviceClass")
        ifaces = sorted(device.glob("*:*"))
        interfaces = [read_text(iface / "bInterfaceClass") for iface in ifaces]
        # Class E0 subclass 01 protocol 01 is Bluetooth; E0/01/03 is RNDIS (USB tethering).
        bluetooth = ((klass, read_text(device / "bDeviceSubClass"), read_text(device / "bDeviceProtocol")) == ("e0", "01", "01")
                     or any((read_text(i / "bInterfaceClass"), read_text(i / "bInterfaceSubClass"), read_text(i / "bInterfaceProtocol"))
                            == ("e0", "01", "01") for i in ifaces))
        if bluetooth:
            klass = "e0"
        elif klass in ("00", "ef", "e0", ""):
            klass = next((c for c in interfaces if c not in ("", "09", "e0")), "02" if "e0" in interfaces else klass)
        if klass == "09":
            continue  # hubs
        vendor, product_id = read_text(device / "idVendor"), read_text(device / "idProduct")
        name = read_text(device / "product") or read_text(device / "manufacturer") or f"{vendor}:{product_id}"
        found.append({"class": clean(klass, 4), "class_name": USB_CLASSES.get(klass, "device"), "vendor": clean(VENDORS.get(vendor, ""), 60),
                      "vendor_id": clean(vendor, 4), "device_id": clean(product_id, 4), "name": clean(name), "driver": "", "bus": "usb"})
    return found


def wireless_interfaces():
    return sorted(p.parent.name for p in SYS.glob("class/net/*/wireless"))


def gpu_audio(device):
    """The HDMI audio function of a graphics card is not the computer's sound card."""
    return device["vendor_id"] in ("10de", "1002") and bool(re.search(r"HD(MI)? Audio|High Definition Audio|Audio Controller", device["name"], re.I))


def proc_field(path, key):
    for line in Path(path).read_text(errors="replace").splitlines():
        name, _, value = line.partition(":")
        if name.strip() == key:
            return value.strip()
    return ""


def detect():
    """Inventory of this computer; every value is plain data for the prompt, the review and the rules."""
    cpu_vendor = proc_field("/proc/cpuinfo", "vendor_id")
    cpu_vendor = {"GenuineIntel": "Intel", "AuthenticAMD": "AMD"}.get(cpu_vendor, cpu_vendor)
    memory = proc_field("/proc/meminfo", "MemTotal").split()
    memory = int(memory[0]) * 1024 if memory and memory[0].isdigit() else 0
    pci = [device_entry(r) for r in lspci_records()]
    usb = usb_devices()
    gpus = [d for d in pci if d["class"] in ("0300", "0302", "0380")]
    network = [{**d, "kind": "wifi" if d["class"] == "0280" else "ethernet"} for d in pci if d["class"] in ("0200", "0280")]
    wireless = wireless_interfaces()
    if wireless and not any(n["kind"] == "wifi" for n in network):
        network.append({"class": "", "class_name": "Network controller", "vendor": "", "vendor_id": "", "device_id": "",
                        "name": ", ".join(wireless), "driver": "", "bus": "", "kind": "wifi"})
    audio = [d for d in pci if d["class"] in ("0401", "0403") and not gpu_audio(d)]
    bluetooth = [d for d in pci if d["class"] == "0d11"] + [d for d in usb if d["class"] == "e0"]
    if not bluetooth and any(SYS.glob("class/bluetooth/hci*")):
        bluetooth.append({"class": "", "class_name": "Bluetooth", "vendor": "", "vendor_id": "", "device_id": "",
                          "name": ", ".join(sorted(p.name for p in SYS.glob("class/bluetooth/hci*"))), "driver": "", "bus": ""})
    chassis_code = read_text(SYS / "class/dmi/id/chassis_type")
    chassis_code = int(chassis_code) if chassis_code.isdigit() else 0
    # A UPS also reports type Battery but with scope Device; a laptop battery has no scope or System.
    battery = any(read_text(p / "type") == "Battery" and read_text(p / "scope") != "Device" for p in SYS.glob("class/power_supply/*"))
    try:
        virtualization = subprocess.run(["systemd-detect-virt"], text=True, capture_output=True, timeout=10,
                                        env={"PATH": "/usr/bin:/bin"}).stdout.strip() or "none"
    except (OSError, subprocess.TimeoutExpired):
        virtualization = "unknown"
    return profile({
        # No PCI records while the bus has devices means lspci failed: nothing may claim "verified".
        "detected": bool(pci) or not any(SYS.glob("bus/pci/devices/*")),
        "cpu": {"vendor": cpu_vendor, "model": proc_field("/proc/cpuinfo", "model name")},
        "memory": memory,
        "virtualization": virtualization,
        "chassis": {"type": CHASSIS.get(chassis_code, "Unknown" if not chassis_code else f"Type {chassis_code}"),
                    "vendor": read_text(SYS / "class/dmi/id/sys_vendor"),
                    "product": read_text(SYS / "class/dmi/id/product_name"),
                    "portable": chassis_code in PORTABLE_CHASSIS or battery, "battery": battery},
        "gpus": gpus, "network": network, "audio": audio, "bluetooth": bluetooth, "usb": usb,
        "tpm": any(SYS.glob("class/tpm/tpm*")),
        "secure_boot": efi_flag(SECURE_BOOT_VAR),
        "setup_mode": efi_flag(SETUP_MODE_VAR),
    })


def profile(data):
    """Bounded, complete copy of an inventory from any source (channel, record, older build)."""
    if not isinstance(data, dict):
        raise ValueError("Invalid hardware inventory")

    def devices(items, extra=()):
        if not isinstance(items, list):
            return []
        return [{k: clean(d.get(k)) for k in (*DEVICE_KEYS, *extra)} for d in items[:64] if isinstance(d, dict)]

    cpu = data.get("cpu") if isinstance(data.get("cpu"), dict) else {}
    chassis = data.get("chassis") if isinstance(data.get("chassis"), dict) else {}
    return {
        "detected": data.get("detected") is not False,
        "cpu": {"vendor": clean(cpu.get("vendor"), 40), "model": clean(cpu.get("model"))},
        "memory": data["memory"] if type(data.get("memory")) is int and data["memory"] >= 0 else 0,
        "virtualization": clean(data.get("virtualization"), 40) or "unknown",
        "chassis": {"type": clean(chassis.get("type"), 40), "vendor": clean(chassis.get("vendor"), 80),
                    "product": clean(chassis.get("product"), 80),
                    "portable": chassis.get("portable") is True, "battery": chassis.get("battery") is True},
        "gpus": devices(data.get("gpus")), "network": devices(data.get("network"), ("kind",)),
        "audio": devices(data.get("audio")), "bluetooth": devices(data.get("bluetooth")), "usb": devices(data.get("usb")),
        "tpm": data.get("tpm") is True,
        "secure_boot": data.get("secure_boot") if data.get("secure_boot") in (True, False) else None,
        "setup_mode": data.get("setup_mode") if data.get("setup_mode") in (True, False) else None,
    }


def digest(hardware, packages=(), session=""):
    """What the consent binds: the install this hardware leads to, not every USB mouse."""
    plan = driver_plan(hardware, packages, session)
    material = {k: plan[k] for k in ("packages", "services", "modules")} | {"detected": profile(hardware)["detected"]}
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()


def virtual(hardware):
    return profile(hardware)["virtualization"] not in ("none", "unknown", "")


def describe(hardware):
    """Short human lines for the review and the prompt."""
    h = profile(hardware)
    lines = []
    if not h["detected"]:
        lines.append("The hardware could not be detected (lspci is unavailable): graphics, Wi-Fi and sound are not checked")
    # MemTotal excludes firmware-reserved memory: a 16 GiB machine reports ~15.3 GiB.
    lines.append(f"CPU: {h['cpu']['model'] or h['cpu']['vendor'] or 'unknown'}; "
                 f"memory: ~{2 * math.ceil(h['memory'] / 2**31)} GiB ({h['memory'] / 2**30:.1f} GiB available to the system)")
    chassis = h["chassis"]
    model = " ".join(filter(None, [chassis["vendor"], chassis["product"]]))
    lines.append(f"Computer: {'laptop' if chassis['portable'] else 'desktop'}{' — ' + model if model else ''}"
                 + ("; has a battery" if chassis["battery"] else ""))
    if h["virtualization"] not in ("none", "unknown", ""):
        lines.append(f"Virtual machine: {h['virtualization']}")

    def named(d):
        return f"{d['vendor']} {d['name']}".strip() + (f" (driver {d['driver']})" if d.get("driver") else "")
    lines.append("Graphics: " + ("; ".join(named(g) for g in h["gpus"]) or "not detected"))
    lines.append("Network: " + ("; ".join(("Wi-Fi " if n["kind"] == "wifi" else "Ethernet ") + named(n) for n in h["network"]) or "not detected"))
    lines.append("Sound: " + ("; ".join(named(a) for a in h["audio"]) or "not detected"))
    lines.append("Bluetooth: " + ("; ".join(named(b) for b in h["bluetooth"]) or "none"))
    others = [u for u in h["usb"] if u["class"] != "e0"]
    if others:
        lines.append("USB: " + "; ".join(f"{u['class_name']} — {named(u)}" for u in others[:8]))
    lines.append("TPM: " + ("yes" if h["tpm"] else "no") + "; Secure Boot: "
                 + {True: "on", False: "off", None: "unknown"}[h["secure_boot"]]
                 + ("; the firmware is in Setup Mode — you can enroll your own keys" if h["setup_mode"] else ""))
    return lines


def driver_plan(hardware, packages=(), session=""):
    """Deterministic packages/services/initramfs modules for this hardware, and what the preview cannot verify.

    `packages` are the user's own choices: a rule steps back when the user already
    picked a competing tool (for example tlp instead of power-profiles-daemon).
    Graphics userspace (mesa, vulkan, VA-API, NVIDIA) only makes sense with a session.
    """
    h = profile(hardware)
    chosen = set(packages)
    add, services, modules, notes, unverified = [], [], [], [], []
    add += {"Intel": ["intel-ucode"], "AMD": ["amd-ucode"]}.get(h["cpu"]["vendor"], ["intel-ucode", "amd-ucode"])
    if not h["detected"]:
        unverified.append("undetected hardware: graphics, Wi-Fi, sound and Bluetooth")
    real_gpus = [g for g in h["gpus"] if g["vendor_id"] not in VIRTUAL_VENDORS]
    # The engine always installs `linux`; extra kernels need their own NVIDIA module.
    kernels = [k for k in EXTRA_KERNELS if k in chosen]
    if session:
        add.append("mesa")
        for gpu in real_gpus:
            label = f"{gpu['vendor']} {gpu['name']}".strip()
            if gpu["vendor_id"] == "8086":
                add += ["vulkan-intel", "intel-media-driver"]
            elif gpu["vendor_id"] in ("1002", "1022"):
                add.append("vulkan-radeon")  # VA-API for AMD ships inside mesa
            elif gpu["vendor_id"] == "10de":
                try:
                    turing_or_newer = int(gpu["device_id"], 16) >= NVIDIA_OPEN_FROM
                except ValueError:
                    turing_or_newer = False
                if turing_or_newer:
                    add.append("nvidia-utils")
                    modules += NVIDIA_MODULES
                    if chosen & NVIDIA_MODULE_PACKAGES:
                        notes.append(f"{label}: using the NVIDIA module you chose; the modules go into the initramfs")
                    elif set(kernels) - {"linux-lts"}:
                        add += ["nvidia-open-dkms", "linux-headers", *(k + "-headers" for k in kernels)]
                        notes.append(f"{label}: the NVIDIA driver nvidia-open-dkms is built for each kernel "
                                     f"(linux, {', '.join(kernels)}); the modules go into the initramfs")
                    else:
                        add += ["nvidia-open", *(["nvidia-open-lts"] if kernels else [])]
                        notes.append(f"{label}: NVIDIA driver — the open kernel modules nvidia-open (Turing and newer) "
                                     "and the closed user-space part nvidia-utils; the modules go into the initramfs")
                else:
                    add.append("vulkan-nouveau")
                    notes.append(f"{label}: older than Turing — the official repositories have no supported proprietary "
                                 "driver, so nouveau from mesa is used")
        if h["gpus"] and not real_gpus:
            notes.append("The graphics are virtual: mesa only")
    for gpu in real_gpus:
        unverified.append(f"graphics {gpu['vendor']} {gpu['name']}".strip())
    wifi = [n for n in h["network"] if n["kind"] == "wifi"]
    if wifi:
        add.append("wireless-regdb")
        for device in wifi:
            if device["vendor_id"] == "14e4":
                notes.append(f"Wi-Fi Broadcom {device['name']}: some chips work only with the proprietary driver — "
                             "if Wi-Fi does not work, install broadcom-wl-dkms and linux-headers from extra")
            elif device["bus"] == "pci" and not device["driver"]:
                notes.append(f"Wi-Fi {device['vendor']} {device['name']}: the driver did not load in Live — it may need firmware or a driver from outside the repositories")
        unverified.append("Wi-Fi " + "; ".join(f"{n['vendor']} {n['name']}".strip() for n in wifi))
    if h["audio"]:
        add += ["sof-firmware", "alsa-ucm-conf"] if any(a["vendor_id"] == "8086" for a in h["audio"]) else ["alsa-ucm-conf"]
        # PipeWire needs its session manager and compatibility layers; only PulseAudio replaces the stack.
        if session and not any(p == "pulseaudio" or p.startswith("pulseaudio-") for p in chosen):
            add += ["pipewire", "pipewire-pulse", "pipewire-alsa", "wireplumber"]
        unverified.append("sound " + "; ".join(f"{a['vendor']} {a['name']}".strip() for a in h["audio"]))
    if h["bluetooth"]:
        add += ["bluez", "bluez-utils"]
        services.append("bluetooth.service")
        unverified.append("Bluetooth")
    if h["chassis"]["portable"]:
        if not chosen & POWER_MANAGERS:
            add.append("power-profiles-daemon")
            services.append("power-profiles-daemon.service")  # also when the user chose the package themselves
        unverified.append("battery, power saving and laptop keys")
    if h["secure_boot"]:
        notes.append("Secure Boot is on: sign the system with your own keys (the Secure Boot option before the preview; "
                     "the keys are enrolled during installation in Setup Mode) or turn Secure Boot off in UEFI")
    add = [p for p in dict.fromkeys(add) if p not in chosen]
    return {"packages": add, "services": list(dict.fromkeys(services)), "modules": list(dict.fromkeys(modules)),
            "notes": notes, "unverified": unverified}


def initramfs_config(plan, encrypted, hibernate=False, lvm=False):
    """mkinitcpio drop-in for this plan, or '' when the stock configuration is right.

    NVIDIA's own modules replace the generic kms hook (it would pull nouveau, which
    nvidia-utils blacklists); the encrypt hook goes before filesystems. resume must
    follow encrypt (the swap file lives inside the opened root) and precede
    filesystems, so the saved image is restored before anything is mounted read-write.
    """
    modules = list(plan.get("modules", []))
    if not modules and not encrypted and not hibernate and not lvm:
        return ""
    # lvm2 activates the root volume group after encrypt opened it and before resume reads
    # the swap file on the root logical volume.
    hooks = ["base", "udev", "autodetect", "microcode", "modconf", *([] if modules else ["kms"]),
             "keyboard", "keymap", "consolefont", "block", *(["encrypt"] if encrypted else []),
             *(["lvm2"] if lvm else []), *(["resume"] if hibernate else []), "filesystems", "fsck"]
    return ("MODULES=(" + " ".join(modules) + ")\n" if modules else "") + "HOOKS=(" + " ".join(hooks) + ")\n"


def demo():
    return profile({"cpu": {"vendor": "Intel", "model": "Demo CPU"}, "memory": 16 * 2**30,
                    "virtualization": "none",
                    "chassis": {"type": "Notebook", "vendor": "Demo", "product": "Laptop", "portable": True, "battery": True},
                    "gpus": [{"class": "0300", "class_name": "VGA compatible controller", "vendor": "Intel", "vendor_id": "8086",
                              "device_id": "a788", "name": "UHD Graphics", "driver": "i915", "bus": "pci"}],
                    "network": [{"class": "0280", "class_name": "Network controller", "vendor": "Intel", "vendor_id": "8086",
                                 "device_id": "272b", "name": "Wi-Fi 7 BE200", "driver": "iwlwifi", "bus": "pci", "kind": "wifi"}],
                    "audio": [{"class": "0403", "class_name": "Audio device", "vendor": "Intel", "vendor_id": "8086",
                               "device_id": "7a50", "name": "HD Audio", "driver": "snd_hda_intel", "bus": "pci"}],
                    "bluetooth": [{"class": "e0", "class_name": "wireless", "vendor": "Intel", "vendor_id": "8087",
                                   "device_id": "0036", "name": "BE200 Bluetooth", "driver": "", "bus": "usb"}],
                    "usb": [], "tpm": True, "secure_boot": False})
