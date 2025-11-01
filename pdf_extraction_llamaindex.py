"""
Alternative PDF extraction implementation using LlamaIndex.

This file demonstrates how to use LlamaIndex for PDF extraction
as an alternative to pypdf. It can be integrated into the existing
app.py if desired, but keeps the original pypdf implementation intact.

LlamaIndex Advantages:
- Better handling of complex PDF layouts
- Table extraction capabilities
- Structured document parsing
- Can extract sections, headings, and paragraphs
- Better for invoices with complex formatting
"""

import tempfile
import os
from typing import Optional

try:
    # Try newer LlamaIndex API (v0.10+)
    from llama_index.core import SimpleDirectoryReader, Document
    from llama_index.readers.file import PyPDFReader
except ImportError:
    try:
        # Fallback to older API
        from llama_index import SimpleDirectoryReader, Document
        from llama_index.readers.file import PyPDFReader
    except ImportError:
        # If PDF reader not available, use SimpleDirectoryReader which supports PDFs
        from llama_index.core import SimpleDirectoryReader, Document
        PyPDFReader = None


def extract_text_from_pdf_llamaindex(temp_pdf_path: str) -> str:
    """
    Extract text from PDF using LlamaIndex PyPDFReader.
    
    This is an alternative to the pypdf-based extraction in app.py.
    LlamaIndex provides better handling of complex layouts and tables.
    
    Args:
        temp_pdf_path: Path to temporary PDF file
        
    Returns:
        Extracted text as string
    """
    try:
        # Use SimpleDirectoryReader which handles PDFs natively
        # Create a temporary directory approach
        temp_dir = os.path.dirname(temp_pdf_path)
        pdf_filename = os.path.basename(temp_pdf_path)
        
        # Option 1: Use SimpleDirectoryReader (works with PDFs)
        reader = SimpleDirectoryReader(
            input_files=[temp_pdf_path],
            filename_as_id=True
        )
        documents = reader.load_data()
        
        # Extract text from all pages
        text_parts = []
        for doc in documents:
            text_content = doc.text or ""
            if text_content.strip():
                text_parts.append(text_content)
        
        # Combine all pages with page breaks
        full_text = "\n\n".join(text_parts).strip()
        return full_text
        
    except Exception as e:
        print(f"Error extracting PDF text with LlamaIndex: {e}")
        # Fallback to empty string
        return ""


def extract_text_from_pdf_simple_directory(temp_pdf_path: str) -> str:
    """
    Alternative: Extract text using SimpleDirectoryReader.
    
    This approach loads the PDF from a directory structure.
    Useful for batch processing multiple PDFs.
    
    Args:
        temp_pdf_path: Path to temporary PDF file
        
    Returns:
        Extracted text as string
    """
    try:
        # Get directory and filename
        temp_dir = os.path.dirname(temp_pdf_path)
        pdf_filename = os.path.basename(temp_pdf_path)
        
        # Use SimpleDirectoryReader - reads from directory
        reader = SimpleDirectoryReader(
            input_dir=temp_dir,
            filename_as_id=True,
            file_metadata=lambda filename: {"source": filename}
        )
        
        # Load documents
        documents = reader.load_data()
        
        # Filter to get only our PDF
        pdf_docs = [doc for doc in documents if pdf_filename in doc.metadata.get("source", "")]
        
        # Extract text
        text_parts = []
        for doc in pdf_docs:
            text_content = doc.text or ""
            if text_content.strip():
                text_parts.append(text_content)
        
        full_text = "\n\n".join(text_parts).strip()
        return full_text
        
    except Exception as e:
        print(f"Error extracting PDF text with SimpleDirectoryReader: {e}")
        return ""


def extract_text_from_pdf_with_metadata(temp_pdf_path: str) -> dict:
    """
    Extract text from PDF using LlamaIndex with metadata.
    
    Returns both text content and metadata (page numbers, etc.)
    
    Args:
        temp_pdf_path: Path to temporary PDF file
        
    Returns:
        Dictionary with 'text' and 'metadata' keys
    """
    try:
        reader = SimpleDirectoryReader(
            input_files=[temp_pdf_path],
            filename_as_id=True
        )
        documents = reader.load_data()
        
        text_parts = []
        metadata_list = []
        
        for i, doc in enumerate(documents):
            text_content = doc.text or ""
            if text_content.strip():
                text_parts.append(text_content)
                # Extract metadata
                metadata = {
                    "page": i + 1,
                    "source": doc.metadata.get("source", temp_pdf_path),
                    "file_path": doc.metadata.get("file_path", temp_pdf_path),
                    "file_name": doc.metadata.get("file_name", os.path.basename(temp_pdf_path)),
                }
                metadata_list.append(metadata)
        
        full_text = "\n\n".join(text_parts).strip()
        
        return {
            "text": full_text,
            "metadata": metadata_list,
            "page_count": len(documents)
        }
        
    except Exception as e:
        print(f"Error extracting PDF with metadata: {e}")
        return {
            "text": "",
            "metadata": [],
            "page_count": 0
        }


# Example integration function (for reference)
def extract_invoice_with_llamaindex(pdf_path: str) -> dict:
    """
    Complete example: Extract invoice data using LlamaIndex + LLM.
    
    This shows how you could replace the current extraction flow
    in app.py with LlamaIndex-based extraction.
    
    Args:
        pdf_path: Path to PDF file
        
    Returns:
        Dictionary with extracted invoice data
    """
    from openai import OpenAI as OpenAIClient
    import json
    import os
    
    # Extract text using LlamaIndex
    extraction_result = extract_text_from_pdf_with_metadata(pdf_path)
    full_text = extraction_result["text"]
    
    if not full_text:
        return {}
    
    # Use LLM to extract structured data (same as current implementation)
    client = OpenAIClient(api_key=os.getenv("OPENAI_API_KEY"))
    
    extraction_prompt = f"""
    Parse the following invoice text and extract key information into JSON format.
    Extract: invoice_id (or invoice_number), supplier_name, invoice_date (ISO format YYYY-MM-DD), 
    total_amount (number), currency (e.g., "USD", "INR"), and line_items (array of objects with 
    description, quantity, unit_price, total).
    
    IMPORTANT: For supplier_name:
    - Extract the supplier/vendor name from "From" column or header
    - DO NOT include "Kaladeofin" in the supplier name (Kaladeofin is the recipient)
    - The supplier is the entity FROM whom the invoice is received
    
    If a field is not present, leave it null. Do not hallucinate.
    
    Invoice Text:
    {full_text[:8000]}
    """
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are an invoice data extraction assistant."},
                {"role": "user", "content": extraction_prompt}
            ],
            response_format={"type": "json_object"}
        )
        
        result_dict = json.loads(response.choices[0].message.content)
        return result_dict
        
    except Exception as e:
        print(f"Error during LLM extraction: {e}")
        return {}


if __name__ == "__main__":
    # Example usage
    print("LlamaIndex PDF Extraction Alternative")
    print("=" * 50)
    print("\nThis module provides alternative PDF extraction methods")
    print("using LlamaIndex instead of pypdf.")
    print("\nFunctions available:")
    print("- extract_text_from_pdf_llamaindex()")
    print("- extract_text_from_pdf_simple_directory()")
    print("- extract_text_from_pdf_with_metadata()")
    print("- extract_invoice_with_llamaindex()")
    print("\nTo use in app.py, replace extract_text_from_pdf() calls")
    print("with extract_text_from_pdf_llamaindex()")

