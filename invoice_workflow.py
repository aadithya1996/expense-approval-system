
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from openai import OpenAI as OpenAIClient
from pydantic import BaseModel, Field

from helper import (
    APPROVAL_EMAIL,
    APPROVAL_PROMPT_PATH,
    OPENAI_API_KEY,
    POLICY_FILE_PATH,
    create_approval,
    get_invoice,
    get_approval_level,
    get_approver_name,
    list_prior_reasons,
    load_text_safe,
    send_approval_email,
)


# Define the output model for the LLM's decision
class DecisionModel(BaseModel):
    decision: str = Field(description="The approval decision: 'approved', 'declined', or 'approval_inprogress'")
    reason: Optional[str] = Field(None, description="Reason for the decision")
    confidence: Optional[float] = Field(None, description="Confidence level (0.0-1.0)")
    citations: Optional[List[str]] = Field(None, description="Policy citations")


def detect_alcohol_items(line_items: List[Dict[str, Any]], client: OpenAIClient) -> Dict[str, Any]:
    """
    Enhanced alcohol detection using LLM to identify alcohol brands and items.
    Returns dict with 'has_alcohol' (bool) and 'alcohol_items' (list of detected items).
    """
    if not line_items:
        return {"has_alcohol": False, "alcohol_items": []}
    
    # Basic keyword check first (fast)
    # These keywords strongly indicate alcohol - if found, definitely check with LLM
    alcohol_keywords = [
        # Alcohol types
        "alcohol", "beer", "wine", "vodka", "whiskey", "whisky", "rum", "gin", "tequila", "liqueur", 
        "spirits", "liquor", "champagne", "cognac", "brandy", "port", "sherry", "sake",
        # Alcohol indicators
        "malt", "hops", "barley", "fermented", "distilled", "brew", "brewing",
        # Cocktails/drinks
        "mojito", "margarita", "martini", "cocktail", "shot", "pint", "bottle",
        # Venues/establishments
        "brewery", "distillery", "winery", "bar", "pub", "tavern", "tap room", "taproom",
        # Brand names (common alcohol brands)
        "absolut", "singha", "smirnoff", "budweiser", "heineken", "corona", "jack daniel", 
        "miller", "coors", "stella", "guinness", "chivas", "johnnie walker", "hennessy",
        "bira", "bacardi", "jim beam", "maker's mark", "patron", "grey goose", "belvedere",
        "jose cuervo", "captain morgan", "baileys", "kahlua", "grand marnier"
    ]
    
    # Check all items - even if no keywords match, use LLM to catch brand names
    suspicious_items = []
    for item in line_items:
        description = str(item.get("description", "")).lower()
        # If keyword matches, definitely suspicious
        if any(keyword in description for keyword in alcohol_keywords):
            suspicious_items.append(item)
        # Also check for potential alcohol indicators even without keywords
        # Look for patterns: brand names, "single malt", "draft", etc.
        elif any(indicator in description for indicator in ["single malt", "double malt", "draft", "ipa", "lager", "ale", "stout"]):
            suspicious_items.append(item)
    
    # ALWAYS use LLM to check items for alcohol, even if no keywords matched
    # This catches brand names and context that keywords miss
    if not suspicious_items:
        # No keywords matched, but still check all items with LLM
        # (LLM is good at identifying alcohol brands even if not in keyword list)
        suspicious_items = line_items
    
    # Use LLM to verify if suspicious items are actually alcohol
    try:
        items_json = json.dumps(suspicious_items, ensure_ascii=False)
        prompt = f"""Analyze the following invoice line items and determine if ANY of them contain alcohol, alcoholic beverages, or alcohol-related products.

For each item, classify it as:
- "alcohol" if it's an alcoholic beverage (beer, wine, spirits, liquor, etc.) or contains alcohol
- "non_alcohol" if it's clearly not alcohol-related

Consider:
- Brand names (Absolut, Smirnoff, Budweiser, etc.)
- Product types (beer, wine, vodka, whiskey, etc.)
- Context clues (brewery, distillery, bar, etc.)

Line Items:
{items_json}

Respond with JSON format:
{{
  "has_alcohol": true/false,
  "alcohol_items": [
    {{"description": "...", "reason": "why it's alcohol"}}
  ]
}}"""
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are an alcohol detection assistant. Analyze invoice line items to identify alcoholic beverages."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"}
        )
        
        result = json.loads(response.choices[0].message.content)
        return {
            "has_alcohol": result.get("has_alcohol", False),
            "alcohol_items": result.get("alcohol_items", [])
        }
    except Exception as e:
        print(f"[WORKFLOW] Error in alcohol detection: {e}")
        # Fallback to basic keyword check
        return {
            "has_alcohol": len(suspicious_items) > 0,
            "alcohol_items": suspicious_items
        }


def propose_decision(invoice_row: Dict[str, Any]) -> Dict[str, Any]:
    """Uses an LLM to make an approval decision based on policy and context."""
    print(f"[WORKFLOW] Step: Proposing decision for Invoice #{invoice_row.get('id')}")
    policy_text = load_text_safe(POLICY_FILE_PATH)
    prior = list_prior_reasons()
    
    # Get current date in readable format
    now = datetime.utcnow()
    current_date_readable = now.strftime("%Y-%m-%d")  # e.g., "2025-10-30"
    current_date_full = now.isoformat()  # Full ISO format for reference
    
    # Calculate days difference if invoice date is available
    invoice_date_str = invoice_row.get("invoice_date")
    days_diff = None
    if invoice_date_str:
        try:
            from dateutil.parser import parse as parse_date
            invoice_date = parse_date(invoice_date_str).date()
            days_diff = (now.date() - invoice_date).days
            print(f"[WORKFLOW] Invoice date: {invoice_date_str}, Current date: {current_date_readable}, Days difference: {days_diff}")
        except Exception as e:
            print(f"[WORKFLOW] Could not parse invoice date '{invoice_date_str}': {e}")

    template = load_text_safe(APPROVAL_PROMPT_PATH)
    
    # Format the prompt with clearer date information
    date_info = f"Current Date: {current_date_readable}"
    if days_diff is not None:
        date_info += f" | Invoice Date: {invoice_date_str} | Days Since Invoice: {days_diff}"
    
    # Determine approver information based on amount
    total_amount = invoice_row.get("total_amount")
    approval_level = get_approval_level(total_amount)
    approver_name = get_approver_name(total_amount)
    
    # Trust LLM intelligence - it sees all line items and can detect alcohol from context
    # Examples: "Bira Single Malt" (malt = whiskey), "tap room" (bar), brand names, etc.
    # The LLM will analyze and flag alcohol in its decision/reason/citations
    # No need for separate alcohol detection - let LLM handle it intelligently
    
    prompt_text = template.format(
        invoice=json.dumps(invoice_row, ensure_ascii=False),
        policy=policy_text,
        prior=json.dumps(prior, ensure_ascii=False),
        current_date=date_info,
        approval_level=approval_level,
        approver_name=approver_name,
    )
    
    # Use OpenAI directly with structured outputs
    client = OpenAIClient(api_key=OPENAI_API_KEY)
    
    try:
        completion = client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are an invoice approval assistant. Analyze the invoice against the policy and provide a structured decision."},
                {"role": "user", "content": prompt_text}
            ],
            response_format=DecisionModel,
        )
        
        result = completion.choices[0].message.parsed
        decision_dict = result.model_dump()
        print(f"[WORKFLOW] LLM Decision: {decision_dict.get('decision')}")
        return decision_dict
    except Exception as e:
        print(f"[WORKFLOW] Error calling OpenAI: {e}")
        # Fallback to manual approval
        return {
            "decision": "approval_inprogress",
            "reason": f"Error during LLM analysis: {str(e)}",
            "confidence": None,
            "citations": None
        }


def persist_and_notify(invoice_id: int, proposed: Dict[str, Any]):
    """
    Saves the approval record to the database and sends a notification email
    if human approval is required.
    """
    print(f"[WORKFLOW] Step: Persisting approval for Invoice #{invoice_id}")
    decision = proposed.get("decision", "approval_inprogress")
    
    # Get invoice to check amount and determine if we need to override declined status
    invoice_row = get_invoice(invoice_id)
    if not invoice_row:
        print(f"[WORKFLOW] ERROR: Invoice #{invoice_id} not found in database")
        raise ValueError(f"Invoice {invoice_id} not found")
    
    # Auto-approve logic: If amount ≤ $250 and meets basic criteria, auto-approve regardless of LLM decision
    # CRITICAL: Check amount threshold FIRST before any other checks
    total_amount = invoice_row.get("total_amount") if invoice_row else None
    
    if total_amount and total_amount <= 250:
        print(f"[WORKFLOW] Checking auto-approval eligibility for amount: ${total_amount:,.2f}")
        
        # Parse line items
        line_items = invoice_row.get("line_items") if invoice_row else None
        if isinstance(line_items, str):
            try:
                line_items = json.loads(line_items)
            except:
                line_items = []
        
        # Trust LLM's intelligence - check if LLM detected alcohol/disallowed items
        # LLM sees all line items and should detect alcohol from "Bira Single Malt", "tap room", etc.
        has_alcohol = False
        
        # Check citations for alcohol-related policy sections
        citations = proposed.get("citations", [])
        if citations:
            if any("alcohol" in str(citation).lower() for citation in citations):
                has_alcohol = True
                print(f"[WORKFLOW] Auto-approval BLOCKED: LLM detected alcohol (citations: {citations})")
        
        # Check if reason mentions alcohol/disallowed items
        reason = proposed.get("reason", "")
        if reason:
            alcohol_keywords = ["alcohol", "beer", "wine", "vodka", "whiskey", "whisky", "rum", "gin", 
                               "tequila", "liqueur", "spirits", "liquor", "champagne", "disallowed",
                               "malt", "bira", "absolut", "prohibited", "violates policy"]
            if any(keyword in reason.lower() for keyword in alcohol_keywords):
                has_alcohol = True
                print(f"[WORKFLOW] Auto-approval BLOCKED: LLM reason mentions alcohol/disallowed items")
        
        # Also check decision - if LLM declined, don't auto-approve
        if proposed.get("decision") == "declined":
            has_alcohol = True
            print(f"[WORKFLOW] Auto-approval BLOCKED: LLM decision is 'declined'")
        
        if has_alcohol:
            print(f"[WORKFLOW] Auto-approval BLOCKED: Alcohol detected in line items or by LLM")
            # Don't auto-approve, let LLM handle it (should decline)
            decision = proposed.get("decision", "approval_inprogress")
        else:
            # Check for other disallowed items (weapons, gambling, etc.)
            disallowed_keywords = ["weapon", "firearm", "knife", "gambling", "casino", "lottery"]
            has_disallowed_items = False
            if line_items:
                for item in line_items:
                    description = str(item.get("description", "")).lower()
                    if any(keyword in description for keyword in disallowed_keywords):
                        has_disallowed_items = True
                        print(f"[WORKFLOW] Auto-approval blocked: Disallowed item found: {description[:50]}")
                        break
            
            if not has_disallowed_items:
                # Check if invoice has required fields
                has_supplier = bool(invoice_row.get("supplier_name") if invoice_row else None)
                has_invoice_date = bool(invoice_row.get("invoice_date") if invoice_row else None)
                has_line_items = bool(line_items and len(line_items) > 0)
                
                # Auto-approve if: no disallowed items, has supplier, has date, has line items
                if has_supplier and has_invoice_date and has_line_items:
                    # Check if invoice date is within 180 days
                    invoice_date_str = invoice_row.get("invoice_date") if invoice_row else None
                    if invoice_date_str:
                        try:
                            from dateutil.parser import parse as parse_date
                            invoice_date = parse_date(invoice_date_str).date()
                            days_diff = (datetime.utcnow().date() - invoice_date).days
                            if days_diff > 180:
                                print(f"[WORKFLOW] Auto-approval blocked: Invoice date is {days_diff} days old (> 180 days)")
                            else:
                                # Auto-approve this invoice
                                decision = "approved"
                                proposed["reason"] = f"Invoice amount (${total_amount:,.2f}) is within auto-approval threshold (≤ $250). All policy requirements met: supplier verified, invoice date within 180 days, no disallowed items."
                                print(f"[WORKFLOW] ✅ Auto-approving invoice: Amount ${total_amount:,.2f} ≤ $250, meets all criteria")
                        except Exception as e:
                            print(f"[WORKFLOW] Could not verify invoice date for auto-approval: {e}")
                    else:
                        print(f"[WORKFLOW] Auto-approval blocked: Missing invoice date")
                else:
                    missing_items = []
                    if not has_supplier:
                        missing_items.append("supplier name")
                    if not has_invoice_date:
                        missing_items.append("invoice date")
                    if not has_line_items:
                        missing_items.append("line items")
                    print(f"[WORKFLOW] Auto-approval blocked: Missing/invalid - {', '.join(missing_items)}")
    else:
        if total_amount:
            print(f"[WORKFLOW] Amount ${total_amount:,.2f} exceeds auto-approval threshold (> $250), requires human approval")
        else:
            print(f"[WORKFLOW] Cannot determine auto-approval: Missing total_amount")
    
    # Use proposed decision if not already auto-approved
    if decision != "approved":
        decision = proposed.get("decision", "approval_inprogress")
    confidence = proposed.get("confidence")
    
    # Override logic: If declined but amount > $250 OR ambiguous (low confidence), route to human approval
    # Only allow "declined" for clear policy violations (disallowed items, missing critical info)
    # Skip override logic if invoice was already auto-approved
    should_override_to_inprogress = False
    override_reason = None
    
    # Only process override logic if invoice wasn't auto-approved above
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
            print(f"[WORKFLOW] Overriding 'declined' to 'approval_inprogress' - amount ${total_amount:,.2f} exceeds $250 threshold")
        # Check if ambiguous (low confidence indicates uncertainty)
        elif confidence is not None and confidence < 0.7:
            should_override_to_inprogress = True
            override_reason = f"Invoice analysis indicates uncertainty (confidence: {confidence:.2f}). Routed for human review with recommendation."
            print(f"[WORKFLOW] Overriding 'declined' to 'approval_inprogress' - low confidence ({confidence:.2f}) indicates ambiguity")
        # Check if reason mentions ambiguity or uncertainty
        elif proposed.get("reason"):
            reason_lower = proposed.get("reason", "").lower()
            ambiguous_keywords = ["ambiguous", "unclear", "uncertain", "requires clarification", "needs review", "unable to determine", "unclear", "missing"]
            if any(keyword in reason_lower for keyword in ambiguous_keywords):
                should_override_to_inprogress = True
                override_reason = f"Invoice contains ambiguous or unclear information. Routed for human review with recommendation."
                print(f"[WORKFLOW] Overriding 'declined' to 'approval_inprogress' - reason indicates ambiguity")
    
    # Apply override if needed
    if should_override_to_inprogress:
        decision = "approval_inprogress"
        # Use the original reason if it's already well-formatted, otherwise create a concise override
        original_reason = proposed.get("reason", "")
        if original_reason and original_reason.startswith(("RECOMMENDATION:", "ANALYSIS:", "Recommendation:", "Analysis:")):
            # Already formatted as recommendation, use as-is
            proposed["reason"] = original_reason
        elif original_reason and ("disallowed" in original_reason.lower() or "alcohol" in original_reason.lower() or "prohibited" in original_reason.lower()):
            # Contains disallowed items - keep original reason but ensure it's concise
            # Remove any verbose prefixes that might have been added
            proposed["reason"] = original_reason.replace("AI Analysis: ", "").strip()
        else:
            # Create concise override for amount-based routing
            if total_amount:
                if total_amount > 10000:
                    approval_level = "executive"
                elif total_amount > 2500:
                    approval_level = "finance manager"
                else:
                    approval_level = "manager"
                proposed["reason"] = f"Invoice amount (${total_amount:,.2f}) requires {approval_level} approval per policy threshold."
            else:
                proposed["reason"] = override_reason if override_reason else original_reason
        print(f"[WORKFLOW] Decision overridden: declined → approval_inprogress")

    approval_id, token = create_approval(
        invoice_id=invoice_id,
        status=decision,
        reason=proposed.get("reason"),
        decided_by="auto",
        approver_email=APPROVAL_EMAIL,
        model_decision=proposed.get("decision"),  # Keep original model decision for audit
        model_confidence=proposed.get("confidence"),
        policy_citations=proposed.get("citations") or [],
        previous_case_refs=[r.get("reason") for r in list_prior_reasons()],
    )
    print(f"[WORKFLOW] Approval record #{approval_id} created with status: {decision}")

    # Send email if status is "approval_inprogress" (including overridden cases)
    if decision == "approval_inprogress":
        if not invoice_row:
            print(f"[WORKFLOW] WARNING: Invoice #{invoice_id} not found, cannot send email")
        else:
            send_approval_email(approval_id, invoice_row, proposed, token)
            print(f"[WORKFLOW] Triggering notification email (status: approval_inprogress)")
    else:
        print(f"[WORKFLOW] Status is '{decision}', no notification needed.")
    
    return {"approval_id": approval_id, "status": decision}


def run_approval_workflow(invoice_row: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main workflow function that orchestrates the approval process.
    """
    # Step 1: Get LLM decision
    proposed = propose_decision(invoice_row)
    
    # Step 2: Persist and notify
    result = persist_and_notify(invoice_row["id"], proposed)
    
    return result
