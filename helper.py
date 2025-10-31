# Add your utilities or helper functions to this file.

import os
import json
import sqlite3
import hmac
import hashlib
from datetime import datetime
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv, find_dotenv
from pydantic import BaseModel, create_model
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

# --- Environment and Config ---

# Load environment variables from .env file
load_dotenv(find_dotenv())

DB_PATH = os.path.join(os.path.dirname(__file__), "invoices.db")
POLICY_FILE_PATH = os.getenv("POLICY_FILE_PATH", os.path.join(os.path.dirname(__file__), "prompts/approval_policy.txt"))
APPROVAL_PROMPT_PATH = os.getenv("APPROVAL_PROMPT_PATH", os.path.join(os.path.dirname(__file__), "prompts/approval_prompt.txt"))
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
FROM_EMAIL = os.getenv("FROM_EMAIL")
APPROVAL_EMAIL = os.getenv("APPROVAL_EMAIL")
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://127.0.0.1:8000")
APP_SECRET = os.getenv("APP_SECRET", "dev-secret")

# Approver mappings based on amount thresholds
APPROVERS = {
    "manager": "Robert Schrill",
    "finance_manager": "Sven Stevenon",
    "executive": "Georly Daniel",
}
SENDGRID_TEMPLATE_ID = os.getenv("SENDGRID_TEMPLATE_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


# --- Database Helpers ---

def init_db() -> None:
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT,
                supplier_name TEXT,
                invoice_date TEXT,
                total_amount REAL,
                currency TEXT,
                line_items TEXT,
                submitter_name TEXT,
                submitter_email TEXT,
                submitter_team TEXT,
                business_reason TEXT,
                file_sha256 TEXT UNIQUE,
                raw_json TEXT,
                text_excerpt TEXT,
                created_at TEXT,
                approval_status TEXT DEFAULT 'approval_inprogress'
            )
            """
        )
        # add approval_status column if migrating older DBs
        try:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(invoices)").fetchall()]
            if "approval_status" not in cols:
                conn.execute("ALTER TABLE invoices ADD COLUMN approval_status TEXT DEFAULT 'approval_inprogress'")
            if "currency" not in cols:
                conn.execute("ALTER TABLE invoices ADD COLUMN currency TEXT")
            if "line_items" not in cols:
                conn.execute("ALTER TABLE invoices ADD COLUMN line_items TEXT")
            if "business_reason" not in cols:
                conn.execute("ALTER TABLE invoices ADD COLUMN business_reason TEXT")
        except Exception:
            pass

        # approvals table
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS approvals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                reason TEXT,
                decided_by TEXT,
                approver_email TEXT,
                model_decision TEXT,
                model_confidence REAL,
                policy_citations TEXT,
                previous_case_refs TEXT,
                link_token TEXT UNIQUE,
                created_at TEXT,
                updated_at TEXT,
                FOREIGN KEY(invoice_id) REFERENCES invoices(id)
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def insert_invoice(row: Dict[str, Any]) -> int:
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.execute(
            """
            INSERT INTO invoices (
                filename, supplier_name, invoice_date, total_amount, currency, line_items,
                submitter_name, submitter_email, submitter_team, business_reason,
                file_sha256, raw_json, text_excerpt, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row.get("filename"),
                row.get("supplier_name"),
                row.get("invoice_date"),
                row.get("total_amount"),
                row.get("currency"),
                row.get("line_items"),
                row.get("submitter_name"),
                row.get("submitter_email"),
                row.get("submitter_team"),
                row.get("business_reason"),
                row.get("file_sha256"),
                row.get("raw_json"),
                row.get("text_excerpt"),
                row.get("created_at"),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def get_invoices(limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            "SELECT id, filename, supplier_name, invoice_date, total_amount, submitter_name, submitter_team, created_at FROM invoices ORDER BY id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def get_invoice(invoice_id: int) -> Optional[Dict[str, Any]]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,))
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# --- Approval & Security Helpers ---

def sign_token(approval_id: int, created_at: str) -> str:
    msg = f"{approval_id}:{created_at}".encode()
    return hmac.new(APP_SECRET.encode(), msg, hashlib.sha256).hexdigest()


def verify_token(approval_id: int, created_at: str, token: str) -> bool:
    return hmac.compare_digest(sign_token(approval_id, created_at), token)


def load_text_safe(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def list_prior_reasons(limit: int = 20) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            """
            SELECT a.reason, a.status, i.supplier_name, i.total_amount, i.currency
            FROM approvals a JOIN invoices i ON a.invoice_id = i.id
            WHERE a.reason IS NOT NULL AND a.reason <> '' AND a.decided_by LIKE 'human:%'
            ORDER BY a.id DESC LIMIT ?
            """,
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def create_approval(invoice_id: int, status: str, reason: Optional[str], decided_by: str, approver_email: Optional[str], model_decision: Optional[str], model_confidence: Optional[float], policy_citations: Optional[List[str]], previous_case_refs: Optional[List[str]]) -> tuple[int, str]:
    now = datetime.utcnow().isoformat()
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.execute(
            """
            INSERT INTO approvals (invoice_id, status, reason, decided_by, approver_email, model_decision, model_confidence, policy_citations, previous_case_refs, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                invoice_id, status, reason, decided_by, approver_email, model_decision, model_confidence,
                json.dumps(policy_citations or []), json.dumps(previous_case_refs or []), now, now,
            ),
        )
        approval_id = int(cur.lastrowid)
        token = sign_token(approval_id, now)
        conn.execute("UPDATE approvals SET link_token = ? WHERE id = ?", (token, approval_id))
        conn.execute("UPDATE invoices SET approval_status = ? WHERE id = ?", (status, invoice_id))
        conn.commit()
        return approval_id, token
    finally:
        conn.close()


def update_approval_status(approval_id: int, status: str, reason: Optional[str], decided_by: Optional[str]) -> None:
    now = datetime.utcnow().isoformat()
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            "UPDATE approvals SET status = ?, reason = COALESCE(?, reason), decided_by = COALESCE(?, decided_by), updated_at = ? WHERE id = ?",
            (status, reason, decided_by, now, approval_id),
        )
        # also update invoice
        cur = conn.execute("SELECT invoice_id FROM approvals WHERE id = ?", (approval_id,))
        row = cur.fetchone()
        if row:
            conn.execute("UPDATE invoices SET approval_status = ? WHERE id = ?", (status, row[0]))
        conn.commit()
    finally:
        conn.close()


# --- Email Helpers ---

def send_approval_email(approval_id: int, invoice: Dict[str, Any], proposed: Dict[str, Any], token: str) -> None:
    print(f"\n{'='*80}")
    print(f"[EMAIL TRIGGER] send_approval_email() called")
    print(f"[EMAIL TRIGGER] Approval ID: {approval_id}")
    print(f"[EMAIL TRIGGER] Invoice ID: {invoice.get('id')}")
    print(f"[EMAIL TRIGGER] Recipient: {APPROVAL_EMAIL}")
    print(f"[EMAIL TRIGGER] Token: {token}")
    print(f"{'='*80}\n")
    
    if not SENDGRID_API_KEY or not FROM_EMAIL or not APPROVAL_EMAIL:
        # fallback: print to logs
        print("[EMAIL] ❌ Missing SendGrid config; printing approval email instead")
        print(f"[EMAIL] SENDGRID_API_KEY set: {bool(SENDGRID_API_KEY)}")
        print(f"[EMAIL] FROM_EMAIL: {FROM_EMAIL}")
        print(f"[EMAIL] APPROVAL_EMAIL: {APPROVAL_EMAIL}")
        print({"approval_id": approval_id, "invoice": invoice, "proposed": proposed, "token": token})
        return

    # Prefer SendGrid Dynamic Template when configured, otherwise fallback to HTML
    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        if 'build_approval_email_payload' in globals() and SENDGRID_TEMPLATE_ID:
            print(f"[EMAIL] 📧 Using SendGrid Dynamic Template: {SENDGRID_TEMPLATE_ID}")
            dt_payload = build_approval_email_payload(approval_id, {**invoice, "id": invoice.get("id")}, proposed, token)
            message = Mail(from_email=FROM_EMAIL, to_emails=APPROVAL_EMAIL)
            message.template_id = SENDGRID_TEMPLATE_ID
            message.dynamic_template_data = dt_payload
            response = sg.send(message)
            print(f"[EMAIL] ✅ Email sent successfully!")
            print(f"[EMAIL] SendGrid response status: {response.status_code}")
            print(f"[EMAIL] From: {FROM_EMAIL} → To: {APPROVAL_EMAIL}")
        else:
            print(f"[EMAIL] 📧 Using built-in HTML email (no template ID configured)")
            review_link = f"{APP_BASE_URL}/approvals/{approval_id}/review?token={token}"
            print(f"[EMAIL] Review URL: {review_link}")

            # Extract actual invoice number from raw_json if available
            invoice_number = None
            if invoice.get("raw_json"):
                try:
                    raw_json = json.loads(invoice.get("raw_json")) if isinstance(invoice.get("raw_json"), str) else invoice.get("raw_json")
                    invoice_number = raw_json.get("invoice_id") or raw_json.get("invoice_number")
                except (json.JSONDecodeError, TypeError):
                    pass
            
            # Fallback to database ID if no invoice number found
            if not invoice_number:
                invoice_number = invoice.get("id")

            subject = f"Invoice #{invoice_number} requires approval"
            body = (
                f"Supplier: {invoice.get('supplier_name')}<br>"
                f"Invoice Number: {invoice_number}<br>"
                f"Date: {invoice.get('invoice_date')}<br>"
                f"Total: {invoice.get('total_amount')}<br>"
            )
            body += (
                f"<br>"
                f"<div style='margin: 16px 0; padding: 12px; background: #f0f9ff; border-left: 4px solid #3b82f6; border-radius: 4px;'>"
                f"<h3 style='margin: 0 0 10px 0; color: #1f2937; font-size: 16px;'>Policy Recommendations</h3>"
            )
            if invoice.get('business_reason'):
                body += (
                    f"<div style='margin-bottom: 12px; padding: 8px; background: #ffffff; border-radius: 4px;'>"
                    f"<div style='font-size: 11px; color: #6b7280; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px;'>Business Reason</div>"
                    f"<div style='color: #1f2937; font-size: 14px;'>{invoice.get('business_reason')}</div>"
                    f"</div>"
                )
            if proposed.get('reason'):
                body += (
                    f"<div style='color: #374151; font-size: 14px; line-height: 1.6;'>{proposed.get('reason')}</div>"
                )
            body += (
                f"</div>"
                f"<br>"
                f"<a href='{review_link}' style='background:#10b981;color:#fff;padding:12px 24px;text-decoration:none;border-radius:8px;display:inline-block;margin-right:10px'>Review Invoice</a>"
            )
            message = Mail(from_email=FROM_EMAIL, to_emails=APPROVAL_EMAIL, subject=subject, html_content=body)
            response = sg.send(message)
            print(f"[EMAIL] ✅ Email sent successfully!")
            print(f"[EMAIL] SendGrid response status: {response.status_code}")
            print(f"[EMAIL] From: {FROM_EMAIL} → To: {APPROVAL_EMAIL}")
    except Exception as e:
        print(f"[EMAIL] ❌ SendGrid error: {e}")
        print(f"[EMAIL] Error type: {type(e).__name__}")


def render_brand_approval_email(payload: Dict[str, Any]) -> Dict[str, str]:
    pre = payload.get("preheader") or "Invoice requires your approval"
    brand = payload.get("brand") or {}
    invoice = payload.get("invoice") or {}
    requestor = payload.get("requestor") or {}
    approver_name = payload.get("approver_name") or "Approver"
    approval_url = payload.get("approval_url") or "#"
    reject_url = payload.get("reject_url") or "#"
    footer = payload.get("footer") or {}

    subject = pre
    logo = brand.get("logo_url")
    brand_name = brand.get("name", "")
    amount_line = f"{invoice.get('currency','')}{invoice.get('amount','')}"

    html = f"""
    <div style='font-family:Inter,Arial,sans-serif'>
      <div style='max-width:620px;margin:auto;border:1px solid #eee;border-radius:12px;overflow:hidden'>
        <div style='background:#0f172a;color:#fff;padding:16px 20px;display:flex;align-items:center;gap:12px'>
          {f"<img src='{logo}' alt='logo' style='height:28px'/>" if logo else ''}
          <div style='font-weight:600'>{brand_name}</div>
        </div>
        <div style='padding:20px'>
          <div style='color:#334155;font-size:14px'>{pre}</div>
          <h2 style='margin:8px 0 16px'>Invoice {invoice.get('number','')}</h2>
          <table style='width:100%;border-collapse:collapse'>
            <tr><td style='padding:6px 0;color:#64748b'>Vendor</td><td style='text-align:right'>{invoice.get('vendor','')}</td></tr>
            {"<tr><td style='padding:6px 0;color:#64748b'>Business Reason</td><td style='text-align:right'>{invoice.get('business_reason','')}</td></tr>" if invoice.get('business_reason') else ''}
            <tr><td style='padding:6px 0;color:#64748b'>Invoice Date</td><td style='text-align:right'>{invoice.get('date','')}</td></tr>
            <tr><td style='padding:6px 0;color:#64748b'>Amount</td><td style='text-align:right;font-weight:600'>{amount_line}</td></tr>
          </table>
          <div style='margin:14px 0'>
            <a href='{invoice.get('link','#')}' style='color:#2563eb;text-decoration:none'>View invoice</a>
            {" · " if invoice.get('attachments_url') else ''}
            {f"<a href='{invoice.get('attachments_url')}' style='color:#2563eb;text-decoration:none'>Attachments</a>" if invoice.get('attachments_url') else ''}
          </div>
          <div style='margin:16px 0;padding:12px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px'>
            <div style='color:#475569;font-size:14px;margin-bottom:6px'>Requested by</div>
            <div style='display:flex;justify-content:space-between'>
              <div>{requestor.get('name','')} · {requestor.get('team','')}</div>
              <div style='color:#64748b'>{requestor.get('email','')}</div>
            </div>
          </div>
          <p style='color:#334155'>Hi {approver_name}, please review this invoice.</p>
          <div style='display:flex;gap:10px;margin:18px 0'>
            <a href='{approval_url}' style='background:#16a34a;color:#fff;padding:10px 14px;border-radius:8px;text-decoration:none'>Approve</a>
            <a href='{reject_url}' style='background:#ef4444;color:#fff;padding:10px 14px;border-radius:8px;text-decoration:none'>Decline</a>
          </div>
          <div style='font-size:12px;color:#94a3b8;margin-top:18px'>
            Need help? <a href='{footer.get('help_url','#')}' style='color:#2563eb'>Help center</a>
            {" · " if footer.get('preferences_url') else ''}
            {f"<a href='{footer.get('preferences_url')}' style='color:#2563eb'>Preferences</a>" if footer.get('preferences_url') else ''}
          </div>
        </div>
      </div>
    </div>
    """
    return {"subject": subject, "html": html}


def get_approver_name(total_amount: Optional[float]) -> str:
    """Determine approver name based on invoice amount threshold."""
    if total_amount is None:
        return APPROVERS.get("manager", "Approver")
    
    if total_amount > 10000:
        return APPROVERS.get("executive", "Georly Daniel")
    elif total_amount > 2500:
        return APPROVERS.get("finance_manager", "Sven Stevenon")
    else:
        return APPROVERS.get("manager", "Robert Schrill")


def get_approval_level(total_amount: Optional[float]) -> str:
    """Get approval level description based on amount."""
    if total_amount is None:
        return "manager"
    
    if total_amount > 10000:
        return "executive"
    elif total_amount > 2500:
        return "finance manager"
    else:
        return "manager"


def build_approval_email_payload(approval_id: int, invoice: Dict[str, Any], proposed: Dict[str, Any], token: str) -> Dict[str, Any]:
    """Construct dynamic_template_data for SendGrid Dynamic Template emails."""
    review_url = f"{APP_BASE_URL}/approvals/{approval_id}/review?token={token}"
    
    print(f"[EMAIL PAYLOAD] Building payload for approval #{approval_id}, invoice #{invoice.get('id')}")
    print(f"[EMAIL PAYLOAD] Review URL: {review_url}")
    
    # Extract actual invoice number from raw_json if available
    invoice_number = None
    if invoice.get("raw_json"):
        try:
            raw_json = json.loads(invoice.get("raw_json")) if isinstance(invoice.get("raw_json"), str) else invoice.get("raw_json")
            invoice_number = raw_json.get("invoice_id") or raw_json.get("invoice_number")
        except (json.JSONDecodeError, TypeError):
            pass
    
    # Fallback to database ID if no invoice number found
    if not invoice_number:
        invoice_number = invoice.get("id")
    
    # Determine approver name based on amount
    total_amount = invoice.get("total_amount")
    approver_name = get_approver_name(total_amount)
    
    return {
        "preheader": f"Invoice {invoice_number} requires your approval",
        "brand": {
            "name": "Kaladeofin Technologies",
            "logo_url": "https://example.com/logo.png",
        },
        "invoice": {
            "number": invoice_number,
            "amount": invoice.get("total_amount"),
            "currency": invoice.get("currency"),
            "vendor": invoice.get("supplier_name") or "",
            "business_reason": invoice.get("business_reason") or "",
            "date": invoice.get("invoice_date") or "",
            "link": f"{APP_BASE_URL}/invoices/{invoice.get('id')}",
            "attachments_url": "",
        },
        "requestor": {
            "name": invoice.get("submitter_name") or "",
            "email": invoice.get("submitter_email") or "",
            "team": invoice.get("submitter_team") or "",
        },
        "approver_name": approver_name,
        "approval_url": review_url,
        "reject_url": review_url,
        "footer": {
            "help_url": "https://example.com/help",
            "preferences_url": "{{{unsubscribe}}}",
        },
        # Optional model details if your template wants to show them
        "model_decision": proposed.get("decision"),
        "model_confidence": proposed.get("confidence"),
        "model_reason": proposed.get("reason"),
        "model_citations": proposed.get("citations") or [],
    }

# --- Pydantic & LlamaIndex Helpers ---

def build_pydantic_model_from_schema(name: str, schema_dict: Dict[str, str]) -> BaseModel:
    # By default, make all fields OPTIONAL so missing values don't fail validation.
    # Support required with a trailing '!' (e.g., "str!"), optional with '?' or no suffix.
    base_map: Dict[str, Any] = {
        "str": str,
        "int": int,
        "float": float,
        "bool": bool,
    }

    fields: Dict[str, Any] = {}
    for key, raw in schema_dict.items():
        t = (raw or "").strip().lower()
        required = t.endswith("!")
        optional = t.endswith("?") or not required
        core = t.rstrip("!?")
        py_type = base_map.get(core, str)

        if optional and not required:
            fields[key] = (Optional[py_type], None)
        else:
            fields[key] = (py_type, ...)

    return create_model(name, **fields)  # type: ignore