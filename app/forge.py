"""Forge storage for evaluations (schema RepairEval).

One evaluation per repair number; every save appends a revision. Photo bytes
are NOT here: a revision references content-hashed snapshots in the repair's
drawing folder (see photos.py). Deleting an evaluation is a soft delete.
pyodbc is synchronous, so the async wrappers run the work in a thread.
"""
import asyncio
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import pyodbc

from .settings import get_settings


class ForgeUnavailable(Exception):
    """Forge is not configured or cannot be reached."""


class NotFound(Exception):
    pass


class StaleSave(Exception):
    """Someone else saved a newer revision since this one was loaded."""

    def __init__(self, current_revision_no: int, saved_at: Optional[str], saved_by: Optional[str]):
        super().__init__(f"Revision {current_revision_no} was saved by {saved_by or 'someone'} at {saved_at}")
        self.current_revision_no = current_revision_no
        self.saved_at = saved_at
        self.saved_by = saved_by


def _s() -> str:
    return get_settings().forge_schema


def _connect() -> pyodbc.Connection:
    st = get_settings()
    if not st.forge_configured:
        raise ForgeUnavailable("Forge credentials are not configured (see .env.example)")
    try:
        return pyodbc.connect(st.forge_connection_string, timeout=st.forge_timeout, autocommit=False)
    except pyodbc.Error as exc:
        raise ForgeUnavailable(f"Unable to connect to Forge: {str(exc)[:200]}") from exc


def like_escape(value: str) -> str:
    """Escape LIKE wildcards so user text matches literally (used with ESCAPE '\\')."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_").replace("[", "\\[")


def _rows(cur: pyodbc.Cursor) -> list[dict[str, Any]]:
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _iso(v: Any) -> Optional[str]:
    if isinstance(v, datetime):
        return v.isoformat(timespec="seconds")
    if isinstance(v, date):
        return v.isoformat()
    return v


# --------------------------------------------------------------------------
# Schema bootstrap
# --------------------------------------------------------------------------
def _run_schema_script_sync(path: Path) -> list[str]:
    """Execute a sql/*.sql script batch by batch (split on GO)."""
    sql = path.read_text(encoding="utf-8")
    batches = [b.strip() for b in _split_go(sql) if b.strip()]
    done = []
    with _connect() as cn:
        cn.autocommit = True
        cur = cn.cursor()
        for b in batches:
            cur.execute(b)
            done.append(b.splitlines()[0][:80])
    return done


def _split_go(sql: str) -> list[str]:
    out, cur = [], []
    for line in sql.splitlines():
        if line.strip().upper() == "GO":
            out.append("\n".join(cur))
            cur = []
        else:
            cur.append(line)
    out.append("\n".join(cur))
    return out


# --------------------------------------------------------------------------
# Evaluations
# --------------------------------------------------------------------------
SUMMARY_SQL = """
SELECT e.repair_no, e.current_revision_no, e.updated_at, e.deleted_at, e.deleted_by,
       r.eval_date, r.technician, r.customer, r.saved_at, r.saved_by,
       (SELECT COUNT(*) FROM {s}.revision_photo p WITH (NOLOCK) WHERE p.revision_id = r.revision_id) AS photo_count
FROM {s}.evaluation e WITH (NOLOCK)
JOIN {s}.revision r WITH (NOLOCK)
  ON r.evaluation_id = e.evaluation_id AND r.revision_no = e.current_revision_no
"""


def _summary(d: dict[str, Any]) -> dict[str, Any]:
    return {
        "repair_no": d["repair_no"],
        "customer": d.get("customer") or "",
        "date": _iso(d.get("eval_date")) or "",
        "technician": d.get("technician") or "",
        "photo_count": int(d.get("photo_count") or 0),
        "revision_count": int(d.get("current_revision_no") or 0),
        "updated_at": _iso(d.get("saved_at") or d.get("updated_at")),
        "saved_by": d.get("saved_by"),
        "deleted_at": _iso(d.get("deleted_at")),
        "deleted_by": d.get("deleted_by"),
    }


def _list_sync(limit: int, include_deleted: bool) -> list[dict[str, Any]]:
    where = "" if include_deleted else "WHERE deleted_at IS NULL"
    with _connect() as cn:
        cur = cn.cursor()
        cur.execute(f"SELECT TOP (?) * FROM ({SUMMARY_SQL.format(s=_s())}) x {where} ORDER BY updated_at DESC", [limit])
        return [_summary(d) for d in _rows(cur)]


def _search_sync(query: str, limit: int, include_deleted: bool) -> list[dict[str, Any]]:
    q = like_escape(query[:100])
    like = f"{q}%"
    contains = f"%{q}%"
    deleted = "" if include_deleted else "AND deleted_at IS NULL"
    with _connect() as cn:
        cur = cn.cursor()
        cur.execute(
            f"""SELECT TOP (?) * FROM ({SUMMARY_SQL.format(s=_s())}) x
                WHERE (repair_no LIKE ? ESCAPE '\\' OR customer LIKE ? ESCAPE '\\') {deleted}
                ORDER BY CASE WHEN repair_no LIKE ? ESCAPE '\\' THEN 0 ELSE 1 END, updated_at DESC""",
            [limit, contains, contains, like],
        )
        return [_summary(d) for d in _rows(cur)]


def _load_sync(repair_no: str, revision_no: Optional[int]) -> dict[str, Any]:
    s = _s()
    with _connect() as cn:
        cur = cn.cursor()
        cur.execute(
            f"SELECT evaluation_id, current_revision_no, deleted_at FROM {s}.evaluation WITH (NOLOCK) WHERE repair_no = ?",
            [repair_no],
        )
        ev = cur.fetchone()
        if ev is None:
            raise NotFound(f"No evaluation for repair number {repair_no}")
        evaluation_id, current, deleted_at = ev
        rev_no = revision_no if revision_no is not None else current
        cur.execute(
            f"SELECT * FROM {s}.revision WITH (NOLOCK) WHERE evaluation_id = ? AND revision_no = ?",
            [evaluation_id, rev_no],
        )
        rows = _rows(cur)
        if not rows:
            raise NotFound(f"Repair {repair_no} has no revision {rev_no}")
        r = rows[0]
        cur.execute(
            f"""SELECT revision_photo_id, seq, sha256, source_name, display_name, description, rotation
                FROM {s}.revision_photo WITH (NOLOCK) WHERE revision_id = ? ORDER BY seq""",
            [r["revision_id"]],
        )
        photos = _rows(cur)
        by_photo: dict[int, list[dict[str, Any]]] = {}
        if photos:
            ids = [p["revision_photo_id"] for p in photos]
            marks = ",".join("?" * len(ids))
            cur.execute(
                f"""SELECT revision_photo_id, symbol, x, y, size_pct, color
                    FROM {s}.photo_annotation WITH (NOLOCK)
                    WHERE revision_photo_id IN ({marks}) ORDER BY revision_photo_id, seq""",
                ids,
            )
            for a in _rows(cur):
                by_photo.setdefault(a["revision_photo_id"], []).append({
                    "symbol": a["symbol"], "x": float(a["x"]), "y": float(a["y"]),
                    "size": int(a["size_pct"]), "color": (a.get("color") or "#ff0000").strip(),
                })

    return {
        "repair_no": repair_no,
        "revision_no": int(r["revision_no"]),
        "current_revision_no": int(current),
        "saved_at": _iso(r["saved_at"]),
        "saved_by": r.get("saved_by"),
        "deleted_at": _iso(deleted_at),
        "date": _iso(r.get("eval_date")) or "",
        "technician": r.get("technician") or "",
        "customer": r.get("customer") or "",
        "customer_id": r.get("customer_id"),
        "customer_contact": r.get("customer_contact") or "",
        "contact_id": r.get("contact_id"),
        "customer_email": r.get("customer_email") or "",
        "email_override": bool(r.get("email_override")),
        "model": r.get("model") or "",
        "serial": r.get("serial") or "",
        "customer_po": r.get("customer_po") or "",
        "material": r.get("material") or "",
        "customer_request": r.get("customer_request") or "",
        "findings": r.get("findings") or "",
        "photos": [
            {
                "ref": f"archive:{(p['sha256'] or '').strip()}",
                "name": p.get("source_name") or p.get("display_name") or "",
                "description": p.get("description") or "",
                "rotation": int(p.get("rotation") or 0),
                "annotations": by_photo.get(p["revision_photo_id"], []),
            }
            for p in photos
            if (p.get("sha256") or "").strip()
        ],
    }


def _latest_shas_sync(repair_no: str) -> set[str]:
    """Snapshot hashes on the current revision (to flag library photos already on the report)."""
    s = _s()
    with _connect() as cn:
        cur = cn.cursor()
        cur.execute(
            f"""SELECT vp.sha256 FROM {s}.revision_photo vp WITH (NOLOCK)
                JOIN {s}.revision r WITH (NOLOCK) ON r.revision_id = vp.revision_id
                JOIN {s}.evaluation e WITH (NOLOCK) ON e.evaluation_id = r.evaluation_id
                WHERE e.repair_no = ? AND r.revision_no = e.current_revision_no AND vp.sha256 IS NOT NULL""",
            [repair_no],
        )
        return {row[0].strip() for row in cur.fetchall()}


def _revisions_sync(repair_no: str) -> list[dict[str, Any]]:
    s = _s()
    with _connect() as cn:
        cur = cn.cursor()
        cur.execute(
            f"""SELECT r.revision_no, r.saved_at, r.saved_by, r.technician, r.customer, r.eval_date,
                       (SELECT COUNT(*) FROM {s}.revision_photo p WITH (NOLOCK) WHERE p.revision_id = r.revision_id) AS photo_count
                FROM {s}.revision r WITH (NOLOCK)
                JOIN {s}.evaluation e WITH (NOLOCK) ON e.evaluation_id = r.evaluation_id
                WHERE e.repair_no = ?
                ORDER BY r.revision_no DESC""",
            [repair_no],
        )
        return [
            {
                "revision_no": int(d["revision_no"]),
                "saved_at": _iso(d["saved_at"]),
                "saved_by": d.get("saved_by"),
                "technician": d.get("technician") or "",
                "customer": d.get("customer") or "",
                "date": _iso(d.get("eval_date")) or "",
                "photo_count": int(d.get("photo_count") or 0),
            }
            for d in _rows(cur)
        ]


def _save_sync(data: dict[str, Any], saved_by: Optional[str], snapshots: list[dict[str, Any]],
               base_revision_no: Optional[int], force: bool) -> dict[str, Any]:
    """Append a revision for data['repair_no'] (creating or un-deleting the evaluation).

    `snapshots` is the photo list with each entry already frozen:
    {sha256, archive_path, source_name, description, rotation, annotations}.
    Raises StaleSave when the evaluation moved past base_revision_no and not force."""
    s = _s()
    repair_no = (data.get("repair_no") or "").strip()
    if not repair_no:
        raise ValueError("Repair # is required to save")

    eval_date = None
    if data.get("date"):
        try:
            eval_date = date.fromisoformat(data["date"])
        except ValueError:
            eval_date = None

    with _connect() as cn:
        cur = cn.cursor()
        try:
            # Lock the evaluation row for the duration of the save so two
            # concurrent saves cannot claim the same revision number.
            cur.execute(
                f"SELECT evaluation_id, current_revision_no FROM {s}.evaluation WITH (UPDLOCK, HOLDLOCK) WHERE repair_no = ?",
                [repair_no],
            )
            row = cur.fetchone()
            if row is None:
                cur.execute(f"INSERT INTO {s}.evaluation (repair_no) OUTPUT INSERTED.evaluation_id VALUES (?)", [repair_no])
                evaluation_id = int(cur.fetchone()[0])
                current = 0
            else:
                evaluation_id, current = int(row[0]), int(row[1])

            if not force and base_revision_no is not None and current != int(base_revision_no):
                cur.execute(
                    f"SELECT saved_at, saved_by FROM {s}.revision WITH (NOLOCK) WHERE evaluation_id = ? AND revision_no = ?",
                    [evaluation_id, current],
                )
                latest = cur.fetchone()
                cn.rollback()
                raise StaleSave(current, _iso(latest[0]) if latest else None, latest[1] if latest else None)

            next_rev = current + 1
            cur.execute(
                f"""INSERT INTO {s}.revision
                    (evaluation_id, revision_no, saved_by, eval_date, technician, customer, customer_id,
                     customer_contact, contact_id, customer_email, email_override, model, serial,
                     customer_po, material, customer_request, findings)
                    OUTPUT INSERTED.revision_id
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [
                    evaluation_id, next_rev, saved_by, eval_date,
                    data.get("technician") or None, data.get("customer") or None, data.get("customer_id") or None,
                    data.get("customer_contact") or None, data.get("contact_id") or None,
                    data.get("customer_email") or None, 1 if data.get("email_override") else 0,
                    data.get("model") or None, data.get("serial") or None,
                    data.get("customer_po") or None, data.get("material") or None,
                    data.get("customer_request") or None, data.get("findings") or None,
                ],
            )
            revision_id = int(cur.fetchone()[0])

            for seq, p in enumerate(snapshots, start=1):
                cur.execute(
                    f"""INSERT INTO {s}.revision_photo
                        (revision_id, seq, sha256, archive_path, source_name, display_name, description, rotation)
                        OUTPUT INSERTED.revision_photo_id VALUES (?,?,?,?,?,?,?,?)""",
                    [revision_id, seq, p["sha256"], p["archive_path"], (p.get("source_name") or "")[:260] or None,
                     (p.get("source_name") or "")[:260] or None, p.get("description") or None,
                     int(p.get("rotation") or 0) % 360],
                )
                photo_id = int(cur.fetchone()[0])
                anns = p.get("annotations") or []
                if anns:
                    cur.executemany(
                        f"""INSERT INTO {s}.photo_annotation (revision_photo_id, seq, symbol, x, y, size_pct, color)
                            VALUES (?,?,?,?,?,?,?)""",
                        [
                            (photo_id, i, a.get("symbol") or "arrow_up", float(a.get("x", 0.5)),
                             float(a.get("y", 0.5)), int(a.get("size", 100)), a.get("color") or "#ff0000")
                            for i, a in enumerate(anns, start=1)
                        ],
                    )

            cur.execute(
                f"""UPDATE {s}.evaluation
                    SET current_revision_no = ?, updated_at = SYSDATETIME(), deleted_at = NULL, deleted_by = NULL
                    WHERE evaluation_id = ?""",
                [next_rev, evaluation_id],
            )
            cn.commit()
        except StaleSave:
            raise
        except Exception:
            cn.rollback()
            raise

    return _load_sync(repair_no, next_rev)


def _soft_delete_sync(repair_no: str, who: Optional[str]) -> bool:
    with _connect() as cn:
        cur = cn.cursor()
        cur.execute(
            f"UPDATE {_s()}.evaluation SET deleted_at = SYSDATETIME(), deleted_by = ? WHERE repair_no = ? AND deleted_at IS NULL",
            [who, repair_no],
        )
        n = cur.rowcount
        cn.commit()
    return n > 0


def _restore_sync(repair_no: str) -> bool:
    with _connect() as cn:
        cur = cn.cursor()
        cur.execute(
            f"UPDATE {_s()}.evaluation SET deleted_at = NULL, deleted_by = NULL WHERE repair_no = ? AND deleted_at IS NOT NULL",
            [repair_no],
        )
        n = cur.rowcount
        cn.commit()
    return n > 0


def _recent_repairs_sync(limit: int) -> list[dict[str, Any]]:
    """Recently saved evaluations (for the phone page's quick picks)."""
    with _connect() as cn:
        cur = cn.cursor()
        cur.execute(
            f"""SELECT TOP (?) repair_no, current_revision_no, updated_at
                FROM {_s()}.evaluation WITH (NOLOCK) WHERE deleted_at IS NULL ORDER BY updated_at DESC""",
            [limit],
        )
        return [{"repair_no": d["repair_no"], "revisions": int(d["current_revision_no"]), "updated_at": _iso(d["updated_at"])}
                for d in _rows(cur)]


def _ping_sync() -> dict[str, Any]:
    with _connect() as cn:
        cur = cn.cursor()
        cur.execute("SELECT @@SERVERNAME, DB_NAME(), SUSER_SNAME()")
        server, db, user = cur.fetchone()
        cur.execute(f"SELECT COUNT(*) FROM {_s()}.evaluation WITH (NOLOCK) WHERE deleted_at IS NULL")
        n = cur.fetchone()[0]
    return {"server": server, "database": db, "user": user, "schema": _s(), "evaluations": int(n)}


# --------------------------------------------------------------------------
# async facade
# --------------------------------------------------------------------------
async def list_evaluations(limit: int = 200, include_deleted: bool = False) -> list[dict[str, Any]]:
    return await asyncio.to_thread(_list_sync, limit, include_deleted)


async def search_evaluations(query: str, limit: int = 25, include_deleted: bool = False) -> list[dict[str, Any]]:
    return await asyncio.to_thread(_search_sync, query, limit, include_deleted)


async def load_evaluation(repair_no: str, revision_no: Optional[int] = None) -> dict[str, Any]:
    return await asyncio.to_thread(_load_sync, repair_no, revision_no)


async def latest_snapshot_hashes(repair_no: str) -> set[str]:
    return await asyncio.to_thread(_latest_shas_sync, repair_no)


async def list_revisions(repair_no: str) -> list[dict[str, Any]]:
    return await asyncio.to_thread(_revisions_sync, repair_no)


async def save_evaluation(data: dict[str, Any], saved_by: Optional[str], snapshots: list[dict[str, Any]],
                          base_revision_no: Optional[int], force: bool) -> dict[str, Any]:
    return await asyncio.to_thread(_save_sync, data, saved_by, snapshots, base_revision_no, force)


async def soft_delete_evaluation(repair_no: str, who: Optional[str]) -> bool:
    return await asyncio.to_thread(_soft_delete_sync, repair_no, who)


async def restore_evaluation(repair_no: str) -> bool:
    return await asyncio.to_thread(_restore_sync, repair_no)


async def recent_repairs(limit: int = 20) -> list[dict[str, Any]]:
    return await asyncio.to_thread(_recent_repairs_sync, limit)


async def ping() -> dict[str, Any]:
    return await asyncio.to_thread(_ping_sync)


async def run_schema_script(path: Path) -> list[str]:
    return await asyncio.to_thread(_run_schema_script_sync, path)
