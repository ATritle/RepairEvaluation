from pathlib import Path

APP_NAME = "IFP Repair Evaluation"
APP_VERSION = "2.0.0-web"

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
STATIC = ROOT / "static"
DATA = ROOT / "data"
PHOTOS_DIR = DATA / "photos"   # local cache of Forge photo bytes
THUMBS_DIR = DATA / "thumbs"   # generated thumbnails for the library grid
REPORTS_DIR = DATA / "reports"  # legacy JSON store (pre-Forge); no longer written

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

ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def ensure_dirs() -> None:
    PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    THUMBS_DIR.mkdir(parents=True, exist_ok=True)
