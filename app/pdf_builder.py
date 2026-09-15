"""ReportLab PDF generation.

Symbol geometry in _draw_pdf_annotations() must stay in step with drawSymbol()
in static/app.js so the on-screen preview and the PDF agree.
"""
import math
import tempfile
from datetime import datetime
from pathlib import Path

from PIL import Image as PILImage
from PIL import ImageDraw
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Image as RLImage,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .config import PDF_LOGO
from .images import PDF_EDGE


def image_size(path: Path, max_w: float, max_h: float) -> tuple[float, float]:
    try:
        with PILImage.open(path) as im:
            w, h = im.size
        if not w or not h:
            return max_w, max_h
        scale = min(max_w / w, max_h / h)
        return w * scale, h * scale
    except Exception:
        return max_w, max_h


def report_title(data: dict) -> str:
    r = data.get("repair_no") or "UNNUMBERED"
    return f"Repair Evaluation Report — {r}"


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _draw_pdf_annotations(im, annotations, display_width_px, display_height_px) -> None:
    """Draw annotations at the same relative size used by the app preview."""
    draw = ImageDraw.Draw(im)
    w, h = im.size

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
        color = a.get("color") or "#ff0000"

        current_size = max(4.0, base_source_symbol * symbol_scale)
        width = max(2, int(current_size * 0.065))
        radius = current_size / 2

        if symbol == "circle":
            draw.ellipse([x - radius, y - radius, x + radius, y + radius], outline=color, width=width)
        elif symbol == "square":
            draw.rectangle([x - radius, y - radius, x + radius, y + radius], outline=color, width=width)
        elif symbol == "rectangle":
            rw, rh = current_size * 1.55, current_size * 0.85
            draw.rectangle([x - rw / 2, y - rh / 2, x + rw / 2, y + rh / 2], outline=color, width=width)
        elif symbol == "x":
            s = current_size * 0.55
            draw.line([x - s, y - s, x + s, y + s], fill=color, width=width)
            draw.line([x + s, y - s, x - s, y + s], fill=color, width=width)
        elif symbol == "check":
            s = current_size * 0.55
            draw.line([x - s, y, x - s * 0.2, y + s * 0.7], fill=color, width=width)
            draw.line([x - s * 0.2, y + s * 0.7, x + s, y - s * 0.75], fill=color, width=width)
        else:
            length = current_size * 1.35
            head = current_size * 0.32
            if symbol == "arrow_up":
                sx, sy, ex, ey = x, y + length / 2, x, y - length / 2
            elif symbol == "arrow_right":
                sx, sy, ex, ey = x - length / 2, y, x + length / 2, y
            elif symbol == "arrow_down":
                sx, sy, ex, ey = x, y - length / 2, x, y + length / 2
            else:
                sx, sy, ex, ey = x + length / 2, y, x - length / 2, y

            draw.line([sx, sy, ex, ey], fill=color, width=width)
            angle = math.atan2(ey - sy, ex - sx)
            left = (ex - head * math.cos(angle - math.pi / 6), ey - head * math.sin(angle - math.pi / 6))
            right = (ex - head * math.cos(angle + math.pi / 6), ey - head * math.sin(angle + math.pi / 6))
            draw.line([ex, ey, left[0], left[1]], fill=color, width=width)
            draw.line([ex, ey, right[0], right[1]], fill=color, width=width)


def _pdf_image_path(photo: dict, temp_dir: str) -> Path:
    """Create a PDF-ready image: downscaled (a hand-copied 20 MB original must
    not bloat the report), rotated, with correctly scaled markups.

    `photo["local_path"]` is filled in by the caller (main.py) - the resolved
    file on the share for this photo's reference."""
    source = Path(photo.get("local_path") or "")
    rotation = int(photo.get("rotation", 0)) % 360
    annotations = photo.get("annotations", []) or []

    if not source or not source.exists():
        return Path(temp_dir) / "missing.jpg"   # does not exist -> "Image unavailable"

    existing = list(Path(temp_dir).glob("annotated_*"))
    output = Path(temp_dir) / f"annotated_{len(existing):04d}.jpg"

    with PILImage.open(source) as im:
        try:
            from PIL import ImageOps
            im = ImageOps.exif_transpose(im)
        except Exception:
            pass
        if im.mode in ("RGBA", "LA"):
            background = PILImage.new("RGB", im.size, "white")
            background.paste(im, mask=im.getchannel("A"))
            im = background
        elif im.mode != "RGB":
            im = im.convert("RGB")

        longest = max(im.width, im.height)
        if longest > PDF_EDGE:
            scale = PDF_EDGE / longest
            im = im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))), PILImage.Resampling.LANCZOS)

        if rotation:
            # Positive rotation is clockwise visually, matching the browser canvas.
            im = im.rotate(-rotation, expand=True)

        max_w = 3.35 * 72
        max_h = 2.35 * 72
        ratio = min(max_w / im.width, max_h / im.height)
        _draw_pdf_annotations(im, annotations, im.width * ratio, im.height * ratio)
        im.save(output, format="JPEG", quality=82, optimize=True, progressive=True)

    return output


def build_pdf(data: dict, pdf_path: Path) -> None:
    styles = getSampleStyleSheet()
    normal = ParagraphStyle(
        "Normal2", parent=styles["Normal"], fontName="Helvetica",
        fontSize=9, leading=12, textColor=colors.HexColor("#222222"),
    )
    small = ParagraphStyle("Small", parent=normal, fontSize=7.5, leading=9)
    section_style = ParagraphStyle(
        "Section", parent=normal, fontName="Helvetica-Bold",
        fontSize=11, alignment=TA_CENTER, textColor=colors.white,
    )
    title_style = ParagraphStyle(
        "Title2", parent=normal, fontName="Helvetica-Bold",
        fontSize=18, leading=20, alignment=TA_CENTER,
    )
    label_style = ParagraphStyle("Label", parent=small, fontName="Helvetica-Bold")

    doc = SimpleDocTemplate(
        str(pdf_path), pagesize=letter,
        rightMargin=0.42 * inch, leftMargin=0.42 * inch,
        topMargin=0.38 * inch, bottomMargin=0.42 * inch,
    )
    story = []

    if PDF_LOGO.exists():
        lw, lh = image_size(PDF_LOGO, 1.65 * inch, 0.62 * inch)
        logo = RLImage(str(PDF_LOGO), width=lw, height=lh)
    else:
        logo = Paragraph("", normal)

    header_table = Table(
        [[logo, Paragraph("REPAIR EVALUATION REPORT", title_style)]],
        colWidths=[1.9 * inch, 5.1 * inch],
    )
    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 1, colors.black),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 6))

    pdf_date = ""
    if data.get("date"):
        try:
            pdf_date = datetime.strptime(data["date"], "%Y-%m-%d").strftime("%m/%d/%Y")
        except ValueError:
            pdf_date = data["date"]

    info = [
        [Paragraph("<b>Date</b>", label_style), pdf_date,
         Paragraph("<b>Repair #</b>", label_style), data.get("repair_no", ""), "", ""],
        [Paragraph("<b>Customer</b>", label_style), data.get("customer", ""),
         Paragraph("<b>Customer Contact</b>", label_style), data.get("customer_contact", ""),
         Paragraph("<b>Customer Email</b>", label_style), data.get("customer_email", "")],
        [Paragraph("<b>Customer PO</b>", label_style), data.get("customer_po", ""),
         Paragraph("<b>Customer Part Number</b>", label_style), "", data.get("material", ""), ""],
        [Paragraph("<b>Make / Model</b>", label_style), data.get("model", ""),
         Paragraph("<b>Serial Number / Previous Repair Number</b>", label_style), "", data.get("serial", ""), ""],
        [Paragraph("<b>Technician</b>", label_style), data.get("technician", ""), "", "", "", ""],
    ]

    info_col_widths = [1.15 * inch, 2.00 * inch, 0.78 * inch, 0.99 * inch, 0.78 * inch, 1.40 * inch]
    t = Table(info, colWidths=info_col_widths)
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.6, colors.black),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#e9eef1")),
        ("BACKGROUND", (2, 0), (2, 1), colors.HexColor("#e9eef1")),
        ("BACKGROUND", (4, 1), (4, 1), colors.HexColor("#e9eef1")),
        ("SPAN", (2, 2), (3, 2)),
        ("SPAN", (4, 2), (5, 2)),
        ("SPAN", (2, 3), (3, 3)),
        ("SPAN", (4, 3), (5, 3)),
        ("BACKGROUND", (2, 2), (3, 3), colors.HexColor("#e9eef1")),
        ("SPAN", (3, 0), (5, 0)),
        ("SPAN", (2, 4), (5, 4)),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(t)
    story.append(Spacer(1, 8))

    def section_block(title, text):
        heading = Table([[Paragraph(title, section_style)]], colWidths=[7.1 * inch])
        heading.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#6d8fa0")),
            ("BOX", (0, 0), (-1, -1), 0.6, colors.black),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        body_text = _escape(text or "").replace("\n", "<br/>")
        body = Table([[Paragraph(body_text or "&nbsp;", normal)]], colWidths=[7.1 * inch])
        body.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.6, colors.black),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]))
        return [heading, body, Spacer(1, 7)]

    story.extend(section_block("CUSTOMER REQUEST / REPORTED PROBLEM", data.get("customer_request", "")))
    story.extend(section_block("REPAIR EVALUATION / FINDINGS", data.get("findings", "")))

    photos = data.get("photos", []) or []
    with tempfile.TemporaryDirectory(prefix="ifp_repair_pdf_") as temp_dir:
        if photos:
            appendix_heading = Table(
                [[Paragraph("PHOTOGRAPHIC DOCUMENTATION", section_style)]], colWidths=[7.1 * inch]
            )
            appendix_heading.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#6d8fa0")),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.black),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]))
            story.append(appendix_heading)
            story.append(Spacer(1, 6))

            def make_photo_cell(photo, number, max_w, max_h):
                pdf_photo_path = _pdf_image_path(photo, temp_dir)
                if Path(pdf_photo_path).exists():
                    w, h = image_size(pdf_photo_path, max_w, max_h)
                    img = RLImage(str(pdf_photo_path), width=w, height=h)
                else:
                    img = Paragraph("Image unavailable", normal)

                title = Paragraph(f"<b>PHOTO {number}</b>", normal)
                desc_text = _escape(photo.get("description", "") or "No description provided.")
                desc = Paragraph(desc_text.replace("\n", "<br/>"), small)
                return Table(
                    [[title], [img], [Paragraph("<b>Description:</b>", small)], [desc]],
                    colWidths=[max_w + 0.13 * inch],
                    rowHeights=[0.28 * inch, max_h + 0.07 * inch, 0.22 * inch, 0.55 * inch],
                    style=TableStyle([
                        ("BOX", (0, 0), (-1, -1), 0.7, colors.black),
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#8be9f5")),
                        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 4),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                        ("TOPPADDING", (0, 0), (-1, -1), 3),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ]),
                )

            row_style = TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 2),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ])

            if len(photos) == 1:
                cell = make_photo_cell(photos[0], 1, max_w=3.35 * inch, max_h=1.85 * inch)
                story.append(KeepTogether(cell))
            else:
                for start in range(0, len(photos), 4):
                    page_photos = photos[start:start + 4]
                    cells = [
                        make_photo_cell(photo, start + i + 1, max_w=3.35 * inch, max_h=2.35 * inch)
                        for i, photo in enumerate(page_photos)
                    ]
                    if len(cells) == 1:
                        story.append(KeepTogether(cells[0]))
                    elif len(cells) == 2:
                        row = Table([cells], colWidths=[3.55 * inch, 3.55 * inch])
                        row.setStyle(row_style)
                        story.append(KeepTogether(row))
                    elif len(cells) == 3:
                        row1 = Table([[cells[0], cells[1]]], colWidths=[3.55 * inch, 3.55 * inch])
                        row1.setStyle(row_style)
                        story.append(KeepTogether(row1))
                        story.append(Spacer(1, 4))
                        story.append(KeepTogether(cells[2]))
                    else:
                        grid = Table(
                            [[cells[0], cells[1]], [cells[2], cells[3]]],
                            colWidths=[3.55 * inch, 3.55 * inch],
                        )
                        grid.setStyle(row_style)
                        story.append(KeepTogether(grid))

        title_text = report_title(data)

        def footer(canvas, doc_):
            canvas.saveState()
            canvas.setFont("Helvetica", 7)
            canvas.setFillColor(colors.HexColor("#666666"))
            canvas.drawString(0.42 * inch, 0.22 * inch, f"IFP Motion Solutions • {title_text}")
            canvas.drawRightString(8.08 * inch, 0.22 * inch, f"Page {doc_.page}")
            canvas.restoreState()

        doc.build(story, onFirstPage=footer, onLaterPages=footer)
