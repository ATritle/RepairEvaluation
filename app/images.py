"""Image normalisation. Everything the app writes is a JPEG with EXIF rotation
applied, alpha flattened, longest edge <= 2000 px, quality 82. HEIC/HEIF from
phones is decoded via pillow-heif when present."""
import io

from PIL import Image as PILImage
from PIL import ImageOps

try:  # iPhone HEIC support; optional
    import pillow_heif

    pillow_heif.register_heif_opener()
except Exception:  # pragma: no cover
    pass

MAX_EDGE = 2000
JPEG_QUALITY = 82
THUMB_EDGE = 360
PDF_EDGE = 1600   # embedded report images never need more than this


def _flatten(im: PILImage.Image) -> PILImage.Image:
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        bg = PILImage.new("RGB", im.size, "white")
        bg.paste(im, mask=im.getchannel("A"))
        return bg
    return im if im.mode == "RGB" else im.convert("RGB")


def normalize_image_bytes(raw: bytes, max_edge: int = MAX_EDGE, quality: int = JPEG_QUALITY) -> tuple[bytes, int, int]:
    """Return (jpeg_bytes, width, height). Deterministic for the same input, so
    the hash of the result is a stable identity for a photo."""
    with PILImage.open(io.BytesIO(raw)) as im:
        try:
            im = ImageOps.exif_transpose(im)
        except Exception:
            pass
        im = _flatten(im)
        longest = max(im.width, im.height)
        if longest > max_edge:
            scale = max_edge / longest
            im = im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))), PILImage.Resampling.LANCZOS)
        out = io.BytesIO()
        im.save(out, format="JPEG", quality=quality, optimize=True, progressive=True)
        return out.getvalue(), im.width, im.height


def thumbnail_bytes(raw: bytes, edge: int = THUMB_EDGE) -> bytes:
    with PILImage.open(io.BytesIO(raw)) as im:
        try:
            im = ImageOps.exif_transpose(im)
        except Exception:
            pass
        im = _flatten(im)
        im.thumbnail((edge, edge), PILImage.Resampling.LANCZOS)
        out = io.BytesIO()
        im.save(out, format="JPEG", quality=78, optimize=True)
        return out.getvalue()
