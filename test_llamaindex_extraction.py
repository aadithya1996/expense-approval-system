#!/usr/bin/env python3
"""
Test script for LlamaIndex PDF extraction with JSON output.

Extracts invoice data in JSON format matching the invoices table structure.
Usage: python3 test_llamaindex_extraction.py <path_to_pdf>
"""

import sys
import os
import json
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add current directory to path
sys.path.insert(0, os.path.dirname(__file__))

try:
    from pdf_extraction_llamaindex import extract_text_from_pdf_llamaindex
    from openai import OpenAI as OpenAIClient
    print("✅ Successfully imported required modules")
except ImportError as e:
    print(f"❌ Import error: {e}")
    print("\nMake sure llama-index and openai are installed:")
    print("  pip install llama-index openai python-dotenv")
    sys.exit(1)


def extract_invoice_json(pdf_path: str) -> dict:
    """
    Extract invoice data in JSON format matching invoices table structure.
    
    Returns JSON matching:
    - invoice_id (or invoice_number)
    - supplier_name
    - invoice_date (ISO format YYYY-MM-DD)
    - total_amount (number)
    - currency (e.g., "USD", "INR")
    - line_items (array of objects with description, quantity, unit_price, total)
    """
    # Step 1: Extract text using LlamaIndex
    print("\n📄 Step 1: Extracting text from PDF using LlamaIndex...")
    full_text = extract_text_from_pdf_llamaindex(pdf_path)
    
    if not full_text:
        print("❌ Could not extract text from PDF")
        return {}
    
    print(f"✅ Extracted {len(full_text)} characters")
    
    # Step 2: Use LLM to extract structured data
    print("\n🤖 Step 2: Extracting structured data using LLM...")
    
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("❌ OPENAI_API_KEY not found in environment variables")
        return {}
    
    client = OpenAIClient(api_key=api_key)
    
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
        
        # Clean supplier name (remove Kaladeofin)
        if result_dict.get("supplier_name"):
            import re
            supplier = result_dict["supplier_name"]
            cleaned = re.sub(r'\bKaladeofin\b', '', supplier, flags=re.IGNORECASE)
            cleaned = re.sub(r'\s+', ' ', cleaned).strip()
            cleaned = cleaned.rstrip(' ,-')
            result_dict["supplier_name"] = cleaned if cleaned else None
        
        print("✅ Successfully extracted structured data")
        return result_dict
        
    except Exception as e:
        print(f"❌ Error during LLM extraction: {e}")
        return {}


def test_extraction(pdf_path: str):
    """Test PDF extraction and display JSON output."""
    if not os.path.exists(pdf_path):
        print(f"❌ File not found: {pdf_path}")
        return False
    
    print(f"\n📄 Testing PDF extraction: {pdf_path}")
    print("=" * 60)
    
    # Extract invoice data
    invoice_data = extract_invoice_json(pdf_path)
    
    if not invoice_data:
        print("\n❌ Failed to extract invoice data")
        return False
    
    # Display results
    print("\n📋 Extracted Invoice Data (JSON format):")
    print("=" * 60)
    print(json.dumps(invoice_data, indent=2, ensure_ascii=False))
    
    # Show what would be stored in database
    print("\n💾 Database Storage Format:")
    print("=" * 60)
    
    db_format = {
        "filename": os.path.basename(pdf_path),
        "supplier_name": invoice_data.get("supplier_name"),
        "invoice_date": invoice_data.get("invoice_date"),
        "total_amount": invoice_data.get("total_amount"),
        "currency": invoice_data.get("currency"),
        "line_items": json.dumps(invoice_data.get("line_items", []), ensure_ascii=False),
        "raw_json": json.dumps(invoice_data, ensure_ascii=False)
    }
    
    print(json.dumps(db_format, indent=2, ensure_ascii=False))
    
    # Summary
    print("\n📊 Summary:")
    print("=" * 60)
    print(f"Invoice ID: {invoice_data.get('invoice_id') or invoice_data.get('invoice_number') or 'N/A'}")
    print(f"Supplier: {invoice_data.get('supplier_name') or 'N/A'}")
    print(f"Date: {invoice_data.get('invoice_date') or 'N/A'}")
    print(f"Amount: {invoice_data.get('currency') or 'USD'} {invoice_data.get('total_amount') or 'N/A'}")
    print(f"Line Items: {len(invoice_data.get('line_items', []))} items")
    
    print("\n" + "=" * 60)
    print("✅ Extraction completed successfully!")
    return True


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 test_llamaindex_extraction.py <path_to_pdf>")
        print("\nExample:")
        print("  python3 test_llamaindex_extraction.py Invoice_11203.pdf")
        print("  python3 test_llamaindex_extraction.py \"Invoice 11203.pdf\"")
        sys.exit(1)
    
    # Join all arguments in case filename has spaces
    pdf_path = " ".join(sys.argv[1:])
    test_extraction(pdf_path)

