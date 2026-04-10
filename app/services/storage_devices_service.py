"""
Block-device discovery (lsblk) and optional mount/unmount helpers for Pi / Linux.

Mount/format operations require NAS_STORAGE_OPS_ENABLED and typically root privileges.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status

from app.core.config import get_settings
from app.db.mongo import get_db

# lsblk NAME values that map to /dev/<name> (avoid path injection if NAME is ever odd).
_BLOCK_KNAME_SAFE = re.compile(r"^[a-zA-Z0-9_\-\+]+$")


def _infer_dev_path(name: str, path: str, typ: str) -> str:
    """When lsblk omits PATH, derive /dev/<kname> so partitions (e.g. sda1) are mountable."""
    p = (path or "").strip()
    if p.startswith("/dev/"):
        return p
    if typ not in ("part", "crypt", "lvm", "disk") or not name:
        return p
    if "/" in name or ".." in name or not _BLOCK_KNAME_SAFE.match(name):
        return p
    return f"/dev/{name}"


def _sysfs_block_size_bytes(block_name: str) -> int | None:
    """Sector count from sysfs × 512; lsblk sometimes reports size 0 on parent disk nodes."""
    if not block_name or not _BLOCK_KNAME_SAFE.match(block_name):
        return None
    try:
        raw = Path(f"/sys/class/block/{block_name}/size").read_text().strip()
        sectors = int(raw)
        if sectors <= 0:
            return None
        return sectors * 512
    except (OSError, ValueError):
        return None


def _row_sysfs_block_name(row: dict[str, Any]) -> str | None:
    n = (row.get("name") or "").strip()
    if n and _BLOCK_KNAME_SAFE.match(n):
        return n
    path = (row.get("path") or "").strip()
    if not path.startswith("/dev/"):
        return None
    base = path[len("/dev/") :].split("/")[-1]
    if base and _BLOCK_KNAME_SAFE.match(base):
        return base
    return None


def _blkid_probe_fstype(dev_path: str) -> str | None:
    try:
        r = subprocess.run(
            ["blkid", "-o", "value", "-s", "TYPE", dev_path],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        out = (r.stdout or "").strip()
        return out or None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def _enrich_block_device_row(row: dict[str, Any]) -> None:
    """Backfill size and fstype when lsblk JSON is sparse (common for USB + parent disk rows)."""
    path = (row.get("path") or "").strip()
    size = int(row.get("size_bytes") or 0)
    if size == 0:
        bn = _row_sysfs_block_name(row)
        if bn:
            sz = _sysfs_block_size_bytes(bn)
            if sz:
                row["size_bytes"] = sz
    if path.startswith("/dev/") and not row.get("fstype"):
        ft = _blkid_probe_fstype(path)
        if ft:
            row["fstype"] = ft


def _is_kernel_virtual_storage_noise(row: dict[str, Any]) -> bool:
    """
    Exclude devices that look like block devices but are not user-attached disks.

    Raspberry Pi OS uses zram for compressed swap and may expose loop+swap; these are
    not USB/SATA volumes and confuse the Storage page if listed next to mmcblk/USB drives.
    """
    name = (row.get("name") or "").lower()
    fst = (row.get("fstype") or "").lower()
    if name.startswith("zram"):
        return True
    if name.startswith("loop") and fst == "swap":
        return True
    return False


def _run_lsblk_json() -> dict[str, Any] | None:
    try:
        r = subprocess.run(
            [
                "lsblk",
                "-J",
                "-b",
                "-o",
                "NAME,PATH,TYPE,SIZE,FSTYPE,LABEL,MOUNTPOINT,MODEL,ROTA,TRAN,HOTPLUG",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if r.returncode != 0 or not r.stdout.strip():
            return None
        return json.loads(r.stdout)
    except (FileNotFoundError, json.JSONDecodeError, subprocess.TimeoutExpired):
        return None


def _human_connection(trans: str | None, hotplug: str | None) -> str:
    t = (trans or "").lower()
    if t in ("usb",):
        return "usb"
    if t in ("sata", "sas", "nvme", "pcie"):
        return "sata_nvme"
    if t == "mmc":
        return "mmc"
    return "other"


def _device_kind(rotational: int | None, trans: str | None) -> str:
    if trans and "nvme" in trans.lower():
        return "ssd"
    if rotational == 0:
        return "ssd"
    if rotational == 1:
        return "hdd"
    return "unknown"


def _lsblk_has_partition_child(node: dict[str, Any]) -> bool:
    for ch in node.get("children") or []:
        if isinstance(ch, dict) and (ch.get("type") or "").lower() == "part":
            return True
    return False


def _flatten_lsblk(node: dict[str, Any], disk_model: str | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    name = node.get("name") or ""
    typ = (node.get("type") or "").lower()
    path = _infer_dev_path(str(name), str(node.get("path") or ""), typ)
    size = int(node.get("size") or 0)
    fstype = (node.get("fstype") or "") or None
    label = (node.get("label") or "") or None
    mp = node.get("mountpoint") or ""
    if not mp:
        mps = node.get("mountpoints")
        if isinstance(mps, list) and mps:
            mp = (mps[0] or "") if mps else ""
    model = (node.get("model") or "").strip() or disk_model
    rota = node.get("rota")
    if isinstance(rota, str) and rota.isdigit():
        rota = int(rota)
    elif not isinstance(rota, int):
        rota = None
    trans = node.get("tran") or node.get("transport")
    hotplug = node.get("hotplug")

    if typ == "disk":
        disk_model = (node.get("model") or "").strip() or disk_model

    def _append_row(t: str) -> None:
        out.append(
            {
                "id": path,
                "name": name,
                "path": path,
                "type": t,
                "size_bytes": size,
                "fstype": fstype,
                "label": label,
                "mountpoint": mp if mp else None,
                "mounted": bool(mp),
                "model": model,
                "device_kind": _device_kind(rota, str(trans) if trans else None),
                "connection": _human_connection(str(trans) if trans else None, str(hotplug) if hotplug else None),
            }
        )

    if typ in ("part", "crypt", "lvm") and path.startswith("/dev/"):
        _append_row(typ)

    # Whole-device volumes (no MBR/GPT partitions) only appear as TYPE=disk in lsblk; USB HDDs
    # are often formatted or shipped that way. Skip when partition children exist (use sda1, etc.).
    children = node.get("children") or []
    if typ == "disk" and path.startswith("/dev/") and not _lsblk_has_partition_child(node):
        has_only_disk_level = not children or bool(fstype) or bool(mp and str(mp).strip())
        if has_only_disk_level:
            _append_row("disk")

    for ch in node.get("children") or []:
        if isinstance(ch, dict):
            dm = disk_model if typ == "disk" else disk_model
            out.extend(_flatten_lsblk(ch, dm))

    return out


def discover_block_devices() -> list[dict[str, Any]]:
    data = _run_lsblk_json()
    if not data:
        return []
    devices: list[dict[str, Any]] = []
    for top in data.get("blockdevices") or []:
        if isinstance(top, dict):
            devices.extend(_flatten_lsblk(top, (top.get("model") or "").strip() or None))
    # Dedupe by path
    seen: set[str] = set()
    uniq: list[dict[str, Any]] = []
    for d in devices:
        p = d.get("path") or ""
        if p and p not in seen:
            seen.add(p)
            uniq.append(d)
    for d in uniq:
        _enrich_block_device_row(d)
    return [d for d in uniq if not _is_kernel_virtual_storage_noise(d)]


def _usage_for_path(mount_path: str | None) -> dict[str, float | int] | None:
    if not mount_path:
        return None
    try:
        p = Path(mount_path)
        if not p.is_dir():
            return None
        u = shutil.disk_usage(p)
        pct = round((u.used / u.total) * 100.0, 2) if u.total else 0.0
        return {
            "total": int(u.total),
            "used": int(u.used),
            "free": int(u.free),
            "usage_percentage": pct,
        }
    except OSError:
        return None


async def load_device_prefs() -> dict[str, dict[str, Any]]:
    db = get_db()
    out: dict[str, dict[str, Any]] = {}
    async for doc in db.storage_device_prefs.find({}):
        key = doc.get("device_path") or doc.get("id")
        if key:
            out[str(key)] = {
                "friendly_name": doc.get("friendly_name"),
                "usage_type": doc.get("usage_type", "general"),
                "auto_mount": bool(doc.get("auto_mount", False)),
                "suggested_mount_path": doc.get("suggested_mount_path"),
            }
    return out


async def save_device_prefs(
    device_path: str,
    *,
    friendly_name: str | None,
    usage_type: str,
    auto_mount: bool,
    suggested_mount_path: str | None,
) -> None:
    db = get_db()
    await db.storage_device_prefs.update_one(
        {"device_path": device_path},
        {
            "$set": {
                "device_path": device_path,
                "friendly_name": friendly_name,
                "usage_type": usage_type,
                "auto_mount": auto_mount,
                "suggested_mount_path": suggested_mount_path,
            }
        },
        upsert=True,
    )


def validate_mount_path(path: str) -> Path:
    p = Path(path).resolve()
    allowed = get_settings().storage_mount_allow_prefixes_list()
    ok = any(str(p).startswith(prefix + "/") or str(p) == prefix.rstrip("/") for prefix in allowed)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Mount point must be under allowed prefixes: {allowed}",
        )
    return p


def validate_device_path(dev: str) -> None:
    if not re.match(r"^/dev/[a-zA-Z0-9/_-]+$", dev):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid device path")


def try_mount(source: str, mount_point: str, fstype: str | None = None) -> None:
    settings = get_settings()
    if not settings.nas_storage_ops_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Storage operations disabled. Set NAS_STORAGE_OPS_ENABLED=true and run with sufficient privileges.",
        )
    validate_device_path(source)
    dest = validate_mount_path(mount_point)
    dest.mkdir(parents=True, exist_ok=True)
    cmd: list[str] = ["mount"]
    if fstype:
        cmd.extend(["-t", fstype])
    cmd.extend([source, str(dest)])
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=60)
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or exc.stdout or "").strip() or str(exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Mount failed: {err[:500]}",
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="`mount` command not found",
        ) from exc


def try_unmount(mount_point: str, lazy: bool = False) -> None:
    settings = get_settings()
    if not settings.nas_storage_ops_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Storage operations disabled.",
        )
    validate_mount_path(mount_point)
    cmd = ["umount", mount_point]
    if lazy:
        cmd.insert(1, "-l")
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=120)
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or exc.stdout or "").strip() or str(exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unmount failed: {err[:500]}",
        ) from exc


def list_directory(path: str) -> list[dict[str, Any]]:
    """List files/folders under an allowed mount path (read-only)."""
    root = validate_mount_path(path)
    if not root.is_dir():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Path not found or not a directory")
    entries: list[dict[str, Any]] = []
    try:
        for name in sorted(os.listdir(root)):
            if name.startswith("."):
                continue
            p = root / name
            try:
                st = p.stat()
                is_dir = p.is_dir()
                entries.append(
                    {
                        "name": name,
                        "path": str(p),
                        "type": "directory" if is_dir else "file",
                        "size": 0 if is_dir else int(st.st_size),
                    }
                )
            except OSError:
                continue
    except OSError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    return entries


def _connection_display(connection: str | None) -> str:
    c = (connection or "other").lower()
    return {
        "usb": "USB",
        "sata_nvme": "SATA / NVMe",
        "mmc": "SD / MMC",
        "other": "Other",
    }.get(c, c.replace("_", " ").title())


def _device_kind_display(kind: str | None) -> str:
    k = (kind or "unknown").lower()
    return {"ssd": "SSD", "hdd": "HDD", "unknown": "Storage"}.get(k, k.upper())


async def build_devices_response() -> list[dict[str, Any]]:
    raw = discover_block_devices()
    prefs = await load_device_prefs()
    out: list[dict[str, Any]] = []
    for d in raw:
        path = d["path"]
        pref = prefs.get(path, {})
        usage = _usage_for_path(d.get("mountpoint"))
        display_name = pref.get("friendly_name") or d.get("label") or d.get("name") or path
        conn = d.get("connection")
        out.append(
            {
                **d,
                "display_name": display_name,
                "usage_type": pref.get("usage_type", "general"),
                "auto_mount": pref.get("auto_mount", False),
                "suggested_mount_path": pref.get("suggested_mount_path"),
                "usage": usage,
                "connection_display": _connection_display(str(conn) if conn else None),
                "device_kind_display": _device_kind_display(d.get("device_kind")),
            }
        )
    return out


def try_format(device_path: str, fstype: str) -> None:
    """Destructive: wipe partition. Requires NAS_STORAGE_OPS_ENABLED and NAS_FORMAT_ENABLED."""
    settings = get_settings()
    if not settings.nas_storage_ops_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Storage operations disabled. Set NAS_STORAGE_OPS_ENABLED=true and run with sufficient privileges.",
        )
    if not settings.nas_format_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Formatting disabled. Set NAS_FORMAT_ENABLED=true (dangerous).",
        )
    validate_device_path(device_path)
    ft = fstype.lower().strip()
    if ft == "fat32":
        cmd = ["mkfs.vfat", "-F", "32", device_path]
    elif ft == "ntfs":
        cmd = ["mkfs.ntfs", "-F", device_path]
    elif ft == "ext4":
        cmd = ["mkfs.ext4", "-F", device_path]
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported file system")
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=600)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Formatting tool not found (install dosfstools / ntfs-3g / e2fsprogs as needed).",
        ) from exc
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or exc.stdout or "").strip() or str(exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Format failed: {err[:500]}",
        ) from exc
