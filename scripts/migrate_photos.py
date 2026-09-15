"""Move saved revisions onto folder-first photo references (one-off, 2026-09).

For every revision_photo row still using the legacy photo_file link:
  * find the bytes (photo_file.path, absolute or relative to the old root, or
    the VARBINARY column)
  * normalise, hash, copy into <Dwgs>\\R36000\\R36169\\Photos\\.archive\\<sha>.jpg
  * set sha256 / archive_path / source_name on the row
Revisions whose repair has no drawing folder cannot be archived; the script
reports them. Test evaluations (RTEST-*, R123456) are removed with --drop-tests.
Legacy tables are dropped only with --drop-legacy, and only if nothing still
depends on them.

    .venv\\Scripts\\python scripts\\migrate_photos.py --dry-run
    .venv\\Scripts\\python scripts\\migrate_photos.py --drop-tests --drop-legacy
"""
import argparse
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pyodbc  # noqa: E402

from app.images import normalize_image_bytes  # noqa: E402
from app.photos import PhotoLocationError, archive_file, fs_root, rel_to_root  # noqa: E402
from app.settings import get_settings  # noqa: E402

LEGACY_ROOT = Path(r"\\eha-serv.ifp.eha\data\Apps\RepairEval\photos")
TEST_PATTERNS = ("RTEST-%", "R123456")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--drop-tests", action="store_true", help="delete RTEST-* and R123456 evaluations outright")
    ap.add_argument("--drop-legacy", action="store_true", help="drop repair_photo and photo_file when no row needs them")
    args = ap.parse_args()

    st = get_settings()
    s = st.forge_schema
    cn = pyodbc.connect(st.forge_connection_string)
    cur = cn.cursor()

    if args.drop_tests:
        for pat in TEST_PATTERNS:
            cur.execute(f"SELECT repair_no FROM {s}.evaluation WHERE repair_no LIKE ?", [pat])
            for (rn,) in cur.fetchall():
                print(f"  drop test evaluation {rn}")
                if not args.dry_run:
                    cur.execute(f"DELETE FROM {s}.evaluation WHERE repair_no = ?", [rn])   # cascades revisions/photos
            if not args.dry_run:
                cur.execute(f"DELETE FROM {s}.repair_photo WHERE repair_no LIKE ?", [pat])

    cur.execute(f"""
        SELECT vp.revision_photo_id, e.repair_no, vp.file_name, vp.display_name, pf.storage, pf.path, pf.content
        FROM {s}.revision_photo vp
        JOIN {s}.revision r ON r.revision_id = vp.revision_id
        JOIN {s}.evaluation e ON e.evaluation_id = r.evaluation_id
        LEFT JOIN {s}.photo_file pf ON pf.file_name = vp.file_name
        WHERE vp.sha256 IS NULL""")
    rows = cur.fetchall()
    done = skipped = 0
    for rp_id, repair_no, file_name, display_name, storage, path, content in rows:
        data = None
        if content is not None:
            data = bytes(content)
        elif path:
            for cand in (Path(path), fs_root() / path, LEGACY_ROOT / path):
                if cand.exists():
                    data = cand.read_bytes()
                    break
        if data is None:
            print(f"  !! {repair_no}: bytes for {file_name} not found; row left as is"); skipped += 1; continue
        try:
            jpeg, _w, _h = normalize_image_bytes(data)
            sha = hashlib.sha256(jpeg).hexdigest()
            target = archive_file(repair_no, sha, create_dir=not args.dry_run)
        except PhotoLocationError as exc:
            print(f"  !! {repair_no}: {exc}; row left as is"); skipped += 1; continue
        if not args.dry_run:
            if not target.exists():
                tmp = target.with_suffix(".jpg.part"); tmp.write_bytes(jpeg); tmp.replace(target)
            cur.execute(
                f"UPDATE {s}.revision_photo SET sha256 = ?, archive_path = ?, source_name = COALESCE(source_name, ?) WHERE revision_photo_id = ?",
                [sha, rel_to_root(target), display_name, rp_id],
            )
        done += 1
        print(f"  {repair_no}: {display_name or file_name} -> .archive/{sha[:12]}…")

    if args.drop_legacy:
        cur.execute(f"SELECT COUNT(*) FROM {s}.revision_photo WHERE sha256 IS NULL")
        pending = cur.fetchone()[0]
        if pending:
            print(f"  not dropping legacy tables: {pending} revision photo(s) still unmigrated")
        elif not args.dry_run:
            cur.execute(f"IF OBJECT_ID('{s}.repair_photo', 'U') IS NOT NULL DROP TABLE {s}.repair_photo")
            cur.execute(f"IF OBJECT_ID('{s}.photo_file', 'U') IS NOT NULL DROP TABLE {s}.photo_file")
            cur.execute(f"IF COL_LENGTH('{s}.revision_photo', 'file_name') IS NOT NULL ALTER TABLE {s}.revision_photo DROP COLUMN file_name")
            print("  dropped repair_photo, photo_file and revision_photo.file_name")

    if not args.dry_run:
        cn.commit()
    print(f"\ndone: {done} archived, {skipped} skipped" + (" (dry run)" if args.dry_run else ""))


if __name__ == "__main__":
    main()
