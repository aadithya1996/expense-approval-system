import os
import json
import tempfile
import hashlib
import sqlite3
from datetime import datetime
from typing import Any, Dict, Optional, List

from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Query, Body, Request
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import create_model

from openai import OpenAI as OpenAIClient
from pypdf import PdfReader
from dateutil.parser import parse as parse_date

# Import helpers and workflow
from helper import (
    init_db,
    insert_invoice,
    get_invoices,
    get_invoice,
    update_approval_status,
    render_brand_approval_email,
    build_pydantic_model_from_schema,
    DB_PATH,
    APPROVAL_EMAIL,
    OPENAI_API_KEY,
    verify_token,
    create_approval,
    send_approval_email,
    sqlite3,
    SENDGRID_API_KEY,
    FROM_EMAIL,
    SENDGRID_TEMPLATE_ID,
)
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from invoice_workflow import run_approval_workflow, propose_decision


app = FastAPI(title="PDF → JSON Extractor", version="1.0")

# Initialize Jinja2 templates
templates = Jinja2Templates(directory="templates")

# Initialize database on startup
init_db()


def extract_text_from_pdf(temp_pdf_path: str) -> str:
    """Extract text from PDF using pypdf."""
    try:
        reader = PdfReader(temp_pdf_path)
        pages = [p.extract_text() or "" for p in reader.pages]
        text = "\n\n".join(pages).strip()
        return text
    except Exception as e:
        print(f"Error extracting PDF text: {e}")
        return ""


@app.post("/extract")
async def extract(
    file: UploadFile = File(...),
    schema: Optional[str] = Form(None),
    submitter_name: Optional[str] = Form(None),
    submitter_email: Optional[str] = Form(None),
    submitter_team: Optional[str] = Form(None),
    business_reason: Optional[str] = Form(None),
    force: bool = Query(False),
):
    if file.content_type not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(status_code=400, detail="file must be a PDF")

    try:
        # save upload to temp file
        body = await file.read()
        # upload size limit ~25MB
        if len(body) > 25 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="file too large (max 25MB)")

        file_sha256 = hashlib.sha256(body).hexdigest()

        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(body)
            temp_pdf_path = tmp.name

        # read pdf text
        full_text = extract_text_from_pdf(temp_pdf_path)
        if not full_text:
            raise HTTPException(status_code=400, detail="Could not extract text from PDF")

        # choose schema model
        if schema:
            try:
                schema_dict = json.loads(schema)
                if not isinstance(schema_dict, dict):
                    raise ValueError("schema must be a JSON object of field:type")
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"invalid schema: {e}")
            LineItem = create_model(
                "LineItem",
                description=(Optional[str], None),
                quantity=(Optional[int], None),
                unit_price=(Optional[float], None),
                total=(Optional[float], None),
            )
            OutputModel = build_pydantic_model_from_schema("Extracted", schema_dict)
        else:
            # default minimal OPTIONAL model so missing fields don't error
            LineItem = create_model(
                "LineItem",
                description=(Optional[str], None),
                quantity=(Optional[int], None),
                unit_price=(Optional[float], None),
                total=(Optional[float], None),
            )
            OutputModel = create_model(
                "Extracted",
                supplier_name=(Optional[str], None),
                invoice_date=(Optional[str], None),
                total_amount=(Optional[float], None),
                currency=(Optional[str], None),
                line_items=(Optional[List[LineItem]], None),
            )

        # Use OpenAI to extract invoice data
        client = OpenAIClient(api_key=OPENAI_API_KEY)
        
        extraction_prompt = f"""
        Parse the following invoice text and extract key information into JSON format.
        Extract: invoice_id (or invoice_number - the unique identifier on the invoice), supplier_name, invoice_date (ISO format YYYY-MM-DD), total_amount (number), 
        currency (e.g., "USD", "INR"), and line_items (array of objects with description, quantity, unit_price, total).
        
        IMPORTANT: For supplier_name:
        - Extract the supplier/vendor name from "From" column or header
        - DO NOT include "Kaladeofin" in the supplier name (Kaladeofin is the organization receiving the invoice, not the supplier)
        - If "Kaladeofin" appears in the text, it is the recipient, not the supplier
        - The supplier is the entity FROM whom the invoice is received (the vendor/biller)
        
        If a field is not present, leave it null. Do not hallucinate.
        
        Invoice Text:
        {full_text[:8000]}
        """
        
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are an invoice data extraction assistant. Extract structured data from invoices."},
                    {"role": "user", "content": extraction_prompt}
                ],
                response_format={"type": "json_object"}
            )
            
            result_dict = json.loads(response.choices[0].message.content)
        except Exception as e:
            print(f"Error during OpenAI extraction: {e}")
            result_dict = {}
        
        # Add LLM results to candidates for fallback merging
        candidates: Dict[str, List[Any]] = {
            "invoice_id": [result_dict.get("invoice_id") or result_dict.get("invoice_number")] if (result_dict.get("invoice_id") or result_dict.get("invoice_number")) else [],
            "supplier_name": [result_dict.get("supplier_name")] if result_dict.get("supplier_name") else [],
            "invoice_date": [result_dict.get("invoice_date")] if result_dict.get("invoice_date") else [],
            "total_amount": [result_dict.get("total_amount")] if result_dict.get("total_amount") else [],
            "currency": [result_dict.get("currency")] if result_dict.get("currency") else [],
            "line_items": result_dict.get("line_items", []) if isinstance(result_dict.get("line_items"), list) else []
        }

        def fallback_total(text: str) -> Optional[float]:
            import re
            pat = re.compile(r"\b(total|amount due|balance due)[:\s]*\$?([\d,]+(?:\.\d{2})?)\b", re.I)
            m = pat.search(text)
            if m:
                amt = m.group(2).replace(",", "")
                try:
                    return float(amt)
                except Exception:
                    return None
            return None

        def fallback_date(text: str) -> Optional[str]:
            import re
            # find the first plausible date string
            pat = re.compile(r"(\b\d{4}-\d{2}-\d{2}\b|\b\d{2}/\d{2}/\d{4}\b|\b\d{2}-\d{2}-\d{4}\b)")
            m = pat.search(text)
            if m:
                s = m.group(1)
                try:
                    iso = parse_date(s, dayfirst=False, yearfirst=True).date().isoformat()
                    return iso
                except Exception:
                    return s
            return None

        def clean_supplier_name(supplier: Optional[str]) -> Optional[str]:
            """Remove 'Kaladeofin' from supplier name as it's the recipient organization."""
            if not supplier:
                return None
            # Remove Kaladeofin and variations (case insensitive)
            import re
            cleaned = re.sub(r'\bKaladeofin\b', '', supplier, flags=re.IGNORECASE)
            cleaned = re.sub(r'\s+', ' ', cleaned).strip()  # Normalize whitespace
            # Remove trailing punctuation
            cleaned = cleaned.rstrip(' ,-')
            return cleaned if cleaned else None
        
        def fallback_supplier(text: str) -> Optional[str]:
            """Extract supplier name, looking for 'From' column or header, excluding Kaladeofin."""
            import re
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            
            # Look for "From:" pattern
            for line in lines:
                if re.search(r'From\s*[:]', line, re.IGNORECASE):
                    # Extract text after "From:" or "From"
                    parts = re.split(r'From\s*[:]?\s*', line, maxsplit=1, flags=re.IGNORECASE)
                    if len(parts) > 1:
                        supplier = parts[1].strip()
                        supplier = clean_supplier_name(supplier)
                        if supplier:
                            return supplier
            
            # Fallback: use first non-empty line, but exclude Kaladeofin
            for line in lines:
                if 'Kaladeofin' not in line.upper():
                    supplier = clean_supplier_name(line)
                    if supplier:
                        return supplier
            
            return None

        # post-merge decisions
        def most_frequent(items: List[str]) -> Optional[str]:
            if not items:
                return None
            from collections import Counter
            return Counter(items).most_common(1)[0][0]

        # Clean supplier name candidates to remove Kaladeofin
        supplier_candidates = [clean_supplier_name(str(x)) for x in candidates["supplier_name"]]
        supplier_candidates = [s for s in supplier_candidates if s]  # Remove None values
        
        result_dict: Dict[str, Any] = {
            "invoice_id": candidates["invoice_id"][0] if candidates.get("invoice_id") else None,
            "supplier_name": most_frequent(supplier_candidates) or fallback_supplier(full_text),
            "invoice_date": None,
            "total_amount": None,
            "currency": None,
            "line_items": [],
        }
        
        # Final cleanup of supplier name
        if result_dict["supplier_name"]:
            result_dict["supplier_name"] = clean_supplier_name(result_dict["supplier_name"])

        # decide date (prefer earliest ISO)
        date_candidates: List[str] = [str(x) for x in candidates["invoice_date"]]
        if not date_candidates:
            fb = fallback_date(full_text)
            if fb:
                date_candidates.append(fb)
        def to_iso(s: str) -> Optional[str]:
            try:
                return parse_date(s, dayfirst=False, yearfirst=True).date().isoformat()
            except Exception:
                return None
        iso_dates = [d for d in (to_iso(x) for x in date_candidates) if d]
        result_dict["invoice_date"] = min(iso_dates) if iso_dates else (date_candidates[0] if date_candidates else None)

        # decide total (first numeric)
        total_candidates: List[float] = []
        for x in candidates["total_amount"]:
            try:
                total_candidates.append(float(str(x).replace(",", "").replace("$", "")))
            except Exception:
                continue
        if not total_candidates:
            fb_total = fallback_total(full_text)
            if fb_total is not None:
                total_candidates.append(fb_total)
        result_dict["total_amount"] = total_candidates[0] if total_candidates else None

        # decide currency (most frequent)
        currency_candidates: List[str] = [str(x) for x in candidates["currency"]]
        if not currency_candidates:
            fb_currency = fallback_supplier(full_text) # Fallback to supplier name if no currency found
            if fb_currency:
                # Try to extract currency from supplier name (e.g., "ABC Inc. (USD)", "XYZ Ltd. (INR)")
                import re
                pat = re.compile(r"\(([^)]+)\)$")
                m = pat.search(fb_currency)
                if m:
                    currency_candidates.append(m.group(1).strip())
                else:
                    # Fallback to a default if no currency found
                    currency_candidates.append("USD") # Default to USD
        result_dict["currency"] = most_frequent(currency_candidates) or "USD" # Default to USD if no currency found

        # decide line items
        line_item_candidates: List[Dict[str, Any]] = []
        for item_dict in candidates["line_items"]:
            if isinstance(item_dict, dict):
                line_item = {
                    "description": item_dict.get("description") or "",
                    "quantity": item_dict.get("quantity") or 1,
                    "unit_price": item_dict.get("unit_price") or 0.0,
                    "total": item_dict.get("total") or 0.0,
                }
                line_item_candidates.append(line_item)

        # Post-process line items to ensure consistency (e.g., quantity * unit_price = total)
        for i, item in enumerate(line_item_candidates):
            if item["quantity"] is not None and item["unit_price"] is not None:
                item["total"] = item["quantity"] * item["unit_price"]
            elif item["total"] is not None and item["unit_price"] is not None:
                item["quantity"] = item["total"] / item["unit_price"]
            elif item["total"] is not None and item["quantity"] is not None:
                item["unit_price"] = item["total"] / item["quantity"]
            else:
                # If total is missing, try to calculate it from quantity and unit_price
                if item["quantity"] is not None and item["unit_price"] is not None:
                    item["total"] = item["quantity"] * item["unit_price"]
                else:
                    item["total"] = 0.0 # Default to 0 if calculation fails

        result_dict["line_items"] = line_item_candidates

        # Check for duplicate file (same SHA256 hash) and duplicate invoice (invoice_id + supplier_name)
        extracted_invoice_id = result_dict.get("invoice_id") or result_dict.get("invoice_number")
        extracted_supplier_name = result_dict.get("supplier_name")
        
        if not force:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            try:
                # Check for duplicate file (same SHA256 hash)
                existing_file = conn.execute(
                    "SELECT id, filename FROM invoices WHERE file_sha256 = ?",
                    (file_sha256,)
                ).fetchone()
                
                if existing_file:
                    raise HTTPException(
                        status_code=409,
                        detail=f"duplicate file: This PDF file has already been submitted (invoice id {existing_file['id']}, filename: {existing_file['filename']}). Set force=true to override."
                    )
                
                # Check for duplicate invoice (invoice_id + supplier_name)
                if extracted_invoice_id and extracted_supplier_name:
                    # Get all invoices from the same supplier
                    cur = conn.execute(
                        "SELECT id, supplier_name, raw_json FROM invoices WHERE supplier_name = ?",
                        (extracted_supplier_name,)
                    )
                    existing_invoices = cur.fetchall()
                    
                    # Check each invoice's raw_json for matching invoice_id
                    for existing in existing_invoices:
                        try:
                            existing_json = json.loads(existing["raw_json"])
                            existing_invoice_id = existing_json.get("invoice_id") or existing_json.get("invoice_number")
                            
                            # If invoice_id matches, it's a duplicate
                            if existing_invoice_id and str(existing_invoice_id).strip().lower() == str(extracted_invoice_id).strip().lower():
                                raise HTTPException(
                                    status_code=409, 
                                    detail=f"duplicate invoice (invoice id {existing['id']}): Invoice ID '{extracted_invoice_id}' from supplier '{extracted_supplier_name}' already exists; set force=true to override"
                                )
                        except (json.JSONDecodeError, Exception):
                            # Skip invoices with invalid JSON
                            continue
            finally:
                conn.close()

        # persist row
        text_excerpt = full_text[:4000]
        row = {
            "filename": file.filename,
            "supplier_name": result_dict.get("supplier_name"),
            "invoice_date": result_dict.get("invoice_date"),
            "total_amount": result_dict.get("total_amount"),
            "currency": result_dict.get("currency"),
            "line_items": json.dumps(result_dict.get("line_items") or []),
            "submitter_name": submitter_name,
            "submitter_email": submitter_email,
            "submitter_team": submitter_team,
            "business_reason": business_reason,
            "file_sha256": file_sha256,
            "raw_json": json.dumps(result_dict),
            "text_excerpt": text_excerpt,
            "created_at": datetime.utcnow().isoformat(),
        }
        new_id = insert_invoice(row)
        
        # Run the approval workflow
        try:
            result = run_approval_workflow(invoice_row={**row, "id": new_id})
            return JSONResponse(content={"id": new_id, "data": result_dict, "approval": result})
        except Exception as e:
            # If workflow fails, we still have the invoice, but need to log error
            print(f"[WORKFLOW] Error running approval workflow for Invoice #{new_id}: {e}")
            # Fallback to creating a pending approval record
            approval_id, _ = create_approval(
                invoice_id=new_id,
                status="approval_inprogress",
                reason=f"Workflow failed: {e}",
                decided_by="system_error",
                approver_email=APPROVAL_EMAIL,
                model_decision="error",
                model_confidence=None,
                policy_citations=[],
                previous_case_refs=[],
            )
            return JSONResponse(content={"id": new_id, "data": result_dict, "approval": {"id": approval_id, "status": "approval_inprogress", "error": str(e)}})

    except HTTPException:
        raise
    except sqlite3.IntegrityError as e:
        error_msg = str(e)
        if "UNIQUE constraint failed: invoices.file_sha256" in error_msg:
            raise HTTPException(
                status_code=409,
                detail="duplicate file: This PDF file has already been submitted. Set force=true to override."
            )
        elif "UNIQUE constraint failed" in error_msg:
            raise HTTPException(
                status_code=409,
                detail=f"duplicate entry: {error_msg}. Set force=true to override."
            )
        raise HTTPException(status_code=500, detail=f"Database error: {error_msg}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        try:
            if 'temp_pdf_path' in locals() and os.path.exists(temp_pdf_path):
                os.remove(temp_pdf_path)
        except Exception:
            pass


# Run: uvicorn app:app --reload


@app.get("/invoices")
async def list_invoices(limit: int = 50, offset: int = 0):
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    return JSONResponse(content={"items": get_invoices(limit=limit, offset=offset)})


@app.get("/invoices/{invoice_id}")
async def get_invoice_by_id(invoice_id: int):
    row = get_invoice(invoice_id)
    if not row:
        raise HTTPException(status_code=404, detail="invoice not found")
    return JSONResponse(content=row)


# ---- Approvals API ----
@app.post("/approvals/start")
async def approvals_start(invoice_id: int):
    inv = get_invoice(invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="invoice not found")
    
    proposed = propose_decision(invoice_row=inv)
    decision = proposed.get("decision", "approval_inprogress")
    
    # Apply same override logic as persist_and_notify
    total_amount = inv.get("total_amount")
    confidence = proposed.get("confidence")
    
    should_override_to_inprogress = False
    override_reason = None
    
    if decision == "declined":
        # Check if amount exceeds threshold (should route to human approval, not decline)
        if total_amount and total_amount > 250:
            should_override_to_inprogress = True
            # Determine approval level based on amount
            if total_amount > 10000:
                approval_level = "executive"
            elif total_amount > 2500:
                approval_level = "finance manager"
            else:
                approval_level = "manager"
            override_reason = f"This invoice requires {approval_level} approval per policy (amount: ${total_amount:,.2f}). Routed for human review with recommendation."
        # Check if ambiguous (low confidence indicates uncertainty)
        elif confidence is not None and confidence < 0.7:
            should_override_to_inprogress = True
            override_reason = f"Invoice analysis indicates uncertainty (confidence: {confidence:.2f}). Routed for human review with recommendation."
        # Check if reason mentions ambiguity or uncertainty
        elif proposed.get("reason"):
            reason_lower = proposed.get("reason", "").lower()
            ambiguous_keywords = ["ambiguous", "unclear", "uncertain", "requires clarification", "needs review", "unable to determine", "unclear", "missing"]
            if any(keyword in reason_lower for keyword in ambiguous_keywords):
                should_override_to_inprogress = True
                override_reason = f"Invoice contains ambiguous or unclear information. Routed for human review with recommendation."
    
    # Apply override if needed
    if should_override_to_inprogress:
        decision = "approval_inprogress"
        # Clean up the reason - prefix with recommendation note if not already present
        original_reason = proposed.get("reason", "")
        if original_reason and not original_reason.startswith(("RECOMMENDATION:", "ANALYSIS:", "Recommendation:", "Analysis:")):
            # Prepend override reason and keep original analysis
            proposed["reason"] = f"{override_reason}\n\nAI Analysis: {original_reason}"
        else:
            proposed["reason"] = override_reason if override_reason else original_reason
    
    approval_id, token = create_approval(
        invoice_id=invoice_id,
        status=decision,
        reason=proposed.get("reason"),
        decided_by="auto",
        approver_email=APPROVAL_EMAIL,
        model_decision=proposed.get("decision"),  # Keep original model decision for audit
        model_confidence=proposed.get("confidence"),
        policy_citations=proposed.get("citations") or [],
        previous_case_refs=[], # This was simplified, may need to re-add list_prior_reasons if needed
    )
    if decision == "approval_inprogress":
        send_approval_email(approval_id, inv, proposed, token)
        
    return JSONResponse(content={"id": approval_id, "status": decision, "proposed": proposed})


@app.get("/approvals")
async def approvals_list(status: Optional[str] = None, limit: int = 50, offset: int = 0):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        if status:
            cur = conn.execute(
                "SELECT * FROM approvals WHERE status = ? ORDER BY id DESC LIMIT ? OFFSET ?",
                (status, limit, offset),
            )
        else:
            cur = conn.execute(
                "SELECT * FROM approvals ORDER BY id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
        return JSONResponse(content={"items": [dict(r) for r in cur.fetchall()]})
    finally:
        conn.close()


@app.get("/approvals/{approval_id}")
async def approvals_get(approval_id: int):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="approval not found")
        return JSONResponse(content=dict(row))
    finally:
        conn.close()


@app.get("/approvals/{approval_id}/review")
async def approvals_review(request: Request, approval_id: int, token: str, message: Optional[str] = None, error: Optional[str] = None, message_type: Optional[str] = None):
    """Display the approval review page with invoice details and approval form."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        # Get approval details
        cur = conn.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,))
        approval_row = cur.fetchone()
        if not approval_row:
            raise HTTPException(status_code=404, detail="approval not found")
        
        # Verify token
        created_at = approval_row["created_at"]
        if not verify_token(approval_id, created_at, token):
            raise HTTPException(status_code=403, detail="invalid token")
        
        approval = dict(approval_row)
        
        # Get invoice details
        invoice = get_invoice(approval["invoice_id"])
        if not invoice:
            raise HTTPException(status_code=404, detail="invoice not found")
        
        # Parse proposed decision from model_decision and policy_citations
        # If decided_by is "auto", the reason is the AI's proposed reason
        # If decided_by starts with "human:", the reason has been overwritten by human decision
        is_ai_reason = approval.get("decided_by") == "auto"
        proposed = {
            "decision": approval.get("model_decision") or approval.get("status"),
            "confidence": approval.get("model_confidence"),
            "reason": approval.get("reason") if is_ai_reason else None,  # Only show AI reason if not overwritten
            "citations": json.loads(approval.get("policy_citations") or "[]") if isinstance(approval.get("policy_citations"), str) else (approval.get("policy_citations") or []),
        }
        
        # Parse line items if stored as JSON string
        if isinstance(invoice.get("line_items"), str):
            try:
                invoice["line_items"] = json.loads(invoice["line_items"])
            except:
                invoice["line_items"] = []
        
        # Determine message type
        display_message = message or error
        display_message_type = message_type or ("error" if error else "success" if message else None)
        
        return templates.TemplateResponse(
            "approval_review.html",
            {
                "request": request,
                "approval": approval,
                "invoice": invoice,
                "proposed": proposed,
                "token": token,
                "message": display_message,
                "message_type": display_message_type,
            }
        )
    finally:
        conn.close()


@app.get("/approvals/{approval_id}/decide")
async def approvals_decide_get(approval_id: int, action: str, token: str, reason: Optional[str] = None):
    """Handle GET requests - redirect to review page."""
    # Redirect to review page (for backward compatibility with old email links)
    return RedirectResponse(url=f"/approvals/{approval_id}/review?token={token}", status_code=303)


@app.post("/approvals/{approval_id}/decide")
async def approvals_decide_post(
    approval_id: int,
    action: str = Form(...),
    token: str = Form(...),
    reason: Optional[str] = Form(None)
):
    """Handle POST requests from the review form - process the decision."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute("SELECT created_at, status FROM approvals WHERE id = ?", (approval_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="approval not found")
        created_at = row[0]
        current_status = row[1]
        
        if not verify_token(approval_id, created_at, token):
            raise HTTPException(status_code=403, detail="invalid token")
        
        # Check if already decided
        if current_status not in ("approval_inprogress",):
            return RedirectResponse(
                url=f"/approvals/{approval_id}/review?token={token}&message=This approval has already been {current_status}",
                status_code=303
            )
    finally:
        conn.close()

    act = action.lower()
    if act not in ("approve", "decline"):
        raise HTTPException(status_code=400, detail="action must be approve or decline")

    if not reason or not reason.strip():
        # Redirect back with error if reason is missing
        return RedirectResponse(
            url=f"/approvals/{approval_id}/review?token={token}&error=Reason is required",
            status_code=303
        )

    new_status = "approved" if act == "approve" else "declined"
    update_approval_status(approval_id, new_status, reason, decided_by=f"human:{APPROVAL_EMAIL or 'approver'}")
    
    # Redirect back to review page with success message
    message = f"Invoice has been {new_status} successfully!"
    return RedirectResponse(
        url=f"/approvals/{approval_id}/review?token={token}&message={message}&message_type=success",
        status_code=303
    )


# ---- Email preview/send endpoints for branded template ----
@app.post("/emails/approval/preview")
async def email_approval_preview(payload: Dict[str, Any] = Body(...)):
    rendered = render_brand_approval_email(payload)
    return JSONResponse(content=rendered)


@app.post("/emails/approval/send")
async def email_approval_send(payload: Dict[str, Any] = Body(...), to: Optional[str] = None, template_id: Optional[str] = None):
    rendered = render_brand_approval_email(payload)
    recipient = to or APPROVAL_EMAIL
    if not SENDGRID_API_KEY or not FROM_EMAIL or not recipient:
        return JSONResponse(content={"note": "Missing SendGrid config; printing email", "subject": rendered["subject"], "html": rendered["html"]})

    # Prefer explicit template_id param; otherwise default to env SENDGRID_TEMPLATE_ID
    effective_template_id = template_id or SENDGRID_TEMPLATE_ID

    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        if effective_template_id:
            message = Mail(from_email=FROM_EMAIL, to_emails=recipient)
            message.template_id = effective_template_id
            # pass through user's payload as dynamic data
            message.dynamic_template_data = payload
        else:
            message = Mail(from_email=FROM_EMAIL, to_emails=recipient, subject=rendered["subject"], html_content=rendered["html"])
        sg.send(message)
        return JSONResponse(content={"status": "sent", "to": recipient})
    except Exception as e:
        return JSONResponse(content={"status": "error", "error": str(e)}, status_code=500)