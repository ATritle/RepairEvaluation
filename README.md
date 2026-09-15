# IFP Repair Evaluation App

Documents repair evaluations and generates professional PDF reports.

Browser-based app on a local web server (FastAPI). It replaces the original
PyQt6 desktop app, which lives on the `main` branch; the PDF layout and photo
markup behaviour were ported from it unchanged.

## Web version (localhost)

### Quick start (Windows)

Double-click `run_web.bat`. It creates a `.venv`, installs `requirements.txt`,
starts the server on http://localhost:6969 and opens your browser.

### Manual start

Use a virtual environment; the shared global Python on the dev box has drifted
before (Starlette upgraded under an older FastAPI) and broke the import.

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
  Size 25–300 % (default 250 %), Colour drop-down (10 colours, default red;
  changing it recolours the selected symbol), Clear Markups
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

PHOTO_FS_ROOT=\\eha-serv.ifp.eha\data\Dwgs   # the drawings root on the N drive (N:\Dwgs)
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
  load it. A number nobody has used starts a new evaluation. Typing just the
  digits is fine: `36169` becomes `R36169` everywhere (form, phone page, API).
- **Every Save is a new revision.** Nothing is updated in place. The banner
  above the form shows which revision is loaded; **History** lists all
  revisions and lets you view any of them. Saving while viewing an old
  revision creates a new latest revision from that version.
- **Stale-save warning.** If someone else saved a newer revision while you
  were editing, Save stops and tells you who and when; you can look at their
  revision or save anyway as the next one.
- **Delete is a soft delete.** The evaluation disappears from lists and
  lookups but every revision is kept; "Show deleted" in the Open dialog lists
  them with a Restore button. Saving a deleted repair number restores it.
- **Photos live in the repair's drawing folder on the N drive.** The folder is
  the library: `N:\Dwgs\R36000\R36169\Photos\` (series = R-number rounded down
  to the thousand, then the job folder). Whatever is in that folder shows up in
  the app, whether it came from the phone page, the desktop uploader or
  Explorer. Uploads are normalised on the way in (EXIF rotation, 2000 px
  longest edge, JPEG 82) and named `<yyyymmdd-HHMMSS>_<original>.jpg`. The
  series and job folders must already exist; the app creates only `Photos`,
  `Photos\.archive`, `Photos\.removed` and `Reports`. Non-R-numbers and
  missing folders are refused with a clear message.
- **Saved revisions are immutable.** On Save, each photo on the report is
  normalised, hashed and copied once into `Photos\.archive\<sha256>.jpg`; the
  revision references that snapshot, so renaming or removing a file in the
  live folder never changes history. Saving the same photo on ten revisions
  stores it once. The PDF is also written to `Reports\<R> rev<N>.pdf`.
- "Remove from library" moves the file into `Photos\.removed`; nothing is
  ever deleted by the app.
- `PHOTO_FS_ROOT` is the Dwgs share as a UNC path, not the `N:` letter, so a
  service account can reach it. `data/thumbs/` is a local thumbnail cache.

Tables: `evaluation` (repair number, current revision, soft-delete stamp),
`revision` (all form fields + saved_at / saved_by), `revision_photo` (snapshot
hash + archive path, order, description, rotation), `photo_annotation`
(symbol, x, y, size, colour per markup).

**Who did it.** `saved_by` is the signed-in Windows account,
`jsmith (John Smith)` (see Sign-in below). With `AUTH_ENABLED=false` (dev
only) the phone page falls back to a technician picker and records
`NAME @client-address`.

### Links

The address bar follows what is loaded, so a link can be copied at any time:

```
/r/R123456        the evaluation, latest revision
/r/R123456/v2     revision 2 (read as it was; saving creates a new latest)
/mobile/R123456   phone capture page pre-filled (follows the Repair # field)
```

Opening either `/r/...` form loads that evaluation directly. The same shape
works on the API: `/api/evaluations/R123456/latest`, `/api/evaluations/R123456/v2`,
and `.../pdf` on either for the report.

### Photo library and phone capture (`/mobile`)

- **`/mobile`** is a phone-sized page: enter the repair number (or open
  `/mobile/R123456`, e.g. from a QR code; the address bar follows the field),
  then **Take Photo** or **Choose Photos**. Photos are shrunk on the phone
  before upload (a 20 MB shot leaves as about 1 MB), queued, retried three
  times on a flaky connection, and land in the repair's `Photos` folder. The
  page shows the folder's contents and flags photos already on the saved report.
- In the evaluation form, **📚 Photo Library** shows the folder with
  thumbnails; click to select, **Add selected to report**. **📱 Phone Upload**
  opens `/mobile` pre-filled. **+ ADD PHOTO** uploads into the same folder.

Endpoints: `GET /api/repairs/{repair_no}/folder`, `GET /api/repairs/{repair_no}/photos`,
`POST /api/photos` and `POST /api/mobile/photos` (form `repair_no` + `files[]`),
`DELETE /api/repairs/{repair_no}/photos/{name}`; images at
`/repairs/{repair_no}/photos/{name}` and `/repairs/{repair_no}/archive/{sha}`
(`?thumb=1` for a thumbnail).

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
  photo_store.py  where photo bytes live (fs folder / db), per-row
  settings.py     .env settings (P21 + Forge)
  images.py       photo normalisation
  pdf_builder.py  ReportLab PDF (ported from main.py)
static/
  index.html, style.css, app.js   the browser UI
  mobile.html, mobile.js          phone capture page (/mobile)
assets/           logos
```

### API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/config` | technicians + symbols |
| GET | `/api/evaluations?q=` | list / search evaluations (latest revision each) |
| GET | `/api/evaluations/{repair_no}` | latest revision (`?revision=n` still accepted) |
| GET | `/api/evaluations/{repair_no}/latest` | latest revision, explicit |
| GET | `/api/evaluations/{repair_no}/v{n}` | revision n |
| GET | `/api/evaluations/{repair_no}/revisions` | revision history |
| POST | `/api/evaluations` | save = append a revision (body = report JSON) |
| DELETE | `/api/evaluations/{repair_no}` | delete an evaluation and all revisions |
| GET | `/api/storage/status` | Forge connectivity check |
| POST | `/api/photos` | upload images (multipart `files`, optional `repair_no` to file in the library) |
| POST | `/api/mobile/photos` | phone upload: `repair_no` + `files[]` into the library |
| GET | `/api/repairs/{repair_no}/photos` | photo library for a repair number |
| DELETE | `/api/repairs/{repair_no}/photos/{file}` | remove a photo from the library (soft) |
| POST | `/api/pdf?download=0|1` | build a PDF from the posted report |
| GET | `/api/evaluations/{repair_no}/pdf` or `/latest/pdf` | PDF of the latest revision (`?download=1` for attachment) |
| GET | `/api/evaluations/{repair_no}/v{n}/pdf` | PDF of revision n |
| GET | `/api/p21/status` | P21 connectivity check |
| GET | `/api/p21/customers?q=` | P21 customer type-ahead |
| GET | `/api/p21/customers/{id}/contacts` | contacts for one P21 customer |

Interactive docs: http://localhost:6969/docs
