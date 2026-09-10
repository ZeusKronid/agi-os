"""Read-only host discovery and the official repository catalog."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

from domain import ValidationError


def read_command(args, timeout=30):
    result = subprocess.run(args, text=True, capture_output=True, timeout=timeout,
                            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
    if result.returncode:
        raise ValidationError(f"Не выполнена проверка: {args[0]}")
    return result.stdout


def live_environment():
    return Path("/run/archiso/bootmnt").is_mount()


def fingerprint(disk):
    identity = {k: disk.get(k) for k in ("path", "size", "model", "serial", "wwn", "maj:min")}
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()


def inventory():
    data = json.loads(read_command(["lsblk", "--json", "--bytes", "--output",
        "NAME,PATH,SIZE,TYPE,MODEL,SERIAL,WWN,RO,MOUNTPOINTS,MAJ:MIN"]))

    def in_use(node):
        holders = Path("/sys/class/block") / node["name"] / "holders"
        return (bool([p for p in node.get("mountpoints", []) if p])
                or (holders.is_dir() and any(holders.iterdir()))
                or any(in_use(child) for child in node.get("children", [])))

    disks = []
    for disk in data["blockdevices"]:
        if disk["type"] != "disk":
            continue
        disk["eligible"] = not (disk["ro"] or in_use(disk) or disk["size"] < 12 * 2**30)
        disk["reason"] = "" if disk["eligible"] else "Диск занят, доступен только для чтения или меньше 12 ГиБ"
        disk["fingerprint"] = fingerprint(disk)
        disks.append(disk)
    return {"live": live_environment(), "firmware": "uefi" if Path("/sys/firmware/efi").is_dir() else "bios",
            "cpu_count": os.cpu_count(), "disks": disks}


def selected_disk(snapshot, path):
    disk = next((d for d in snapshot["disks"] if d["path"] == path), None)
    if not disk or not disk["eligible"]:
        raise ValidationError("Выбранный диск недоступен для установки. Обновите список дисков.")
    return disk


class Catalog:
    def __init__(self):
        self.entries = None

    def load(self):
        if self.entries is None:
            output = read_command(["pacman", "-Sl", "core", "extra"], timeout=60)
            self.entries = {}
            for line in output.splitlines():
                fields = line.split()
                if len(fields) >= 3:
                    self.entries[fields[1]] = {"repository": fields[0], "package": fields[1], "version": fields[2]}
        return self.entries

    def search(self, queries):
        entries = self.load()
        return {query: [value for name, value in entries.items() if query.casefold() in name.casefold()][:30]
                for query in queries}

    def validate(self, packages):
        entries = self.load()
        missing = [p for p in packages if p not in entries]
        if missing:
            raise ValidationError("Пакеты не найдены в core/extra: " + ", ".join(missing))
        return [entries[p]["repository"] + "/" + p for p in packages]


def demo_inventory():
    disk = {"name": "vda", "path": "/dev/vda", "size": 64 * 2**30, "type": "disk",
            "model": "Демонстрационный диск", "serial": "DEMO-ONLY", "wwn": "", "maj:min": "0:0",
            "eligible": True, "reason": "", "children": []}
    disk["fingerprint"] = fingerprint(disk)
    return {"live": False, "firmware": "uefi", "cpu_count": 4, "disks": [disk]}
