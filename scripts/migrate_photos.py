"""Move photo bytes into the repair drawing folders on the N drive.

For every photo_file row:
  * find its repair number (library row, else the evaluation that uses it)
  * if <root>\\R36000\\R36169 exists: write/copy the file into its Photos folder
    and set storage='fs', path='R36000/R36169/Photos/<file>'
  * otherwise (non R-number, or job folder missing): if the bytes are still in
    Forge, or the file sits under --legacy-root, leave it there and record an
    absolute path so it still serves. Reported so someone can create the folder
    and re-run.

Safe to re-run. Nothing is deleted from the old location.

    .venv\\Scripts\\python scripts\\migrate_photos.py --legacy-root "\\\\eha-serv.ifp.eha\\data\\Apps\\RepairEval\\photos" --legacy-root data\\photo_store
"""
import argparse
import hashlib
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pyodbc  # noqa: E402

from app.photo_store import PhotoLocationError, _resolve_photos_dir_sync, fs_root  # noqa: E402
from app.settings import get_settings  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--legacy-root", action="append", default=[], help="previous photo root(s) to look in")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    st = get_settings()
    s = st.forge_schema
    root = fs_root()
    legacy = [Path(r) for r in args.legacy_root]
    print(f"target root: {root}")

    cn = pyodbc.connect(st.forge_connection_string)
    cur = cn.cursor()
    cur.execute(f"""
        SELECT pf.file_name, pf.storage, pf.path, pf.sha256, pf.content,
               COALESCE(
                 (SELECT TOP 1 rp.repair_no FROM {s}.repair_photo rp WITH (NOLOCK) WHERE rp.file_name = pf.file_name ORDER BY rp.removed_at DESC, rp.uploaded_at DESC),
                 (SELECT TOP 1 e.repair_no FROM {s}.revision_photo vp WITH (NOLOCK)
                    JOIN {s}.revision r WITH (NOLOCK) ON r.revision_id = vp.revision_id
                    JOIN {s}.evaluation e WITH (NOLOCK) ON e.evaluation_id = r.evaluation_id
                   WHERE vp.file_name = pf.file_name ORDER BY r.saved_at DESC)
               ) AS repair_no
        FROM {s}.photo_file pf WITH (NOLOCK)""")
    rows = cur.fetchall()
    placed = kept = already = orphan = 0

    for file_name, storage, path, sha, content, repair_no in rows:
        storage = (storage or "db").strip()
        # current bytes: from Forge, or from wherever the row / legacy roots say
        src: Path | None = None
        if storage == "fs" and path:
            cand = Path(path) if Path(path).is_absolute() else root / path
            if cand.exists():
                src = cand
            else:
                for lr in legacy:
                    if (lr / path).exists():
                        src = lr / path
                        break
        data = bytes(content) if content is not None else (src.read_bytes() if src else None)
        if data is None:
            print(f"  !! {file_name}: bytes not found anywhere (repair {repair_no})"); orphan += 1; continue

        try:
            if not repair_no:
                raise PhotoLocationError("no repair number references this photo")
            photos_dir = _resolve_photos_dir_sync(repair_no, create=not args.dry_run)
        except PhotoLocationError as exc:
            # leave where it is, but make the row self-sufficient (absolute path)
            if src and not (storage == "fs" and Path(path or "").is_absolute()):
                if not args.dry_run:
                    cur.execute(f"UPDATE {s}.photo_file SET storage='fs', path=?, content=NULL WHERE file_name=?",
                                [str(src.resolve()), file_name])
                print(f"  kept      {file_name} at {src}  ({exc})")
            else:
                print(f"  kept      {file_name} ({'in Forge' if storage == 'db' else src})  ({exc})")
            kept += 1
            continue

        target = photos_dir / file_name
        rel = str(target.relative_to(root)).replace("\\", "/")
        if target.exists() and path == rel:
            already += 1
            continue
        if not args.dry_run:
            if not target.exists():
                if src:
                    shutil.copy2(src, target)
                else:
                    tmp = target.with_suffix(".jpg.part"); tmp.write_bytes(data); tmp.replace(target)
            if sha and hashlib.sha256(target.read_bytes()).hexdigest() != sha:
                print(f"  !! {file_name}: sha mismatch after copy, row left unchanged"); orphan += 1; continue
            cur.execute(f"UPDATE {s}.photo_file SET storage='fs', path=?, content=NULL WHERE file_name=?", [rel, file_name])
        placed += 1
        print(f"  -> {rel}")

    if not args.dry_run:
        cn.commit()
    print(f"\ndone: {placed} placed in drawing folders, {already} already there, {kept} kept where they were, {orphan} problems"
          + (" (dry run)" if args.dry_run else ""))


if __name__ == "__main__":
    main()
