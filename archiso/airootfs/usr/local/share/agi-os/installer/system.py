"""Read-only host discovery and the official repository catalog."""

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from domain import ValidationError
import hardware as hardware_module


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
        "NAME,PATH,SIZE,TYPE,MODEL,SERIAL,WWN,RO,MOUNTPOINTS,MAJ:MIN,FSTYPE,LABEL,PARTLABEL,PTTYPE,RM,TRAN,START,ROTA"]))

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
        disk["partitions"] = [
            {k: child.get(k) for k in ("path", "size", "fstype", "label", "partlabel", "start")}
            | {"mounted": bool([m for m in child.get("mountpoints", []) if m])}
            for child in disk.get("children", []) if child.get("type") == "part"]
        disks.append(disk)
    return {"live": live_environment(), "firmware": "uefi" if Path("/sys/firmware/efi").is_dir() else "bios",
            "cpu_count": os.cpu_count(), "disks": disks, "hardware": hardware_module.detect()}


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
            # Archiso removes sync databases when preparing the image. Prepare
            # the catalogue before conversation lookup, not only in the worker.
            sync = Path("/var/lib/pacman/sync")
            if live_environment() and any(not (sync / (repo + ".db")).is_file()
                                          for repo in ("core", "extra")):
                read_command(["sudo", "-n", "/usr/bin/pacman", "-Sy", "--noconfirm"], timeout=180)
            output = read_command(["pacman", "-Sl", "core", "extra"], timeout=60)
            if not output.strip():
                raise ValidationError("Каталог пакетов пуст. Проверьте сеть и повторите запрос: "
                                      "доступность пакетов пока не подтверждена.")
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

    def estimate(self, packages):
        """Exact installed and download sizes of the resolved package set (with dependencies)."""
        qualified = self.validate(packages)
        # Resolve against an empty local database: the Live system already has most
        # dependencies installed, and a real installation starts from nothing.
        scratch = Path(tempfile.mkdtemp(prefix="agi-estimate-"))
        (scratch / "local").mkdir()
        (scratch / "sync").symlink_to("/var/lib/pacman/sync")
        try:
            resolved = read_command(["pacman", "--dbpath", str(scratch), "-Sp", "--print-format", "%n %s", "--", *qualified], timeout=120)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
        names, download = [], 0
        for line in resolved.splitlines():
            fields = line.split()
            if len(fields) == 2 and fields[1].isdigit():
                names.append(fields[0])
                download += int(fields[1])
        installed = 0
        for line in read_command(["pacman", "-Si", "--", *names], timeout=120).splitlines():
            if line.startswith("Installed Size"):
                value, unit = line.split(":", 1)[1].split()
                installed += float(value) * {"B": 1, "KiB": 2**10, "MiB": 2**20, "GiB": 2**30}[unit]
        return {"packages": len(names), "installed": int(installed), "download": download}


def demo_inventory():
    disk = {"name": "vda", "path": "/dev/vda", "size": 64 * 2**30, "type": "disk", "tran": "nvme", "rota": False,
            "model": "Демонстрационный диск", "serial": "DEMO-ONLY", "wwn": "", "maj:min": "0:0",
            "eligible": True, "reason": "", "children": []}
    disk["fingerprint"] = fingerprint(disk)
    return {"live": False, "firmware": "uefi", "cpu_count": 4, "disks": [disk], "hardware": hardware_module.demo()}
