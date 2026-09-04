"""Photo normalisation and the local disk cache for photo bytes stored in Forge."""
import io
import uuid
from pathlib import Path

from PIL import Image as PILImage
from PIL import ImageOps

from .config import PHOTOS_DIR

MAX_EDGE = 2000
JPEG_QUALITY = 82


def optimize_uploaded_bytes(raw: bytes) -> tuple[str, bytes, int, int]:
    """
    Apply EXIF orientation, flatten alpha onto white, limit the longest edge
    to 2000px and encode as optimised progressive JPEG (quality 82).
    Returns (file_name, jpeg_bytes, width, height). Nothing is written to disk.
    """
    filename = f"{uuid.uuid4().hex}.jpg"

    with PILImage.open(io.BytesIO(raw)) as im:
        try:
            im = ImageOps.exif_transpose(im)
        except Exception:
            pass

        if im.mode in ("RGBA", "LA"):
            bg = PILImage.new("RGB", im.size, "white")
            bg.paste(im, mask=im.getchannel("A"))
            im = bg
        elif im.mode != "RGB":
            im = im.convert("RGB")

        longest = max(im.width, im.height)
        if longest > MAX_EDGE:
            scale = MAX_EDGE / longest
            im = im.resize(
                (max(1, int(im.width * scale)), max(1, int(im.height * scale))),
                PILImage.Resampling.LANCZOS,
            )

        out = io.BytesIO()
        im.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
        return filename, out.getvalue(), im.width, im.height


def photo_path(filename: str) -> Path:
    """Local cache location for a stored photo (may not exist yet)."""
    return PHOTOS_DIR / Path(filename).name


def cache_photo(filename: str, content: bytes) -> Path:
    PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    p = photo_path(filename)
    tmp = p.with_suffix(".part")
    tmp.write_bytes(content)
    tmp.replace(p)
    return p
