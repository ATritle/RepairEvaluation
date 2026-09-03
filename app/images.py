"""Photo normalisation - ported from the desktop optimize_uploaded_image()."""
import io
import uuid
from pathlib import Path

from PIL import Image as PILImage
from PIL import ImageOps

from .config import PHOTOS_DIR

MAX_EDGE = 2000
JPEG_QUALITY = 82


def optimize_uploaded_bytes(raw: bytes) -> str:
    """
    Apply EXIF orientation, flatten alpha onto white, limit the longest edge
    to 2000px and store as optimised progressive JPEG (quality 82).
    Returns the stored filename inside PHOTOS_DIR.
    """
    PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.jpg"
    output = PHOTOS_DIR / filename

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

        im.save(output, format="JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)

    return filename


def photo_path(filename: str) -> Path:
    """Resolve a stored photo filename, refusing path traversal."""
    safe = Path(filename).name
    return PHOTOS_DIR / safe
