from pathlib import Path

APP_NAME = "IFP Repair Evaluation"
APP_VERSION = "2.0.0-web"

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
STATIC = ROOT / "static"
DATA = ROOT / "data"
THUMBS_DIR = DATA / "thumbs"   # generated thumbnails for the library grid

APP_LOGO = ASSETS / "ifp_logo_app.png"
PDF_LOGO = ASSETS / "ifp_logo.png"

TECHNICIANS = [
    "S. HAMILTON",
    "M. DONLEY",
    "A. KRON",
    "P. THOMANN",
    "A. TRITLE",
]

SYMBOLS = [
    {"label": "Arrow ↑", "value": "arrow_up"},
    {"label": "Arrow →", "value": "arrow_right"},
    {"label": "Arrow ↓", "value": "arrow_down"},
    {"label": "Arrow ←", "value": "arrow_left"},
    {"label": "Circle", "value": "circle"},
    {"label": "Square", "value": "square"},
    {"label": "Rectangle", "value": "rectangle"},
    {"label": "X", "value": "x"},
    {"label": "Check Mark", "value": "check"},
]

# Markup colours offered in the Colour drop-down (hex, lower-case).
COLORS = [
    {"label": "Red", "value": "#ff0000"},
    {"label": "Orange", "value": "#ff7a00"},
    {"label": "Yellow", "value": "#ffd400"},
    {"label": "Green", "value": "#00c800"},
    {"label": "Blue", "value": "#0066ff"},
    {"label": "Cyan", "value": "#00d5ff"},
    {"label": "Magenta", "value": "#ff00c8"},
    {"label": "Purple", "value": "#8a2be2"},
    {"label": "White", "value": "#ffffff"},
    {"label": "Black", "value": "#000000"},
]

ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".heic", ".heif", ".tif", ".tiff", ".gif"}


def ensure_dirs() -> None:
    THUMBS_DIR.mkdir(parents=True, exist_ok=True)
