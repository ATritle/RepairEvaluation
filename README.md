# IFP Repair Evaluation App

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

   `pip install -r requirements.txt`

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
