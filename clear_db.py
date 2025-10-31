#!/usr/bin/env python3
"""Simple script to clear all data from invoices.db"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "invoices.db")

if not os.path.exists(DB_PATH):
    print(f"Database not found at {DB_PATH}")
    exit(1)

conn = sqlite3.connect(DB_PATH)
try:
    invoices_deleted = conn.execute("DELETE FROM invoices").rowcount
    approvals_deleted = conn.execute("DELETE FROM approvals").rowcount
    conn.commit()
    print(f"✅ Cleared database successfully!")
    print(f"   - Deleted {invoices_deleted} invoices")
    print(f"   - Deleted {approvals_deleted} approvals")
except Exception as e:
    print(f"❌ Error: {e}")
    conn.rollback()
finally:
    conn.close()

