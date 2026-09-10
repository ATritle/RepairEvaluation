"""Move photo bytes to the configured PHOTO_FS_ROOT.

Handles both cases:
  * rows with storage='db'  -> write the VARBINARY to the root, mark the row
                               storage='fs' with its relative path, null the blob
  * rows with storage='fs'  -> make sure the file exists under the current root;
                               if it only exists under --from-root, copy it over

Safe to re-run. Nothing is deleted from the old location.

    .venv\\Scripts\\python scripts\\migrate_photos.py --from-root data/photo_store
"""
import argparse
import hashlib
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pyodbc  # noqa: E402

from app.photo_store import fs_root  # noqa: E402
from app.settings import get_settings  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-root", help="previous PHOTO_FS_ROOT to copy existing fs files from")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    st = get_settings()
    root = fs_root()
    old = Path(args.from_root).resolve() if args.from_root else None
    print(f"target root: {root}")
    root.mkdir(parents=True, exist_ok=True)

    cn = pyodbc.connect(st.forge_connection_string)
    cur = cn.cursor()
    cur.execute(f"SELECT file_name, storage, path, sha256, content FROM {st.forge_schema}.photo_file")
    rows = cur.fetchall()
    moved = copied = ok = missing = 0

    for file_name, storage, path, sha, content in rows:
        storage = (storage or "db").strip()
        if storage == "db":
            if content is None:
                print(f"  !! {file_name}: storage=db but no content"); missing += 1; continue
            rel = f"{datetime.now():%Y/%m}/{file_name}"
            target = root / rel
            if not args.dry_run:
                target.parent.mkdir(parents=True, exist_ok=True)
                tmp = target.with_suffix(".jpg.part"); tmp.write_bytes(bytes(content)); tmp.replace(target)
                if sha and hashlib.sha256(bytes(content)).hexdigest() != sha:
                    print(f"  !! {file_name}: sha mismatch, leaving row as db"); continue
                cur.execute(
                    f"UPDATE {st.forge_schema}.photo_file SET storage='fs', path=?, content=NULL WHERE file_name=?",
                    [rel, file_name],
                )
            moved += 1
            print(f"  db -> fs  {rel}")
        else:
            target = root / path
            if target.exists():
                ok += 1
                continue
            src = (old / path) if old else None
            if src and src.exists():
                if not args.dry_run:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, target)
                copied += 1
                print(f"  copied    {path}")
            else:
                print(f"  !! {file_name}: not found at {target}" + (f" or {src}" if src else ""))
                missing += 1

    if not args.dry_run:
        cn.commit()
    print(f"\ndone: {moved} moved from db, {copied} copied from old root, {ok} already present, {missing} missing"
          + (" (dry run)" if args.dry_run else ""))


if __name__ == "__main__":
    main()
