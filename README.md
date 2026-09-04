# IFP Repair Evaluation App

Documents repair evaluations and generates professional PDF reports.

This branch (**Web-Version**) adds a browser-based version that runs on a local
web server (FastAPI). The original PyQt6 desktop app (`main.py`) is still in
the repo and unchanged.

## Web version (localhost)

### Quick start (Windows)

Double-click `run_web.bat`. It creates a `.venv`, installs `requirements.txt`,
starts the server on http://localhost:6969 and opens your browser.

### Manual start

```
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 6969
```

Open http://localhost:6969.

### What the web version does

Same workflow as the desktop app:

- Repair information grid (same fields and layout, fixed technician list)
- Customer Request / Reported Problem and Repair Evaluation / Findings
- Unlimited photos (file picker or drag-and-drop onto the page), reorder, remove
- Rotate 90° left/right, reset rotation
- Photo markup on an HTML canvas: arrows, circle, square, rectangle, X, check
  mark; click to place, click to select, drag to move, Delete to remove,
  Size 25–300 % (default 250 %), Clear Markups
- Open Photo / Zoom dialog with a 25–300 % zoom slider
- Save / Open evaluations in Forge with full revision history (see below)
- Preview PDF (in-page viewer) and Print / Save PDF (download)
- Help menu (How to Use, Photo Markup, Keyboard Shortcuts, About)
- Shortcuts: Ctrl+S save, Ctrl+O open, Ctrl+P preview, F1 help
  (Ctrl+N is usually taken by the browser)

The PDF layout and symbol geometry are ported line-for-line from the desktop
app, so reports look the same.

### Prophet 21 integration (customer / contact / email)

The Customer field is a type-ahead against P21. Customers and contacts are
always shown as `# - name` (P21 id, dash, name). Picking a customer:

- stores the P21 `customer_id` with the report and shows a `P21 #id` tag
- turns Customer Contact into a drop-down of **that customer's contacts only**:
  the Customer Maintenance contact links (`oe_contacts_customer`, the same list
  order entry offers), plus contacts on the customer's corporate address and
  contacts linked to its ship-to addresses. Deleted customers, contacts, links
  and ship-tos are excluded.
- fills Customer Email from the chosen contact and greys it out. An
  **Override** check box to the right of the label un-greys the field so a
  different address can be typed. Un-checking it asks "Are you sure?" and, on
  Yes, puts the P21 email back. The override flag is saved with the report.

Typing in the Customer box after a pick breaks the link and the fields go
back to free text. If P21 is unreachable or no credentials are configured the
form shows "P21 offline, free text" and behaves exactly like before.

Connection settings live in `.env` (copy `.env.example`):

```
P21_SERVER=sql19
P21_DATABASE=Prophet21
P21_USER=<read-only login>
P21_PASSWORD=<password>
P21_DRIVER=ODBC Driver 17 for SQL Server
P21_COMPANY_ID=        # optional filter

FORGE_SERVER=sql19
FORGE_DATABASE=Forge
FORGE_SCHEMA=RepairEval
FORGE_USER=<login with read/write on Forge.RepairEval>
FORGE_PASSWORD=<password>
```

All P21 queries are SELECT-only with `WITH (NOLOCK)`, run through a read-only
pyodbc connection. Endpoints: `GET /api/p21/status`,
`GET /api/p21/customers?q=`, `GET /api/p21/customers/{id}/contacts`.

### Where data is stored (Forge)

Evaluations live in the **Forge** database, schema **`RepairEval`**
(`sql/001_repaireval_schema.sql`, fully qualified so it can be run from
`master` in SSMS; the app can also run it with a db_owner login).

- **One evaluation per repair number.** The Repair # is the first field and
  doubles as the lookup: type it and matching evaluations appear; pick one to
  load it. A number nobody has used starts a new evaluation.
- **Every Save is a new revision.** Nothing is updated in place. The banner
  above the form shows which revision is loaded; **History** lists all
  revisions and lets you view any of them. Saving while viewing an old
  revision creates a new latest revision from that version.
- Photo bytes are stored in Forge too (`RepairEval.photo_file`, shared across
  revisions by file name). `data/photos/` is only a local cache.

Tables: `evaluation` (repair number, current revision), `revision` (all form
fields + saved_at / saved_by), `revision_photo` (order, description,
rotation), `photo_annotation` (symbol, x, y, size per markup), `photo_file`
(JPEG bytes).

`saved_by` records the client address for now; switch it to the login name
once the app sits behind authentication (the `X-Forwarded-User` header is
honoured if a proxy supplies it).

### Input hardening

All SQL is parameterised (pyodbc `?` placeholders); table names come from
configuration, never from requests. Free text is scrubbed in the Pydantic
models (control characters removed, CRLF normalised, lengths capped to the
column sizes), LIKE searches escape `% _ [`, photo references must match the
server-generated `<32 hex>.jpg` pattern, P21 ids must be numeric, and Repair #
is limited to letters, digits, space, `. _ / -`. Text is escaped before it is
placed in the PDF or rendered in the page.

### Layout

```
app/
  main.py         FastAPI app + API routes
  config.py       paths, technician list, symbol list
  schemas.py      Pydantic models (Report, Photo, Annotation)
  forge.py        Forge (RepairEval schema) storage
  settings.py     .env settings (P21 + Forge)
  images.py       photo normalisation
  pdf_builder.py  ReportLab PDF (ported from main.py)
static/
  index.html, style.css, app.js   the browser UI
assets/           logos (shared with the desktop app)
main.py           original desktop app (PyQt6)
```

### API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/config` | technicians + symbols |
| GET | `/api/evaluations?q=` | list / search evaluations (latest revision each) |
| GET | `/api/evaluations/{repair_no}?revision=n` | load latest (or a specific) revision |
| GET | `/api/evaluations/{repair_no}/revisions` | revision history |
| POST | `/api/evaluations` | save = append a revision (body = report JSON) |
| DELETE | `/api/evaluations/{repair_no}` | delete an evaluation and all revisions |
| GET | `/api/storage/status` | Forge connectivity check |
| POST | `/api/photos` | upload one or more images (multipart `files`) |
| POST | `/api/pdf?download=0|1` | build a PDF from the posted report |
| GET | `/api/evaluations/{repair_no}/pdf?revision=n` | build a PDF from a saved revision |
| GET | `/api/p21/status` | P21 connectivity check |
| GET | `/api/p21/customers?q=` | P21 customer type-ahead |
| GET | `/api/p21/customers/{id}/contacts` | contacts for one P21 customer |

Interactive docs: http://localhost:6969/docs

---

# Desktop version (original)

A Windows desktop application for documenting repair evaluations and generating professional PDF reports.

## Features

- Manual Repair # field (the app does not generate repair numbers)
- Date, technician, customer, Make/Model, serial number and optional order information
- Customer request and evaluation/findings
- Unlimited photographs with individual descriptions
- Drag/reorder photos
- Photo rotation
- Save and reopen editable evaluation files
- PDF preview through the system PDF viewer
- PDF generation using ReportLab
- Separate application and PDF logos: `assets/ifp_logo_app.png` for the app and `assets/ifp_logo.png` for PDF reports
- Dark/orange PyQt6 interface

## Run from source

1. Install Python 3.12+.
2. Open a terminal in this folder.
3. Create a virtual environment:

   `python -m venv .venv`

4. Activate it:

   Windows PowerShell:
   `.venv\Scripts\Activate.ps1`

5. Install dependencies:

   `pip install -r requirements-desktop.txt`

6. Start the application:

   `python main.py`

## Build a Windows EXE

Run:

`build.bat`

The finished executable will be placed in:

`dist\RepairEvaluationApp.exe`

## Saved reports

Evaluation files use JSON and are saved wherever you choose. Photographs are copied into a companion folder beside the JSON file so the report remains portable.

Example:

`R12345.json`
`R12345_photos\photo_001.jpg`
`R12345_photos\photo_002.jpg`

## PDF layout

The generated report is designed around the supplied service inspection example:
- Page 1: report information, request and findings
- Following pages: photographic documentation, four photos per page

The Repair # is always entered manually.

### PDF photo rotation
Photo rotations made in the application are applied to the generated PDF preview/export using the same clockwise direction as the app, so the PDF matches the orientation shown in the app.

### Photo markups

Each photo has an **Add Symbol** drop-down. Choose an arrow direction, circle,
square, rectangle, X, or check mark, then click directly on the image to place
the symbol. Markups are saved with the evaluation and are rendered into both
PDF Preview and the exported PDF. **Clear Markups** removes all symbols from
the selected photo.

### Resizable symbols

Symbols have a **Size** control from 25% to 300%, with **250% as the default size**. The size applies to the next
symbol placed. Clicking an existing symbol selects it; changing Size then
resizes that selected symbol. The selected symbol is highlighted on the photo.
The selected size is stored with the report and is reproduced in the PDF.

The PDF header field order matches the application layout exactly.
PDF symbol sizing uses the displayed photo geometry and each annotation's saved percentage size.

Photo annotations (symbol type, position, and size) are persisted in the JSON evaluation file.

### Photo compression

Photos are normalized on upload, limited to a 2000-pixel longest edge, and
stored as optimized JPEG quality 82. PDF images with or without markups are
also encoded as optimized JPEGs to keep report files much smaller while
remaining suitable for normal repair-report printing.

### Technician list

Technician is a fixed dropdown using the provided list.
The Received Condition section is temporarily removed from the app and PDF.

Customer Contact is split into two side-by-side fields: Customer Contact and Customer Email.

The PDF information grid mirrors the application layout, including the split Customer Contact / Customer Email row.

The report-information layout uses a narrower left column and wider right column to provide more room for Customer Email.
