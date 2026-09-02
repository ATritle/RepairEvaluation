import json
import os
import shutil
import sys
import tempfile
import uuid
from datetime import date
from pathlib import Path

from PIL import Image as PILImage

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QPixmap, QImageReader, QIcon, QPainter, QPen, QBrush, QTransform
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QDialog,
    QLabel,
    QPushButton,
    QLineEdit,
    QTextEdit,
    QTextBrowser,
    QComboBox,
    QDateEdit,
    QFileDialog,
    QMessageBox,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QFormLayout,
    QScrollArea,
    QSlider,
    QSpinBox,
    QTabWidget,
    QFrame,
    QSizePolicy,
)

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage,
    PageBreak, KeepTogether
)
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics


APP_NAME = "IFP Repair Evaluation"
ORANGE = "#ff7a00"
DARK = "#171717"
PANEL = "#222222"
FIELD = "#2c2c2c"
BORDER = "#4a4a4a"
TEXT = "#f2f2f2"
MUTED = "#b8b8b8"
SECTION = "#6d8fa0"
CYAN = "#8be9f5"


def app_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


ASSETS = app_dir() / "assets"
APP_LOGO = ASSETS / "ifp_logo_app.png"
PDF_LOGO = ASSETS / "ifp_logo.png"


def safe_copy_image(src, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)


def image_size(path, max_w, max_h):
    try:
        with PILImage.open(path) as im:
            w, h = im.size
        if not w or not h:
            return max_w, max_h
        scale = min(max_w / w, max_h / h)
        return w * scale, h * scale
    except Exception:
        return max_w, max_h


def optimize_uploaded_image(source_path):
    """
    Normalize and compress an uploaded repair photo for use by the app.

    Camera EXIF orientation is applied first, then the image is limited to
    a maximum 2000-pixel longest edge and saved as optimized JPEG quality 82.
    """
    source = Path(source_path)
    temp_root = Path(tempfile.gettempdir()) / "IFP_Repair_Evaluation"
    temp_root.mkdir(parents=True, exist_ok=True)
    output = temp_root / f"{uuid.uuid4().hex}.jpg"

    with PILImage.open(source) as im:
        try:
            from PIL import ImageOps
            im = ImageOps.exif_transpose(im)
        except Exception:
            pass

        if im.mode in ("RGBA", "LA"):
            bg = PILImage.new("RGB", im.size, "white")
            alpha = im.getchannel("A")
            bg.paste(im, mask=alpha)
            im = bg
        elif im.mode != "RGB":
            im = im.convert("RGB")

        max_edge = 2000
        longest = max(im.width, im.height)
        if longest > max_edge:
            scale = max_edge / longest
            im = im.resize(
                (max(1, int(im.width * scale)),
                 max(1, int(im.height * scale))),
                PILImage.Resampling.LANCZOS
            )

        im.save(
            output,
            format="JPEG",
            quality=82,
            optimize=True,
            progressive=True
        )

    return output


class HelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("IFP Repair Evaluation - Help")
        self.resize(820, 680)

        layout = QVBoxLayout(self)
        header = QHBoxLayout()

        if APP_LOGO.exists():
            logo = QLabel()
            pix = QPixmap(str(APP_LOGO))
            if not pix.isNull():
                logo.setPixmap(
                    pix.scaled(180, 70, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
                )
            header.addWidget(logo)

        title = QLabel("IFP Repair Evaluation")
        title.setStyleSheet("font-size:24px; font-weight:bold;")
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)

        tabs = QTabWidget()

        how = QTextBrowser()
        how.setOpenExternalLinks(False)
        how.setHtml("""
        <h2>How to Use</h2>
        <p>Use this application to document a repair evaluation and produce a
        professional PDF report.</p>

        <h3>1. Enter Repair Information</h3>
        <ul>
          <li>Enter the <b>Repair #</b> manually.</li>
          <li>Enter the date, customer, contact, customer PO,
              customer part number, make/model, serial number and technician.</li>
        </ul>

        <h3>2. Document the Evaluation</h3>
        <ul>
          <li><b>Customer Request / Reported Problem</b> — describe what the
              customer reported or requested.</li>
          <li><b>Repair Evaluation / Findings</b> — document inspection results,
              measurements, damage and other findings.</li>
        </ul>

        <h3>3. Add Photos</h3>
        <p>Use <b>Add Photos</b> to attach inspection photographs. Each photo
        can have its own description and can be rotated.</p>

        <h3>4. Mark Up Photos</h3>
        <p>Select a symbol from <b>Add Symbol</b>, then click on the photo where
        the symbol should be placed. Symbols are included in the PDF.</p>

        <h3>5. Preview and Export</h3>
        <p>Use <b>PDF Preview</b> to review the report. Use the PDF export
        controls to save the finished report.</p>

        <h3>6. Save Your Evaluation</h3>
        <p>Save the evaluation file if you want to reopen or modify the report
        later.</p>
        """)
        tabs.addTab(how, "How to Use")

        markup = QTextBrowser()
        markup.setHtml("""
        <h2>Photo Markup Guide</h2>
        <h3>Place a Symbol</h3>
        <p>Choose a symbol from <b>Add Symbol</b>, then click anywhere on the
        image. The symbol is placed at that location.</p>

        <h3>Resize a Symbol</h3>
        <p>Click an existing symbol to select it. Use the <b>Size</b> control
        to change its size. The selected symbol is highlighted.</p>

        <h3>Move a Symbol</h3>
        <p>Click and drag an existing symbol to move it. This is useful for
        repositioning an arrow or shape after placing it.</p>

        <h3>Remove a Symbol</h3>
        <p>Select a symbol and press <b>Delete</b>, or use the photo's
        markup controls to clear its markups.</p>

        <h3>Zoom</h3>
        <p>Use the photo zoom control to enlarge the image while positioning
        markups. Zooming changes the view only; it does not change the
        underlying photograph.</p>

        <h3>Available Symbols</h3>
        <ul>
          <li>Arrow Up / Right / Down / Left</li>
          <li>Circle</li>
          <li>Square</li>
          <li>Rectangle</li>
          <li>X</li>
          <li>Check Mark</li>
        </ul>

        <p><b>Tip:</b> Place the point of an arrow directly on the area you
        want the report reader to notice.</p>
        """)
        tabs.addTab(markup, "Photo Markup")

        shortcuts = QTextBrowser()
        shortcuts.setHtml("""
        <h2>Keyboard Shortcuts</h2>
        <table cellspacing="8">
          <tr><td><b>Ctrl + N</b></td><td>New evaluation</td></tr>
          <tr><td><b>Ctrl + O</b></td><td>Open evaluation</td></tr>
          <tr><td><b>Ctrl + S</b></td><td>Save evaluation</td></tr>
          <tr><td><b>Ctrl + P</b></td><td>PDF Preview / export workflow</td></tr>
          <tr><td><b>Delete</b></td><td>Remove a selected photo markup</td></tr>
          <tr><td><b>Esc</b></td><td>Deselect a selected markup</td></tr>
        </table>
        """)
        tabs.addTab(shortcuts, "Keyboard Shortcuts")

        about = QWidget()
        about_layout = QVBoxLayout(about)
        about_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        if APP_LOGO.exists():
            logo2 = QLabel()
            pix2 = QPixmap(str(APP_LOGO))
            if not pix2.isNull():
                logo2.setPixmap(
                    pix2.scaled(300, 110, Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation)
                )
            about_layout.addWidget(logo2, alignment=Qt.AlignmentFlag.AlignCenter)

        a = QLabel(
            "<h1>IFP Repair Evaluation</h1>"
            "<p><b>IFP Motion Solutions</b></p>"
            "<p>Repair evaluation and photographic documentation tool</p>"
            "<p>Version 1.0.0</p>"
        )
        a.setAlignment(Qt.AlignmentFlag.AlignCenter)
        a.setTextFormat(Qt.TextFormat.RichText)
        about_layout.addWidget(a)
        about_layout.addStretch()
        tabs.addTab(about, "About")

        layout.addWidget(tabs)

        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        layout.addWidget(close, alignment=Qt.AlignmentFlag.AlignRight)


class ZoomDialog(QDialog):
    """Full-size photo viewer with zoom and markup positioning."""
    def __init__(self, photo_data, parent=None):
        super().__init__(parent)
        self.photo_data = photo_data
        self.setWindowTitle("Photo Zoom / Markup")
        self.resize(1100, 800)

        layout = QVBoxLayout(self)

        self.canvas = PhotoCanvas(
            self.photo_data,
            self.on_changed,
            self
        )
        self.canvas.setMinimumSize(700, 600)
        layout.addWidget(self.canvas, 1)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Zoom:"))
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(25, 300)
        self.zoom_slider.setValue(100)
        self.zoom_slider.valueChanged.connect(self.update_zoom)
        controls.addWidget(self.zoom_slider)

        self.zoom_label = QLabel("100%")
        self.zoom_label.setFixedWidth(55)
        controls.addWidget(self.zoom_label)

        reset = QPushButton("Reset Zoom")
        reset.clicked.connect(lambda: self.zoom_slider.setValue(100))
        controls.addWidget(reset)

        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        controls.addWidget(close)

        layout.addLayout(controls)
        self.refresh()

    def refresh(self):
        pix = QPixmap(self.photo_data["path"])
        if not pix.isNull():
            rotation = self.photo_data.get("rotation", 0)
            if rotation:
                pix = pix.transformed(QTransform().rotate(rotation))
            self.canvas.set_image(pix)

    def update_zoom(self, value):
        self.zoom_label.setText(f"{value}%")
        self.canvas.zoom_factor = value / 100.0
        self.canvas.update()

    def on_changed(self):
        # ZoomDialog is owned by PhotoCard, not the main window.
        # Pass the change notification through the PhotoCard callback.
        if self.parent() and hasattr(self.parent(), "markup_changed"):
            self.parent().markup_changed()




class PhotoCanvas(QLabel):
    """Image canvas that places a selected symbol wherever the user clicks."""

    SYMBOLS = [
        ("Arrow ↑", "arrow_up"),
        ("Arrow →", "arrow_right"),
        ("Arrow ↓", "arrow_down"),
        ("Arrow ←", "arrow_left"),
        ("Circle", "circle"),
        ("Square", "square"),
        ("Rectangle", "rectangle"),
        ("X", "x"),
        ("Check Mark", "check"),
    ]

    def __init__(self, data, changed_callback, parent=None):
        super().__init__(parent)
        self.data = data
        self.changed_callback = changed_callback
        self.selected_symbol = "arrow_up"
        self.symbol_size = 250
        self.zoom_factor = 1.0
        self.selected_annotation = None
        self.base_pixmap = QPixmap()
        self.display_rect = None
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(280, 210)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setStyleSheet(
            "background:#111; border:1px solid #555; border-radius:6px;"
        )
        self.setMouseTracking(True)

    def set_symbol(self, symbol):
        self.selected_symbol = symbol

    def set_image(self, pixmap):
        self.base_pixmap = pixmap
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self.base_pixmap.isNull():
            return

        scaled = self.base_pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        x = (self.width() - scaled.width()) / 2
        y = (self.height() - scaled.height()) / 2
        rect = scaled.rect().translated(int(x), int(y))

        if not rect.contains(event.position().toPoint()):
            return

        click_x = event.position().x()
        click_y = event.position().y()

        # First try to select an existing symbol near the click.
        nearest = None
        nearest_distance = float("inf")
        base = min(scaled.width(), scaled.height())
        for i, annotation in enumerate(self.data.get("annotations", [])):
            ax = x + annotation.get("x", 0.5) * scaled.width()
            ay = y + annotation.get("y", 0.5) * scaled.height()
            symbol_scale = max(0.35, annotation.get("size", 100) / 100.0)
            hit_radius = max(16.0, base * 0.065 * symbol_scale)
            distance = ((click_x - ax) ** 2 + (click_y - ay) ** 2) ** 0.5
            if distance <= hit_radius and distance < nearest_distance:
                nearest = i
                nearest_distance = distance

        if nearest is not None:
            self.selected_annotation = nearest
            self._dragging = True
            self.changed_callback()
            self.update()
            return

        # Otherwise place a new symbol at the click location.
        nx = (click_x - rect.x()) / max(1, rect.width())
        ny = (click_y - rect.y()) / max(1, rect.height())

        self.data.setdefault("annotations", []).append({
            "symbol": self.selected_symbol,
            "x": max(0.0, min(1.0, nx)),
            "y": max(0.0, min(1.0, ny)),
            "size": self.symbol_size,
        })
        self.selected_annotation = len(self.data["annotations"]) - 1
        self.changed_callback()
        self.update()

    def mouseMoveEvent(self, event):
        if getattr(self, "_dragging", False) and self.selected_annotation is not None:
            annotations = self.data.get("annotations", [])
            if 0 <= self.selected_annotation < len(annotations):
                if self.display_rect and self.display_rect.contains(event.position().toPoint()):
                    rect = self.display_rect
                    annotations[self.selected_annotation]["x"] = max(
                        0.0, min(1.0, (event.position().x() - rect.x()) / max(1, rect.width()))
                    )
                    annotations[self.selected_annotation]["y"] = max(
                        0.0, min(1.0, (event.position().y() - rect.y()) / max(1, rect.height()))
                    )
                    self.changed_callback()
                    self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Delete and self.selected_annotation is not None:
            annotations = self.data.get("annotations", [])
            if 0 <= self.selected_annotation < len(annotations):
                annotations.pop(self.selected_annotation)
            self.selected_annotation = None
            self.changed_callback()
            self.update()
            return
        if event.key() == Qt.Key.Key_Escape:
            self.selected_annotation = None
            self.update()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        if self.base_pixmap.isNull():
            painter.setPen(QPen(Qt.GlobalColor.white))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Unable to load image")
            painter.end()
            return

        target_w = max(1, int(self.width() * getattr(self, "zoom_factor", 1.0)))
        target_h = max(1, int(self.height() * getattr(self, "zoom_factor", 1.0)))
        scaled = self.base_pixmap.scaled(
            target_w, target_h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        x = (self.width() - scaled.width()) // 2
        y = (self.height() - scaled.height()) // 2
        self.display_rect = scaled.rect().translated(x, y)
        painter.drawPixmap(x, y, scaled)

        # Draw markup in display coordinates.
        for i, annotation in enumerate(self.data.get("annotations", [])):
            px = x + annotation["x"] * scaled.width()
            py = y + annotation["y"] * scaled.height()
            selected = (i == self.selected_annotation)
            self.draw_symbol(
                painter,
                annotation["symbol"],
                px,
                py,
                min(scaled.width(), scaled.height()),
                annotation.get("size", 100),
                selected
            )
        painter.end()

    @staticmethod
    def draw_symbol(painter, symbol, x, y, base, symbol_size=100, selected=False):
        size = max(18.0, min(70.0, base * 0.10)) * max(0.25, symbol_size / 100.0)
        line_width = max(2.0, size * 0.065)
        pen = QPen(
            Qt.GlobalColor.yellow if selected else Qt.GlobalColor.red,
            line_width + (1.5 if selected else 0)
        )
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        if symbol == "circle":
            painter.drawEllipse(
                int(x - size/2), int(y - size/2), int(size), int(size)
            )
        elif symbol == "square":
            painter.drawRect(
                int(x - size/2), int(y - size/2), int(size), int(size)
            )
        elif symbol == "rectangle":
            w = size * 1.55
            h = size * 0.85
            painter.drawRect(
                int(x - w/2), int(y - h/2), int(w), int(h)
            )
        elif symbol == "x":
            s = size * 0.55
            painter.drawLine(int(x-s), int(y-s), int(x+s), int(y+s))
            painter.drawLine(int(x+s), int(y-s), int(x-s), int(y+s))
        elif symbol == "check":
            s = size * 0.55
            painter.drawLine(int(x-s), int(y), int(x-s*0.2), int(y+s*0.7))
            painter.drawLine(int(x-s*0.2), int(y+s*0.7), int(x+s), int(y-s*0.75))
        else:
            # Arrows are centered on the click point. The tip points in the
            # selected direction, making a click directly identify the area.
            length = size * 1.35
            head = size * 0.32
            if symbol == "arrow_up":
                sx, sy, ex, ey = x, y + length/2, x, y - length/2
            elif symbol == "arrow_right":
                sx, sy, ex, ey = x - length/2, y, x + length/2, y
            elif symbol == "arrow_down":
                sx, sy, ex, ey = x, y - length/2, x, y + length/2
            else:
                sx, sy, ex, ey = x + length/2, y, x - length/2, y

            painter.drawLine(int(sx), int(sy), int(ex), int(ey))

            import math
            angle = math.atan2(ey - sy, ex - sx)
            left = (
                ex - head * math.cos(angle - math.pi/6),
                ey - head * math.sin(angle - math.pi/6)
            )
            right = (
                ex - head * math.cos(angle + math.pi/6),
                ey - head * math.sin(angle + math.pi/6)
            )
            painter.drawLine(int(ex), int(ey), int(left[0]), int(left[1]))
            painter.drawLine(int(ex), int(ey), int(right[0]), int(right[1]))


class PhotoCard(QFrame):
    def __init__(self, index, data, remove_callback, move_callback, parent=None, changed_callback=None):
        super().__init__(parent)
        self.index = index
        self.data = data
        self.remove_callback = remove_callback
        self.move_callback = move_callback
        self.changed_callback = changed_callback
        self.setObjectName("photoCard")

        # Preserve compatibility with reports created before annotations existed.
        self.data.setdefault("annotations", [])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        top = QHBoxLayout()
        self.title = QLabel(f"PHOTO {index + 1}")
        self.title.setObjectName("photoTitle")
        top.addWidget(self.title)
        top.addStretch()

        top.addWidget(QLabel("Add Symbol:"))
        self.symbol_combo = QComboBox()
        for label, value in PhotoCanvas.SYMBOLS:
            self.symbol_combo.addItem(label, value)
        self.symbol_combo.currentIndexChanged.connect(self.symbol_changed)
        self.symbol_combo.setFixedWidth(145)
        top.addWidget(self.symbol_combo)

        top.addWidget(QLabel("Size:"))
        self.size_spin = QSpinBox()
        self.size_spin.setRange(25, 300)
        self.size_spin.setSingleStep(10)
        self.size_spin.setValue(250)
        self.size_spin.setSuffix("%")
        self.size_spin.setToolTip(
            "Set the size of the next symbol, or resize the selected symbol."
        )
        self.size_spin.valueChanged.connect(self.symbol_size_changed)
        self.size_spin.setFixedWidth(85)
        top.addWidget(self.size_spin)

        clear = QPushButton("Clear Markups")
        clear.setFixedHeight(30)
        clear.clicked.connect(self.clear_markups)
        top.addWidget(clear)

        up = QPushButton("↑")
        down = QPushButton("↓")
        remove = QPushButton("Remove")
        for b in (up, down, remove):
            b.setFixedHeight(30)
        up.clicked.connect(lambda: self.move_callback(index, -1))
        down.clicked.connect(lambda: self.move_callback(index, 1))
        remove.clicked.connect(lambda: self.remove_callback(index))
        top.addWidget(up)
        top.addWidget(down)
        top.addWidget(remove)
        layout.addLayout(top)

        body = QHBoxLayout()

        self.image_canvas = PhotoCanvas(self.data, self.markup_changed)
        body.addWidget(self.image_canvas, 2)

        right = QVBoxLayout()
        path_label = QLabel(Path(data["path"]).name)
        path_label.setWordWrap(True)
        path_label.setStyleSheet("color:#aaa;")
        right.addWidget(path_label)

        right.addWidget(QLabel("Description"))
        self.description = QTextEdit()
        self.description.setPlainText(data.get("description", ""))
        self.description.setMinimumHeight(130)
        self.description.textChanged.connect(self.sync)
        right.addWidget(self.description)

        rotate_row = QHBoxLayout()
        left = QPushButton("Rotate 90° Left")
        right_btn = QPushButton("Rotate 90° Right")
        left.clicked.connect(self.rotate_left)
        right_btn.clicked.connect(self.rotate_right)
        rotate_row.addWidget(left)
        rotate_row.addWidget(right_btn)
        right.addLayout(rotate_row)

        clear_rotation = QPushButton("Reset Rotation")
        clear_rotation.clicked.connect(self.reset_rotation)
        right.addWidget(clear_rotation)

        zoom = QPushButton("Open Photo / Zoom")
        zoom.clicked.connect(self.open_zoom)
        right.addWidget(zoom)

        right.addStretch()

        body.addLayout(right, 1)
        layout.addLayout(body)

        self.refresh()

    def sync(self):
        self.data["description"] = self.description.toPlainText()
        self.markup_changed()

    def markup_changed(self):
        selected = self.image_canvas.selected_annotation
        annotations = self.data.get("annotations", [])
        if selected is not None and 0 <= selected < len(annotations):
            size = int(annotations[selected].get("size", 100))
            if self.size_spin.value() != size:
                self.size_spin.blockSignals(True)
                self.size_spin.setValue(size)
                self.size_spin.blockSignals(False)
        self.changed_callback()
        self.image_canvas.update()

    def symbol_changed(self):
        self.image_canvas.set_symbol(self.symbol_combo.currentData())

    def symbol_size_changed(self, value):
        self.image_canvas.symbol_size = value
        selected = self.image_canvas.selected_annotation
        annotations = self.data.get("annotations", [])
        if selected is not None and 0 <= selected < len(annotations):
            annotations[selected]["size"] = value
        self.markup_changed()

    def clear_markups(self):
        self.data["annotations"] = []
        self.image_canvas.selected_annotation = None
        self.markup_changed()

    def open_zoom(self):
        dialog = ZoomDialog(self.data, self)
        dialog.exec()
        self.refresh()
        self.markup_changed()

    def rotate_left(self):
        self.data["rotation"] = (self.data.get("rotation", 0) - 90) % 360
        self.refresh()
        self.markup_changed()

    def rotate_right(self):
        self.data["rotation"] = (self.data.get("rotation", 0) + 90) % 360
        self.refresh()
        self.markup_changed()

    def reset_rotation(self):
        self.data["rotation"] = 0
        self.refresh()
        self.markup_changed()

    def refresh(self):
        self.title.setText(f"PHOTO {self.index + 1}")
        pix = QPixmap(self.data["path"])
        if not pix.isNull():
            rotation = self.data.get("rotation", 0)
            if rotation:
                pix = pix.transformed(QTransform().rotate(rotation))
            self.image_canvas.set_image(pix)
        else:
            self.image_canvas.set_image(QPixmap())


class RepairEvaluationWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1200, 900)
        self.setMinimumSize(1000, 760)
        self.photos = []
        self.current_file = None
        self.dirty = False
        self.setup_ui()
        self.setup_help_menu()
        self.new_report()

    def setup_ui(self):
        self.setStyleSheet(f"""
            QWidget {{
                background:{DARK};
                color:{TEXT};
                font-family: Segoe UI, Arial;
                font-size: 10pt;
            }}

            QMenuBar {{
                background:#202020;
                color:white;
                border-bottom:1px solid #444;
                padding:2px 4px;
            }}
            QMenuBar::item {{
                background:transparent;
                padding:6px 10px;
                border-radius:4px;
            }}
            QMenuBar::item:selected {{
                background:#3a3a3a;
                color:white;
            }}
            QMenu {{
                background:#242424;
                color:white;
                border:1px solid #555;
                padding:4px;
            }}
            QMenu::item {{
                padding:7px 28px 7px 12px;
                border-radius:4px;
            }}
            QMenu::item:selected {{
                background:#ff7a00;
                color:white;
            }}
            QMenu::separator {{
                height:1px;
                background:#4a4a4a;
                margin:4px 8px;
            }}
            QLineEdit, QTextEdit, QComboBox, QDateEdit, QSpinBox {{
                background:{FIELD};
                border:1px solid {BORDER};
                border-radius:6px;
                padding:7px;
                color:{TEXT};
            }}
            QLineEdit:focus, QTextEdit:focus, QComboBox:focus, QDateEdit:focus {{
                border:1px solid {ORANGE};
            }}
            QPushButton {{
                background:#333;
                border:1px solid #555;
                border-radius:6px;
                padding:8px 14px;
                color:white;
            }}
            QPushButton:hover {{ background:#444; border-color:{ORANGE}; }}
            QPushButton#primary {{
                background:{ORANGE};
                color:white;
                border:0;
                font-weight:bold;
            }}
            QPushButton#primary:hover {{ background:#ff8b22; }}
            QLabel#mainTitle {{
                font-size:20pt;
                font-weight:bold;
            }}
            QLabel#subtitle {{ color:{MUTED}; }}
            QLabel#section {{
                background:{SECTION};
                color:white;
                font-weight:bold;
                font-size:12pt;
                padding:8px;
                border-radius:4px;
            }}
            QFrame#photoCard {{
                background:{PANEL};
                border:1px solid {BORDER};
                border-radius:8px;
            }}
            QLabel#photoTitle {{
                font-size:12pt;
                font-weight:bold;
                color:{CYAN};
            }}
            QScrollArea {{
                border:0;
            }}
        """)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(18, 14, 18, 14)

        header = QHBoxLayout()
        if APP_LOGO.exists():
            logo = QLabel()
            pix = QPixmap(str(APP_LOGO))
            logo.setPixmap(pix.scaledToHeight(70, Qt.TransformationMode.SmoothTransformation))
            header.addWidget(logo)
        titlebox = QVBoxLayout()
        title = QLabel("REPAIR EVALUATION")
        title.setObjectName("mainTitle")
        titlebox.addWidget(title)
        subtitle = QLabel("IFP Motion Solutions — Service / Repair Documentation")
        subtitle.setObjectName("subtitle")
        titlebox.addWidget(subtitle)
        header.addLayout(titlebox)
        header.addStretch()
        root.addLayout(header)

        toolbar = QHBoxLayout()
        for text, slot, primary in [
            ("New", self.new_report, False),
            ("Open", self.open_report, False),
            ("Save", self.save_report, False),
            ("Preview PDF", self.preview_pdf, False),
            ("Print / Save PDF", self.export_pdf, True),
        ]:
            b = QPushButton(text)
            if primary:
                b.setObjectName("primary")
            b.clicked.connect(slot)
            toolbar.addWidget(b)
        toolbar.addStretch()
        root.addLayout(toolbar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        self.form = QVBoxLayout(container)
        self.form.setSpacing(12)
        self.build_form()
        scroll.setWidget(container)
        root.addWidget(scroll, 1)

    def section(self, text):
        l = QLabel(text)
        l.setObjectName("section")
        self.form.addWidget(l)

    def field(self, label, widget):
        box = QVBoxLayout()
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)
        lab = QLabel(label)
        box.addWidget(lab)
        box.addWidget(widget)
        return box

    def build_form(self):
        # Create report information widgets before constructing the layout.
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("MM/dd/yyyy")
        self.date_edit.dateChanged.connect(self.mark_dirty)

        self.repair_no = QLineEdit()
        self.repair_no.setPlaceholderText("R123456")
        self.repair_no.textChanged.connect(self.mark_dirty)

        self.technician = QComboBox()
        self.technician.addItems([
            "S. HAMILTON",
            "M. DONLEY",
            "A. KRON",
            "P. THOMANN",
            "A. TRITLE",
        ])
        self.technician.currentTextChanged.connect(self.mark_dirty)

        self.customer = QLineEdit()
        self.customer.textChanged.connect(self.mark_dirty)

        self.customer_contact = QLineEdit()
        self.customer_contact.textChanged.connect(self.mark_dirty)

        self.customer_email = QLineEdit()
        self.customer_email.textChanged.connect(self.mark_dirty)

        self.model = QLineEdit()
        self.model.textChanged.connect(self.mark_dirty)

        self.serial = QLineEdit()
        self.serial.textChanged.connect(self.mark_dirty)

        self.customer_po = QLineEdit()
        self.customer_po.textChanged.connect(self.mark_dirty)

        self.material = QLineEdit()
        self.material.textChanged.connect(self.mark_dirty)

        self.section("REPAIR INFORMATION")
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        # Give the right side more width so Customer Contact / Customer Email
        # have more room, while shortening the left-side input boxes.
        grid.setColumnStretch(0, 4)
        grid.setColumnStretch(1, 6)

        # Consistent two-column information layout.
        grid.addLayout(self.field("Date", self.date_edit), 0, 0)
        grid.addLayout(self.field("Repair #", self.repair_no), 0, 1)

        grid.addLayout(self.field("Customer", self.customer), 1, 0)

        # Customer Contact + Customer Email share the right column using
        # the same field() layout style as every other field.
        contact_grid = QGridLayout()
        contact_grid.setContentsMargins(0, 0, 0, 0)
        contact_grid.setHorizontalSpacing(10)
        contact_grid.setVerticalSpacing(0)
        contact_grid.setColumnStretch(0, 1)
        contact_grid.setColumnStretch(1, 1)
        contact_grid.addLayout(self.field("Customer Contact", self.customer_contact), 0, 0)
        contact_grid.addLayout(self.field("Customer Email", self.customer_email), 0, 1)
        grid.addLayout(contact_grid, 1, 1)

        grid.addLayout(self.field("Customer PO", self.customer_po), 2, 0)
        grid.addLayout(self.field("Customer Part Number", self.material), 2, 1)

        grid.addLayout(self.field("Make / Model", self.model), 3, 0)
        grid.addLayout(self.field("Serial Number / Previous Repair Number", self.serial), 3, 1)

        grid.addLayout(self.field("Technician", self.technician), 4, 0)
        self.form.addLayout(grid)

        self.section("CUSTOMER REQUEST / REPORTED PROBLEM")
        self.customer_request = QTextEdit()
        self.customer_request.setMinimumHeight(110)
        self.customer_request.textChanged.connect(self.mark_dirty)
        self.form.addWidget(self.customer_request)

        self.section("REPAIR EVALUATION / FINDINGS")
        self.findings = QTextEdit()
        self.findings.setMinimumHeight(160)
        self.findings.textChanged.connect(self.mark_dirty)
        self.form.addWidget(self.findings)

        self.section("PHOTOGRAPHIC DOCUMENTATION")
        row = QHBoxLayout()
        add = QPushButton("+ ADD PHOTO")
        add.setObjectName("primary")
        add.clicked.connect(self.add_photos)
        row.addWidget(add)
        row.addStretch()
        self.photo_count = QLabel("0 photos")
        row.addWidget(self.photo_count)
        self.form.addLayout(row)

        self.photo_area = QVBoxLayout()
        self.form.addLayout(self.photo_area)
        self.form.addStretch()

    def mark_dirty(self):
        self.dirty = True

    def setup_help_menu(self):
        help_menu = self.menuBar().addMenu("&Help")

        how_action = help_menu.addAction("How to Use")
        how_action.setShortcut("F1")
        how_action.triggered.connect(self.show_help)

        about_action = help_menu.addAction("About IFP Repair Evaluation")
        about_action.triggered.connect(self.show_about)

        help_menu.addSeparator()
        shortcuts_action = help_menu.addAction("Keyboard Shortcuts")
        shortcuts_action.triggered.connect(self.show_shortcuts)

    def show_help(self):
        dialog = HelpDialog(self)
        dialog.exec()

    def show_about(self):
        dialog = HelpDialog(self)
        # Select About tab (last tab).
        if dialog.findChildren(QTabWidget):
            dialog.findChildren(QTabWidget)[0].setCurrentIndex(3)
        dialog.exec()

    def show_shortcuts(self):
        dialog = HelpDialog(self)
        if dialog.findChildren(QTabWidget):
            dialog.findChildren(QTabWidget)[0].setCurrentIndex(2)
        dialog.exec()

    def new_report(self):
        self.date_edit.setDate(__import__("PyQt6.QtCore", fromlist=["QDate"]).QDate.currentDate())
        for w in [
            self.repair_no, self.customer, self.customer_contact, self.customer_email,
            self.model, self.serial, self.customer_po, self.material
        ]:
            w.clear()
        self.technician.setCurrentIndex(0)
        for w in [self.customer_request, self.findings]:
            w.clear()
        self.photos.clear()
        self.current_file = None
        self.rebuild_photos()
        self.dirty = False

    def add_photos(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select Repair Evaluation Photos", "",
            "Images (*.jpg *.jpeg *.png *.bmp *.webp)"
        )
        if not paths:
            return

        for p in paths:
            try:
                optimized = optimize_uploaded_image(p)
                photo_path = str(optimized.resolve())
            except Exception:
                photo_path = str(Path(p).resolve())

            self.photos.append({
                "path": photo_path,
                "description": "",
                "rotation": 0,
                "annotations": []
            })
        self.rebuild_photos()
        self.mark_dirty()

    def rebuild_photos(self):
        while self.photo_area.count():
            item = self.photo_area.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for i, data in enumerate(self.photos):
            card = PhotoCard(i, data, self.remove_photo, self.move_photo, changed_callback=self.photo_changed)
            self.photo_area.addWidget(card)
        self.photo_count.setText(f"{len(self.photos)} photo{'s' if len(self.photos) != 1 else ''}")

    def photo_changed(self):
        self.mark_dirty()

    def remove_photo(self, index):
        if 0 <= index < len(self.photos):
            self.photos.pop(index)
            self.rebuild_photos()
            self.mark_dirty()

    def move_photo(self, index, direction):
        new_index = index + direction
        if 0 <= new_index < len(self.photos):
            self.photos[index], self.photos[new_index] = self.photos[new_index], self.photos[index]
            self.rebuild_photos()
            self.mark_dirty()

    def collect_data(self):
        return {
            "date": self.date_edit.date().toString("yyyy-MM-dd"),
            "repair_no": self.repair_no.text().strip(),
            "technician": self.technician.currentText().strip(),
            "customer": self.customer.text().strip(),
            "customer_contact": self.customer_contact.text().strip(),
            "customer_email": self.customer_email.text().strip(),
            "model": self.model.text().strip(),
            "serial": self.serial.text().strip(),
            "customer_po": self.customer_po.text().strip(),
            "material": self.material.text().strip(),
            "customer_request": self.customer_request.toPlainText(),
            "received_condition": "",
            "findings": self.findings.toPlainText(),
            "photos": self.photos,
        }

    def save_report(self):
        if self.current_file is None:
            default = self.repair_no.text().strip() or "RepairEvaluation"
            path, _ = QFileDialog.getSaveFileName(
                self, "Save Repair Evaluation", default + ".json",
                "Repair Evaluation (*.json)"
            )
            if not path:
                return
            self.current_file = Path(path)

        self.current_file.parent.mkdir(parents=True, exist_ok=True)
        photo_dir = self.current_file.parent / f"{self.current_file.stem}_photos"
        photo_dir.mkdir(parents=True, exist_ok=True)

        data = self.collect_data()
        stored_photos = []
        for i, p in enumerate(data["photos"], start=1):
            src = Path(p["path"])
            dest = photo_dir / f"photo_{i:03d}.jpg"
            try:
                optimized = optimize_uploaded_image(src)
                shutil.copy2(optimized, dest)
            except Exception:
                try:
                    shutil.copy2(src, dest)
                except Exception:
                    dest = src
            stored_photos.append({
                "path": str(dest),
                "description": p.get("description", ""),
                "rotation": p.get("rotation", 0),
                "annotations": [
                    {
                        "symbol": a.get("symbol", "arrow_up"),
                        "x": a.get("x", 0.5),
                        "y": a.get("y", 0.5),
                        "size": a.get("size", 100),
                    }
                    for a in p.get("annotations", [])
                ],
            })
        data["photos"] = stored_photos

        self.current_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        self.photos = stored_photos
        self.rebuild_photos()
        self.dirty = False
        self.statusBar().showMessage(f"Saved: {self.current_file}")

    def open_report(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Repair Evaluation", "", "Repair Evaluation (*.json)"
        )
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as e:
            QMessageBox.critical(self, "Open Error", f"Unable to open report:\n{e}")
            return

        from PyQt6.QtCore import QDate
        d = QDate.fromString(data.get("date", ""), "yyyy-MM-dd")
        if d.isValid():
            self.date_edit.setDate(d)

        self.repair_no.setText(data.get("repair_no", ""))
        technician_name = data.get("technician", "")
        tech_index = self.technician.findText(technician_name)
        self.technician.setCurrentIndex(tech_index if tech_index >= 0 else 0)
        self.customer.setText(data.get("customer", ""))
        self.customer_contact.setText(data.get("customer_contact", ""))
        self.customer_email.setText(data.get("customer_email", ""))
        self.model.setText(data.get("model", ""))
        self.serial.setText(data.get("serial", ""))
        self.customer_po.setText(data.get("customer_po", ""))
        self.material.setText(data.get("material", ""))
        self.customer_request.setPlainText(data.get("customer_request", ""))
        self.findings.setPlainText(data.get("findings", ""))
        self.photos = data.get("photos", [])
        for photo in self.photos:
            photo.setdefault("annotations", [])
            for annotation in photo["annotations"]:
                annotation.setdefault("symbol", "arrow_up")
                annotation.setdefault("x", 0.5)
                annotation.setdefault("y", 0.5)
                annotation.setdefault("size", 100)
        self.current_file = Path(path)
        self.rebuild_photos()
        self.dirty = False
        self.statusBar().showMessage(f"Opened: {path}")

    def report_title(self, data):
        r = data["repair_no"] or "UNNUMBERED"
        return f"Repair Evaluation Report — {r}"

    def _draw_pdf_annotations(self, im, annotations, display_width_px, display_height_px):
        """Draw annotations at the same relative size used by the app preview."""
        from PIL import ImageDraw
        import math

        draw = ImageDraw.Draw(im)
        w, h = im.size

        # display_width_px/display_height_px represent the actual size of the
        # image on the PDF page. Annotation geometry is calculated in that
        # coordinate system, then converted back to source-image pixels.
        display_base = min(display_width_px, display_height_px)
        source_base = min(w, h)

        # The app uses 10% of the displayed image's shortest dimension as its
        # 100% symbol size.
        base_display_symbol = display_base * 0.10
        base_source_symbol = base_display_symbol * (source_base / display_base)

        for a in annotations or []:
            symbol = a.get("symbol", "arrow_up")
            x = a.get("x", 0.5) * w
            y = a.get("y", 0.5) * h
            symbol_scale = max(0.25, a.get("size", 100) / 100.0)

            current_size = base_source_symbol * symbol_scale
            current_size = max(4.0, current_size)
            width = max(2, int(current_size * 0.065))
            radius = current_size / 2

            if symbol == "circle":
                draw.ellipse(
                    [x-radius, y-radius, x+radius, y+radius],
                    outline="red", width=width
                )
            elif symbol == "square":
                draw.rectangle(
                    [x-radius, y-radius, x+radius, y+radius],
                    outline="red", width=width
                )
            elif symbol == "rectangle":
                rw, rh = current_size * 1.55, current_size * 0.85
                draw.rectangle(
                    [x-rw/2, y-rh/2, x+rw/2, y+rh/2],
                    outline="red", width=width
                )
            elif symbol == "x":
                s = current_size * 0.55
                draw.line([x-s, y-s, x+s, y+s], fill="red", width=width)
                draw.line([x+s, y-s, x-s, y+s], fill="red", width=width)
            elif symbol == "check":
                s = current_size * 0.55
                draw.line(
                    [x-s, y, x-s*0.2, y+s*0.7],
                    fill="red", width=width
                )
                draw.line(
                    [x-s*0.2, y+s*0.7, x+s, y-s*0.75],
                    fill="red", width=width
                )
            else:
                length = current_size * 1.35
                head = current_size * 0.32

                if symbol == "arrow_up":
                    sx, sy, ex, ey = x, y + length/2, x, y - length/2
                elif symbol == "arrow_right":
                    sx, sy, ex, ey = x-length/2, y, x+length/2, y
                elif symbol == "arrow_down":
                    sx, sy, ex, ey = x, y-length/2, x, y+length/2
                else:
                    sx, sy, ex, ey = x+length/2, y, x-length/2, y

                draw.line([sx, sy, ex, ey], fill="red", width=width)
                angle = math.atan2(ey-sy, ex-sx)
                left = (
                    ex - head*math.cos(angle-math.pi/6),
                    ey - head*math.sin(angle-math.pi/6)
                )
                right = (
                    ex - head*math.cos(angle+math.pi/6),
                    ey - head*math.sin(angle+math.pi/6)
                )
                draw.line([ex, ey, left[0], left[1]], fill="red", width=width)
                draw.line([ex, ey, right[0], right[1]], fill="red", width=width)

    def _pdf_image_path(self, photo, temp_dir):
        """Create a PDF-ready image with rotation and correctly scaled markups."""
        source = Path(photo["path"])
        rotation = photo.get("rotation", 0) % 360
        annotations = photo.get("annotations", []) or []

        if not source.exists():
            return source

        if rotation == 0 and not annotations:
            return source

        existing = list(Path(temp_dir).glob("annotated_*"))
        output = Path(temp_dir) / f"annotated_{len(existing):04d}.jpg"

        with PILImage.open(source) as im:
            if rotation:
                # Match Qt's positive rotation (clockwise visually).
                im = im.rotate(-rotation, expand=True)

            if im.mode in ("RGBA", "LA"):
                background = PILImage.new("RGB", im.size, "white")
                alpha = im.getchannel("A")
                background.paste(im, mask=alpha)
                im = background
            elif im.mode != "RGB":
                im = im.convert("RGB")

            # PDF photo cell/image bounds in points. This matches the
            # RLImage sizing used immediately before placement.
            max_w = 3.35 * 72
            max_h = 2.35 * 72
            ratio = min(max_w / im.width, max_h / im.height)
            display_w = im.width * ratio
            display_h = im.height * ratio

            self._draw_pdf_annotations(
                im, annotations, display_w, display_h
            )
            im.save(
                output,
                format="JPEG",
                quality=82,
                optimize=True,
                progressive=True
            )

        return output

    def build_pdf(self, pdf_path):
        data = self.collect_data()
        styles = getSampleStyleSheet()
        normal = ParagraphStyle(
            "Normal2", parent=styles["Normal"], fontName="Helvetica",
            fontSize=9, leading=12, textColor=colors.HexColor("#222222")
        )
        small = ParagraphStyle(
            "Small", parent=normal, fontSize=7.5, leading=9
        )
        section_style = ParagraphStyle(
            "Section", parent=normal, fontName="Helvetica-Bold",
            fontSize=11, alignment=TA_CENTER, textColor=colors.white
        )
        title_style = ParagraphStyle(
            "Title2", parent=normal, fontName="Helvetica-Bold",
            fontSize=18, leading=20, alignment=TA_CENTER
        )
        label_style = ParagraphStyle(
            "Label", parent=small, fontName="Helvetica-Bold"
        )

        doc = SimpleDocTemplate(
            str(pdf_path), pagesize=letter,
            rightMargin=0.42*inch, leftMargin=0.42*inch,
            topMargin=0.38*inch, bottomMargin=0.42*inch
        )
        story = []

        if PDF_LOGO.exists():
            lw, lh = image_size(PDF_LOGO, 1.65*inch, 0.62*inch)
            logo = RLImage(str(PDF_LOGO), width=lw, height=lh)
        else:
            logo = Paragraph("", normal)

        header_table = Table([
            [logo, Paragraph("REPAIR EVALUATION REPORT", title_style)]
        ], colWidths=[1.9*inch, 5.1*inch])
        header_table.setStyle(TableStyle([
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
            ("BOX", (0,0), (-1,-1), 1, colors.black),
            ("LEFTPADDING", (0,0), (-1,-1), 8),
            ("RIGHTPADDING", (0,0), (-1,-1), 8),
            ("TOPPADDING", (0,0), (-1,-1), 7),
            ("BOTTOMPADDING", (0,0), (-1,-1), 7),
        ]))
        story.append(header_table)
        story.append(Spacer(1, 6))

        # Match the application field locations exactly:
        # Left column: Date, Customer, Customer PO, Make/Model, Technician
        # Right column: Repair #, Customer Contact, Customer Part Number, Serial Number
        # Match the application layout exactly.
        # Left column: Date, Customer, Customer PO, Make/Model, Technician
        # Right column: Repair #, Customer Contact + Customer Email,
        # Customer Part Number, Serial Number
        info = [
            [
                Paragraph("<b>Date</b>", label_style),
                __import__("datetime").datetime.strptime(
                    data["date"], "%Y-%m-%d"
                ).strftime("%m/%d/%Y") if data["date"] else "",
                Paragraph("<b>Repair #</b>", label_style),
                data["repair_no"],
                "",
                "",
            ],
            [
                Paragraph("<b>Customer</b>", label_style),
                data["customer"],
                Paragraph("<b>Customer Contact</b>", label_style),
                data["customer_contact"],
                Paragraph("<b>Customer Email</b>", label_style),
                data["customer_email"],
            ],
            [
                Paragraph("<b>Customer PO</b>", label_style),
                data["customer_po"],
                Paragraph("<b>Customer Part Number</b>", label_style),
                "",
                data["material"],
                "",
            ],
            [
                Paragraph("<b>Make / Model</b>", label_style),
                data["model"],
                Paragraph("<b>Serial Number / Previous Repair Number</b>", label_style),
                "",
                data["serial"],
                "",
            ],
            [
                Paragraph("<b>Technician</b>", label_style),
                data["technician"],
                "",
                "",
                "",
                "",
            ],
        ]

        # Keep the first two rows unchanged. On the Customer Part Number and
        # Serial Number rows only, the right-side label spans two columns and
        # the value spans the remaining two columns. This widens those labels
        # without changing the geometry of the rows above.
        info_col_widths = [
            1.15*inch, 2.00*inch,
            0.78*inch, 0.99*inch,
            0.78*inch, 1.40*inch,
        ]

        t = Table(info, colWidths=info_col_widths)

        t.setStyle(TableStyle([
            ("GRID", (0,0), (-1,-1), 0.6, colors.black),

            # Left-side label cells.
            ("BACKGROUND", (0,0), (0,-1), colors.HexColor("#e9eef1")),

            # Right-side label cells in the normal rows.
            ("BACKGROUND", (2,0), (2,1), colors.HexColor("#e9eef1")),
            ("BACKGROUND", (4,1), (4,1), colors.HexColor("#e9eef1")),

            # Wider labels ONLY on Customer Part Number / Serial Number rows.
            ("SPAN", (2,2), (3,2)),
            ("SPAN", (4,2), (5,2)),
            ("SPAN", (2,3), (3,3)),
            ("SPAN", (4,3), (5,3)),
            ("BACKGROUND", (2,2), (3,3), colors.HexColor("#e9eef1")),

            # Repair # value spans the remainder of the right side.
            ("SPAN", (3,0), (5,0)),

            # Technician occupies the left side only.
            ("SPAN", (2,4), (5,4)),

            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
            ("FONTNAME", (0,0), (-1,-1), "Helvetica"),
            ("FONTSIZE", (0,0), (-1,-1), 8.5),

            ("LEFTPADDING", (0,0), (-1,-1), 5),
            ("RIGHTPADDING", (0,0), (-1,-1), 5),
            ("TOPPADDING", (0,0), (-1,-1), 5),
            ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ]))

        story.append(t)

        story.append(Spacer(1, 8))

        def section_block(title, text):
            heading = Table([[Paragraph(title, section_style)]], colWidths=[7.1*inch])
            heading.setStyle(TableStyle([
                ("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#6d8fa0")),
                ("BOX", (0,0), (-1,-1), 0.6, colors.black),
                ("TOPPADDING", (0,0), (-1,-1), 5),
                ("BOTTOMPADDING", (0,0), (-1,-1), 5),
            ]))
            body_text = (text or "").replace("\n", "<br/>")
            body = Table([[Paragraph(body_text or "&nbsp;", normal)]], colWidths=[7.1*inch])
            body.setStyle(TableStyle([
                ("BOX", (0,0), (-1,-1), 0.6, colors.black),
                ("VALIGN", (0,0), (-1,-1), "TOP"),
                ("LEFTPADDING", (0,0), (-1,-1), 7),
                ("RIGHTPADDING", (0,0), (-1,-1), 7),
                ("TOPPADDING", (0,0), (-1,-1), 7),
                ("BOTTOMPADDING", (0,0), (-1,-1), 7),
            ]))
            return [heading, body, Spacer(1, 7)]

        story.extend(section_block("CUSTOMER REQUEST / REPORTED PROBLEM", data["customer_request"]))
        story.extend(section_block("REPAIR EVALUATION / FINDINGS", data["findings"]))

        photos = data["photos"]
        with tempfile.TemporaryDirectory(prefix="ifp_repair_pdf_") as temp_dir:
            if photos:
                appendix_heading = Table(
                    [[Paragraph("PHOTOGRAPHIC DOCUMENTATION", section_style)]],
                    colWidths=[7.1*inch]
                )
                appendix_heading.setStyle(TableStyle([
                    ("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#6d8fa0")),
                    ("BOX", (0,0), (-1,-1), 0.6, colors.black),
                    ("TOPPADDING", (0,0), (-1,-1), 6),
                    ("BOTTOMPADDING", (0,0), (-1,-1), 6),
                ]))
                story.append(appendix_heading)
                story.append(Spacer(1, 6))

                def make_photo_cell(photo, number, max_w, max_h):
                    pdf_photo_path = self._pdf_image_path(photo, temp_dir)
                    if Path(pdf_photo_path).exists():
                        w, h = image_size(pdf_photo_path, max_w, max_h)
                        img = RLImage(str(pdf_photo_path), width=w, height=h)
                    else:
                        img = Paragraph("Image unavailable", normal)

                    title = Paragraph(f"<b>PHOTO {number}</b>", normal)
                    desc = Paragraph(
                        (photo.get("description", "") or "No description provided.").replace("\n", "<br/>"),
                        small
                    )
                    return Table(
                        [[title], [img], [Paragraph("<b>Description:</b>", small)], [desc]],
                        colWidths=[max_w + 0.13*inch],
                        rowHeights=[
                            0.28*inch,
                            max_h + 0.07*inch,
                            0.22*inch,
                            0.55*inch
                        ],
                        style=TableStyle([
                            ("BOX", (0,0), (-1,-1), 0.7, colors.black),
                            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#8be9f5")),
                            ("ALIGN", (0,0), (-1,0), "CENTER"),
                            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
                            ("LEFTPADDING", (0,0), (-1,-1), 4),
                            ("RIGHTPADDING", (0,0), (-1,-1), 4),
                            ("TOPPADDING", (0,0), (-1,-1), 3),
                            ("BOTTOMPADDING", (0,0), (-1,-1), 3),
                        ])
                    )

                # One photo uses a compact layout so it can occupy the
                # remaining space on page 1 when available. There are no
                # placeholder boxes.
                if len(photos) == 1:
                    cell = make_photo_cell(
                        photos[0], 1,
                        max_w=3.35*inch,
                        max_h=1.85*inch
                    )
                    story.append(KeepTogether(cell))

                else:
                    # Use two-column photo rows for 2+ photos. Each group is
                    # allowed to flow to the next page when it cannot fit.
                    for start in range(0, len(photos), 4):
                        page_photos = photos[start:start+4]
                        cells = [
                            make_photo_cell(
                                photo, start + i + 1,
                                max_w=3.35*inch,
                                max_h=2.35*inch
                            )
                            for i, photo in enumerate(page_photos)
                        ]

                        if len(cells) == 2:
                            row = Table(
                                [cells],
                                colWidths=[3.55*inch, 3.55*inch]
                            )
                            row.setStyle(TableStyle([
                                ("VALIGN", (0,0), (-1,-1), "TOP"),
                                ("LEFTPADDING", (0,0), (-1,-1), 2),
                                ("RIGHTPADDING", (0,0), (-1,-1), 2),
                                ("TOPPADDING", (0,0), (-1,-1), 2),
                                ("BOTTOMPADDING", (0,0), (-1,-1), 2),
                            ]))
                            story.append(KeepTogether(row))

                        elif len(cells) == 3:
                            row1 = Table(
                                [[cells[0], cells[1]]],
                                colWidths=[3.55*inch, 3.55*inch]
                            )
                            row1.setStyle(TableStyle([
                                ("VALIGN", (0,0), (-1,-1), "TOP"),
                                ("LEFTPADDING", (0,0), (-1,-1), 2),
                                ("RIGHTPADDING", (0,0), (-1,-1), 2),
                                ("TOPPADDING", (0,0), (-1,-1), 2),
                                ("BOTTOMPADDING", (0,0), (-1,-1), 2),
                            ]))
                            story.append(KeepTogether(row1))
                            story.append(Spacer(1, 4))
                            story.append(KeepTogether(cells[2]))

                        else:
                            grid = Table(
                                [[cells[0], cells[1]], [cells[2], cells[3]]],
                                colWidths=[3.55*inch, 3.55*inch]
                            )
                            grid.setStyle(TableStyle([
                                ("VALIGN", (0,0), (-1,-1), "TOP"),
                                ("LEFTPADDING", (0,0), (-1,-1), 2),
                                ("RIGHTPADDING", (0,0), (-1,-1), 2),
                                ("TOPPADDING", (0,0), (-1,-1), 2),
                                ("BOTTOMPADDING", (0,0), (-1,-1), 2),
                            ]))
                            story.append(KeepTogether(grid))

            def footer(canvas, doc):
                canvas.saveState()
                canvas.setFont("Helvetica", 7)
                canvas.setFillColor(colors.HexColor("#666666"))
                canvas.drawString(
                    0.42*inch, 0.22*inch,
                    f"IFP Motion Solutions • {self.report_title(data)}"
                )
                canvas.drawRightString(
                    8.08*inch, 0.22*inch, f"Page {doc.page}"
                )
                canvas.restoreState()

            doc.build(story, onFirstPage=footer, onLaterPages=footer)

    def choose_pdf_path(self):
        default_name = (self.repair_no.text().strip() or "RepairEvaluation") + ".pdf"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Repair Evaluation PDF", default_name, "PDF (*.pdf)"
        )
        return Path(path) if path else None

    def export_pdf(self):
        path = self.choose_pdf_path()
        if not path:
            return
        try:
            self.build_pdf(path)
            self.statusBar().showMessage(f"PDF created: {path}")
            QMessageBox.information(self, "PDF Created", f"Report PDF created:\n\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "PDF Error", f"Unable to create PDF:\n{e}")

    def preview_pdf(self):
        temp = Path(tempfile.gettempdir()) / "IFP_Repair_Evaluation_Preview.pdf"
        try:
            self.build_pdf(temp)
            if sys.platform.startswith("win"):
                os.startfile(temp)
            elif sys.platform == "darwin":
                os.system(f'open "{temp}"')
            else:
                os.system(f'xdg-open "{temp}"')
        except Exception as e:
            QMessageBox.critical(self, "Preview Error", f"Unable to preview PDF:\n{e}")

    def closeEvent(self, event):
        if self.dirty:
            answer = QMessageBox.question(
                self, "Unsaved Changes",
                "This repair evaluation has unsaved changes. Close anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    if APP_LOGO.exists():
        app.setWindowIcon(QIcon(str(APP_LOGO)))
    window = RepairEvaluationWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
