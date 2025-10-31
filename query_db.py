import argparse
import json
import os
import sqlite3
import sys
from typing import Any, Dict, List, Optional


def _ensure_db_exists(db_path: str) -> None:
    if not os.path.exists(db_path):
        print(f"Error: database not found at {db_path}", file=sys.stderr)
        sys.exit(1)


def _dict_factory(cursor: sqlite3.Cursor, row: sqlite3.Row) -> Dict[str, Any]:
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


def list_invoices(db_path: str, limit: int, offset: int) -> List[Dict[str, Any]]:
    _ensure_db_exists(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = _dict_factory
    try:
        cur = conn.execute(
            "SELECT id, filename, supplier_name, invoice_date, total_amount, submitter_name, submitter_team, created_at "
            "FROM invoices ORDER BY id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        return cur.fetchall()
    finally:
        conn.close()


def get_invoice(db_path: str, invoice_id: int) -> Optional[Dict[str, Any]]:
    _ensure_db_exists(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = _dict_factory
    try:
        cur = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,))
        return cur.fetchone()
    finally:
        conn.close()


def execute_query(db_path: str, sql: str) -> tuple[List[Dict[str, Any]], Optional[str]]:
    _ensure_db_exists(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = _dict_factory
    try:
        cur = conn.execute(sql)
        if sql.strip().upper().startswith("SELECT"):
            rows = cur.fetchall()
            return rows, None
        conn.commit()
        return [], f"Success: {cur.rowcount} row(s) affected"
    except Exception as e:
        return [], f"Error: {str(e)}"
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Query invoices SQLite DB")
    parser.add_argument(
        "--db",
        default=os.path.join(os.path.dirname(__file__), "invoices.db"),
        help="Path to SQLite database (default: invoices.db in project root)",
    )

    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List invoices")
    p_list.add_argument("--limit", type=int, default=20)
    p_list.add_argument("--offset", type=int, default=0)

    p_get = sub.add_parser("get", help="Get one invoice by id")
    p_get.add_argument("id", type=int)

    p_raw = sub.add_parser("raw", help="Print raw_json for an invoice id")
    p_raw.add_argument("id", type=int)

    p_shell = sub.add_parser("shell", help="Interactive SQL shell")
    # No args for shell

    args = parser.parse_args()

    if args.cmd == "list":
        rows = list_invoices(args.db, max(1, min(args.limit, 200)), max(0, args.offset))
        print(json.dumps({"items": rows}, indent=2, ensure_ascii=False))
        return

    if args.cmd == "get":
        row = get_invoice(args.db, args.id)
        if not row:
            print(f"Not found: invoice id {args.id}", file=sys.stderr)
            sys.exit(2)
        print(json.dumps(row, indent=2, ensure_ascii=False))
        return

    if args.cmd == "raw":
        row = get_invoice(args.db, args.id)
        if not row:
            print(f"Not found: invoice id {args.id}", file=sys.stderr)
            sys.exit(2)
        try:
            payload = json.loads(row.get("raw_json") or "{}")
        except Exception:
            payload = {"raw_json": row.get("raw_json")}
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    if args.cmd == "shell":
        db_path = args.db
        if not os.path.exists(db_path):
            print(f"Error: database not found at {db_path}", file=sys.stderr)
            sys.exit(1)
        print(f"Connected to {db_path}")
        print("Enter SQL queries (or 'exit' to quit)")
        while True:
            try:
                query = input("> ").strip()
                if not query:
                    continue
                if query.lower() in ("exit", "quit", "q"):
                    break
                rows, msg = execute_query(db_path, query)
                if msg:
                    print(msg)
                else:
                    if rows:
                        # Print table header
                        print(" ".join(k for k in rows[0].keys()))
                        # Print rows
                        for r in rows:
                            print(" ".join(str(v) for v in r.values()))
                    else:
                        print("No rows returned")
            except KeyboardInterrupt:
                print("\nGoodbye!")
                break
            except Exception as e:
                print(f"Error: {e}")
        return


if __name__ == "__main__":
    main()


