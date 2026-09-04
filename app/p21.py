"""Read-only Prophet 21 lookups: customers and their contacts.

pyodbc is synchronous, so every query runs in a worker thread via
asyncio.to_thread. All SELECTs use WITH (NOLOCK) - this is a production ERP.
"""
import asyncio
from typing import Any

import pyodbc

from .settings import get_settings

CUSTOMER_SEARCH_SQL = """
SELECT TOP (?)
    c.customer_id,
    c.customer_name,
    a.mail_city  AS city,
    a.mail_state AS state,
    c.company_id
FROM {db}.dbo.customer c WITH (NOLOCK)
LEFT JOIN {db}.dbo.address a WITH (NOLOCK) ON a.id = c.customer_id
WHERE c.delete_flag = 'N'
  AND (c.customer_name LIKE ? OR CAST(c.customer_id AS VARCHAR(20)) LIKE ?)
  {company_filter}
ORDER BY
    CASE WHEN c.customer_name LIKE ? THEN 0 ELSE 1 END,
    c.customer_name
"""

# Contacts for a customer, in P21 terms:
#   1. oe_contacts_customer - the Customer Maintenance "Contacts" link table
#      (this is what order entry offers on a sales order)
#   2. contacts whose address record is the customer's corporate address
#   3. contacts linked to one of the customer's ship-to addresses
# Deleted customers, contacts, links and ship-tos are all excluded.
CONTACTS_SQL = """
SELECT DISTINCT
    ct.id                                   AS contact_id,
    LTRIM(RTRIM(ISNULL(ct.first_name, '') + ' ' + ISNULL(ct.last_name, ''))) AS contact_name,
    ct.email_address,
    ct.direct_phone,
    ct.cellular,
    ct.title
FROM {db}.dbo.contacts ct WITH (NOLOCK)
WHERE ct.delete_flag = 'N'
  AND (
        ct.id IN (
            SELECT l.contact_id
            FROM {db}.dbo.oe_contacts_customer l WITH (NOLOCK)
            WHERE l.customer_id = ? AND l.delete_flag = 'N'
        )
     OR ct.address_id = ?
     OR ct.id IN (
            SELECT cxs.contact_id
            FROM {db}.dbo.contacts_x_ship_to cxs WITH (NOLOCK)
            WHERE cxs.ship_to_id = ?
               OR cxs.ship_to_id IN (
                    SELECT s.ship_to_id
                    FROM {db}.dbo.ship_to s WITH (NOLOCK)
                    WHERE s.customer_id = ? AND s.delete_flag = 'N'
               )
        )
  )
ORDER BY contact_name
"""


class P21Unavailable(Exception):
    """Raised when P21 is not configured or cannot be reached."""


def _connect() -> pyodbc.Connection:
    s = get_settings()
    if not s.p21_configured:
        raise P21Unavailable("P21 credentials are not configured (see .env.example)")
    try:
        return pyodbc.connect(s.p21_connection_string, timeout=s.p21_timeout, readonly=True)
    except pyodbc.Error as exc:
        raise P21Unavailable(f"Unable to connect to P21: {str(exc)[:200]}") from exc


def _rows(cursor: pyodbc.Cursor) -> list[dict[str, Any]]:
    cols = [c[0] for c in cursor.description]
    out = []
    for row in cursor.fetchall():
        d = {}
        for k, v in zip(cols, row):
            if isinstance(v, str):
                v = v.strip()
            d[k] = v
        out.append(d)
    return out


def _search_customers_sync(query: str, limit: int) -> list[dict[str, Any]]:
    s = get_settings()
    like = f"%{query}%"
    prefix = f"{query}%"
    company_filter = "AND c.company_id = ?" if s.p21_company_id else ""
    sql = CUSTOMER_SEARCH_SQL.format(db=s.p21_database, company_filter=company_filter)
    params: list[Any] = [limit, like, like]
    if s.p21_company_id:
        params.append(s.p21_company_id)
    params.append(prefix)
    with _connect() as cn:
        cur = cn.cursor()
        cur.execute(sql, params)
        rows = _rows(cur)
    for r in rows:
        r["customer_id"] = _fmt_id(r["customer_id"])
    return rows


def _contacts_sync(customer_id: str) -> list[dict[str, Any]]:
    cid = _parse_id(customer_id)
    with _connect() as cn:
        cur = cn.cursor()
        cur.execute(CONTACTS_SQL.format(db=get_settings().p21_database), [cid, cid, cid, cid])
        rows = _rows(cur)
    return rows


def _ping_sync() -> dict[str, Any]:
    with _connect() as cn:
        cur = cn.cursor()
        cur.execute("SELECT @@SERVERNAME, DB_NAME(), SUSER_SNAME()")
        server, db, user = cur.fetchone()
    return {"server": server, "database": db, "user": user}


def _fmt_id(v: Any) -> str:
    """P21 customer_id is DECIMAL(19,0); show it without a trailing '.0'."""
    try:
        return str(int(v))
    except (TypeError, ValueError):
        return str(v)


def _parse_id(v: str) -> int:
    try:
        return int(str(v).strip())
    except ValueError as exc:
        raise ValueError(f"Invalid customer id: {v!r}") from exc


async def search_customers(query: str, limit: int = 25) -> list[dict[str, Any]]:
    return await asyncio.to_thread(_search_customers_sync, query, limit)


async def customer_contacts(customer_id: str) -> list[dict[str, Any]]:
    return await asyncio.to_thread(_contacts_sync, customer_id)


async def ping() -> dict[str, Any]:
    return await asyncio.to_thread(_ping_sync)
