r"""Photos live in the repair's drawing folder on the N drive. The folder is the truth.

    <Dwgs>\R36000\R36169\Photos\                     live library: anything anyone puts here
    <Dwgs>\R36000\R36169\Photos\.archive\<sha>.jpg   frozen, normalised snapshots behind saved revisions
    <Dwgs>\R36000\R36169\Photos\.removed\            where "remove from library" moves a file (recoverable)
    <Dwgs>\R36000\R36169\Reports\R36169 rev3.pdf     the PDF written on every save

A photo on a report is referenced as either
    live:<file name>      a file in the live folder (before the report is saved)
    archive:<sha256>      a snapshot (after save; immutable)
and served from /repairs/{repair_no}/photos/{name} or /repairs/{repair_no}/archive/{sha}.

The series folder (R-number rounded down to the thousand) and the job folder
must already exist; only Photos, .archive, .removed and Reports are created here.
"""
from __future__ import annotations

import asyncio
import hashlib
import re
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import ROOT, THUMBS_DIR
from .images import normalize_image_bytes, thumbnail_bytes
from .settings import get_settings

PHOTOS_SUBFOLDER = "Photos"
ARCHIVE_SUBFOLDER = ".archive"
REMOVED_SUBFOLDER = ".removed"
REPORTS_SUBFOLDER = "Reports"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".heic", ".heif", ".tif", ".tiff", ".gif"}

_R_NUMBER = re.compile(r"^R(\d{4,7})$", re.IGNORECASE)
_SAFE_NAME = re.compile(r"^[^\\/:*?\"<>|\x00-\x1f]{1,200}$")   # a single Windows file name
_SHA = re.compile(r"^[0-9a-f]{64}$")
REF_RE = re.compile(r"^(live:(?P<name>[^\\/:*?\"<>|\x00-\x1f]{1,200})|archive:(?P<sha>[0-9a-f]{64}))$")


class PhotoLocationError(Exception):
    """Repair number is not an R-number, or its drawing folder is missing."""


class PhotoNotFound(Exception):
    pass


# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
def fs_root() -> Path:
    root = Path(get_settings().photo_fs_root)
    return root if root.is_absolute() else ROOT / root


def series_and_number(repair_no: str) -> tuple[str, str]:
    m = _R_NUMBER.match((repair_no or "").strip())
    if not m:
        raise PhotoLocationError(
            f"Photos can only be filed for R-number repairs (e.g. R36169); '{repair_no}' is not one."
        )
    n = int(m.group(1))
    return f"R{(n // 1000) * 1000}", f"R{m.group(1)}"


def job_folder(repair_no: str) -> Path:
    """<root>\\R36000\\R36169 - must exist."""
    series, number = series_and_number(repair_no)
    root = fs_root()
    if not root.exists():
        raise PhotoLocationError(f"Photo root is not reachable: {root}")
    if not (root / series).is_dir():
        raise PhotoLocationError(f"Drawing series folder {series} does not exist under {root}")
    job = root / series / number
    if not job.is_dir():
        raise PhotoLocationError(f"No drawing folder for {number} under {root / series}. Create the job folder first.")
    return job


def photos_dir(repair_no: str, create: bool = False) -> Path:
    d = job_folder(repair_no) / PHOTOS_SUBFOLDER
    if create:
        d.mkdir(exist_ok=True)
    return d


def _sub(repair_no: str, name: str, create: bool) -> Path:
    d = photos_dir(repair_no, create=create) / name
    if create:
        d.mkdir(exist_ok=True)
    return d


def check_name(name: str) -> str:
    name = (name or "").strip()
    if not _SAFE_NAME.match(name) or name.startswith(".") or name in (".", ".."):
        raise PhotoNotFound("Invalid photo name")
    return name


def live_path(repair_no: str, name: str) -> Path:
    p = photos_dir(repair_no) / check_name(name)
    if not p.is_file():
        raise PhotoNotFound(f"{name} is not in the Photos folder for {repair_no}")
    return p


def archive_file(repair_no: str, sha: str, create_dir: bool = False) -> Path:
    if not _SHA.match(sha or ""):
        raise PhotoNotFound("Invalid snapshot reference")
    return _sub(repair_no, ARCHIVE_SUBFOLDER, create_dir) / f"{sha}.jpg"


def resolve_ref(repair_no: str, ref: str) -> Path:
    """Local/UNC path for a 'live:<name>' or 'archive:<sha>' reference."""
    m = REF_RE.match(ref or "")
    if not m:
        raise PhotoNotFound("Invalid photo reference")
    if m.group("name"):
        return live_path(repair_no, m.group("name"))
    p = archive_file(repair_no, m.group("sha"))
    if not p.is_file():
        raise PhotoNotFound("Snapshot is missing from the archive")
    return p


def rel_to_root(p: Path) -> str:
    return str(p.relative_to(fs_root())).replace("\\", "/")


# --------------------------------------------------------------------------
# Library listing (with a small hash cache so 20 MB originals hash once)
# --------------------------------------------------------------------------
@dataclass
class LibraryItem:
    name: str
    size: int
    modified: str
    sha256: Optional[str]      # hash of the *normalised* image = the archive key it would get
    width: Optional[int]
    height: Optional[int]


_hash_cache: dict[tuple[str, int, int], tuple[str, int, int]] = {}   # (path, mtime_ns, size) -> (sha, w, h)


def _normalised_identity(p: Path) -> tuple[str, int, int]:
    """sha256 + dimensions of the normalised JPEG for a live file, cached on (path, mtime, size)."""
    st = p.stat()
    key = (str(p), st.st_mtime_ns, st.st_size)
    hit = _hash_cache.get(key)
    if hit:
        return hit
    jpeg, w, h = normalize_image_bytes(p.read_bytes())
    val = (hashlib.sha256(jpeg).hexdigest(), w, h)
    if len(_hash_cache) > 5000:
        _hash_cache.clear()
    _hash_cache[key] = val
    return val


def _list_sync(repair_no: str, with_hash: bool) -> list[LibraryItem]:
    d = photos_dir(repair_no)
    if not d.is_dir():
        return []
    items: list[LibraryItem] = []
    for p in sorted(d.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if not p.is_file() or p.name.startswith(".") or p.suffix.lower() not in IMAGE_EXTS:
            continue
        st = p.stat()
        sha = w = h = None
        if with_hash:
            try:
                sha, w, h = _normalised_identity(p)
            except Exception:
                pass   # unreadable image: still list it, just without a hash
        items.append(LibraryItem(p.name, st.st_size, datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"), sha, w, h))
    return items


# --------------------------------------------------------------------------
# Writes
# --------------------------------------------------------------------------
def _unique_name(d: Path, stem: str, ext: str) -> Path:
    cand = d / f"{stem}{ext}"
    n = 2
    while cand.exists():
        cand = d / f"{stem} ({n}){ext}"
        n += 1
    return cand


def _upload_stem(original_name: str) -> str:
    """<yyyymmdd-HHMMSS>_<original stem>: sortable in Explorer and readable.
    Generic camera names (image.jpg, IMG_0001) keep only the timestamp."""
    stem = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "_", Path(original_name or "").stem).strip(" ._") or "photo"
    stem = stem[:60]
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    if re.fullmatch(r"(image|img|photo|dsc|pxl)[_\-]?\d*", stem, re.IGNORECASE):
        return ts
    return f"{ts}_{stem}"


def _save_upload_sync(repair_no: str, original_name: str, raw: bytes) -> tuple[str, int, int]:
    """Normalise and write an upload into the live folder. Returns (name, w, h)."""
    d = photos_dir(repair_no, create=True)
    jpeg, w, h = normalize_image_bytes(raw)
    target = _unique_name(d, _upload_stem(original_name), ".jpg")
    tmp = target.with_suffix(".jpg.part")
    tmp.write_bytes(jpeg)
    tmp.replace(target)
    return target.name, w, h


def _archive_live_sync(repair_no: str, name: str) -> tuple[str, str]:
    """Freeze a live photo for a saved revision: normalised copy keyed by content
    hash. Returns (sha, archive_path relative to root). Idempotent."""
    src = live_path(repair_no, name)
    sha, _w, _h = _normalised_identity(src)
    target = archive_file(repair_no, sha, create_dir=True)
    if not target.exists():
        jpeg, _, _ = normalize_image_bytes(src.read_bytes())
        tmp = target.with_suffix(".jpg.part")
        tmp.write_bytes(jpeg)
        tmp.replace(target)
    return sha, rel_to_root(target)


def _remove_live_sync(repair_no: str, name: str) -> None:
    """'Remove from library' = move into .removed (never delete someone's file)."""
    src = live_path(repair_no, name)
    dest_dir = _sub(repair_no, REMOVED_SUBFOLDER, create=True)
    shutil.move(str(src), str(_unique_name(dest_dir, src.stem, src.suffix)))


def _reports_dir_sync(repair_no: str) -> Path:
    d = job_folder(repair_no) / REPORTS_SUBFOLDER
    d.mkdir(exist_ok=True)
    return d


# --------------------------------------------------------------------------
# Thumbnails (cached locally by content identity or by path+mtime)
# --------------------------------------------------------------------------
def _thumb_sync(p: Path) -> Path:
    THUMBS_DIR.mkdir(parents=True, exist_ok=True)
    st = p.stat()
    key = hashlib.sha1(f"{p}|{st.st_mtime_ns}|{st.st_size}".encode()).hexdigest()
    out = THUMBS_DIR / f"{key}.jpg"
    if not out.exists():
        tmp = out.with_suffix(".part")
        tmp.write_bytes(thumbnail_bytes(p.read_bytes()))
        tmp.replace(out)
    return out


# --------------------------------------------------------------------------
# async facade
# --------------------------------------------------------------------------
async def list_library(repair_no: str, with_hash: bool = True) -> list[LibraryItem]:
    return await asyncio.to_thread(_list_sync, repair_no, with_hash)


async def save_upload(repair_no: str, original_name: str, raw: bytes) -> tuple[str, int, int]:
    return await asyncio.to_thread(_save_upload_sync, repair_no, original_name, raw)


async def archive_live(repair_no: str, name: str) -> tuple[str, str]:
    return await asyncio.to_thread(_archive_live_sync, repair_no, name)


async def remove_live(repair_no: str, name: str) -> None:
    await asyncio.to_thread(_remove_live_sync, repair_no, name)


async def path_for_ref(repair_no: str, ref: str) -> Path:
    return await asyncio.to_thread(resolve_ref, repair_no, ref)


async def thumb_for(p: Path) -> Path:
    return await asyncio.to_thread(_thumb_sync, p)


async def photos_dir_checked(repair_no: str) -> Path:
    return await asyncio.to_thread(photos_dir, repair_no, False)


async def reports_dir(repair_no: str) -> Path:
    return await asyncio.to_thread(_reports_dir_sync, repair_no)
