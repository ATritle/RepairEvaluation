r"""Where photo bytes live.

Metadata for every photo is always a row in Forge.RepairEval.photo_file. The
bytes go to one of two backends, chosen per file by the row's `storage` column
so old and new files coexist:

  db  - VARBINARY in the photo_file row
  fs  - a file in the repair's drawing folder on the N drive:

            <PHOTO_FS_ROOT>\R36000\R36169\Photos\<file_name>.jpg
             (root = \\eha-serv.ifp.eha\data\Dwgs)

        The series folder (R-number rounded down to the thousand) and the
        numbered folder must already exist - they are created by the drawing /
        job process, not by this app. The Photos sub-folder is created on demand.
        The row's `path` is relative to the root; an absolute path is also
        honoured (used for photos migrated from an earlier layout).

New uploads use settings.photo_store. Reads follow the row.
"""
import asyncio
import re
from pathlib import Path
from typing import Optional

from . import forge
from .config import ROOT
from .images import cache_photo, photo_path
from .settings import get_settings

PHOTOS_SUBFOLDER = "Photos"
_R_NUMBER = re.compile(r"^R(\d{4,7})$", re.IGNORECASE)


class PhotoLocationError(Exception):
    """The repair's drawing folder is missing or the repair number is not an R-number."""


def fs_root() -> Path:
    root = Path(get_settings().photo_fs_root)
    if not root.is_absolute():
        root = ROOT / root
    return root


def repair_folder_rel(repair_no: str) -> tuple[str, str]:
    """('R36000', 'R36169') for 'R36169'. Raises PhotoLocationError for non R-numbers."""
    m = _R_NUMBER.match((repair_no or "").strip())
    if not m:
        raise PhotoLocationError(
            f"Photos can only be filed for R-number repairs (e.g. R36169); '{repair_no}' is not one."
        )
    n = int(m.group(1))
    series = f"R{(n // 1000) * 1000}"
    return series, f"R{m.group(1)}"


def _resolve_photos_dir_sync(repair_no: str, create: bool) -> Path:
    """Full path of <root>\\R36000\\R36169\\Photos, checking the parents exist."""
    series, number = repair_folder_rel(repair_no)
    root = fs_root()
    if not root.exists():
        raise PhotoLocationError(f"Photo root is not reachable: {root}")
    series_dir = root / series
    if not series_dir.is_dir():
        raise PhotoLocationError(f"Drawing series folder {series} does not exist under {root}")
    number_dir = series_dir / number
    if not number_dir.is_dir():
        raise PhotoLocationError(f"No drawing folder for {number} under {series_dir}. Create the job folder first.")
    photos_dir = number_dir / PHOTOS_SUBFOLDER
    if create:
        photos_dir.mkdir(exist_ok=True)
    return photos_dir


def _fs_write(target: Path, content: bytes) -> Path:
    tmp = target.with_suffix(target.suffix + ".part")
    tmp.write_bytes(content)
    tmp.replace(target)          # never expose a half-written file
    return target


def _fs_path(rel_or_abs: str) -> Path:
    p = Path(rel_or_abs)
    return p if p.is_absolute() else fs_root() / p


def _fs_read(rel_or_abs: str) -> Optional[bytes]:
    p = _fs_path(rel_or_abs)
    return p.read_bytes() if p.exists() else None


async def photos_dir_for(repair_no: str) -> Path:
    """Where photos for this repair go (checks the folders exist; does not create)."""
    return await asyncio.to_thread(_resolve_photos_dir_sync, repair_no, False)


async def put(file_name: str, original_name: str, content: bytes, width: int, height: int,
              uploaded_by: Optional[str], repair_no: str) -> None:
    """Store bytes according to settings.photo_store and record the metadata row."""
    mode = get_settings().photo_store
    if mode == "fs":
        photos_dir = await asyncio.to_thread(_resolve_photos_dir_sync, repair_no, True)
        target = photos_dir / Path(file_name).name
        await asyncio.to_thread(_fs_write, target, content)
        rel = str(target.relative_to(fs_root())).replace("\\", "/")
        await forge.photo_put(file_name, original_name, None, width, height, uploaded_by,
                              storage="fs", path=rel, byte_size=len(content), sha_source=content)
    else:
        await forge.photo_put(file_name, original_name, content, width, height, uploaded_by,
                              storage="db", path=None, byte_size=len(content), sha_source=content)
    cache_photo(file_name, content)


async def get(file_name: str) -> Optional[bytes]:
    """Bytes for a stored photo, wherever the row says they are."""
    row = await forge.photo_locate(file_name)
    if row is None:
        return None
    if row["storage"] == "fs" and row.get("path"):
        return await asyncio.to_thread(_fs_read, row["path"])
    return row.get("content")


async def ensure_cached(file_name: str) -> Optional[Path]:
    """Make sure the local cache (used by the PDF builder and /photos) has the file."""
    p = photo_path(file_name)
    if p.exists():
        return p
    content = await get(file_name)
    if content is None:
        return None
    return cache_photo(file_name, content)


async def exists(file_name: str) -> bool:
    if photo_path(file_name).exists():
        return True
    return await forge.photo_exists(file_name)
