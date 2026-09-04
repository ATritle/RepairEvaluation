"""Where photo bytes live.

Metadata for every photo is always a row in Forge.RepairEval.photo_file. The
bytes go to one of two backends, chosen per file by the row's `storage` column
so old and new files coexist:

  db  - VARBINARY in the photo_file row (the original behaviour)
  fs  - a file under PHOTO_FS_ROOT at <yyyy>/<mm>/<file_name>. Today that root
        is a local folder; pointing it at a UNC share later needs no code change.

New uploads use settings.photo_store. Reads follow the row.
"""
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import forge
from .config import ROOT
from .images import cache_photo, photo_path
from .settings import get_settings


def fs_root() -> Path:
    root = Path(get_settings().photo_fs_root)
    if not root.is_absolute():
        root = ROOT / root
    return root


def _relative_path(file_name: str) -> str:
    now = datetime.now()
    return f"{now:%Y}/{now:%m}/{Path(file_name).name}"


def _fs_write(rel: str, content: bytes) -> Path:
    target = fs_root() / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".part")
    tmp.write_bytes(content)
    tmp.replace(target)          # never expose a half-written file
    return target


def _fs_read(rel: str) -> Optional[bytes]:
    p = fs_root() / rel
    return p.read_bytes() if p.exists() else None


async def put(file_name: str, original_name: str, content: bytes, width: int, height: int,
              uploaded_by: Optional[str]) -> None:
    """Store bytes according to settings.photo_store and record the metadata row."""
    mode = get_settings().photo_store
    if mode == "fs":
        rel = _relative_path(file_name)
        await asyncio.to_thread(_fs_write, rel, content)
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
