# LlamaIndex PDF Extraction Alternative

This document explains how to use LlamaIndex for PDF extraction as an alternative to pypdf.

## Overview

The file `pdf_extraction_llamaindex.py` provides alternative PDF extraction methods using LlamaIndex. This keeps the original `app.py` implementation with pypdf intact while offering a more advanced option.

## Why LlamaIndex?

**Advantages over pypdf:**
- Better handling of complex PDF layouts
- Table extraction capabilities
- Structured document parsing (sections, headings, paragraphs)
- Better preservation of document structure
- Metadata extraction (page numbers, document info)
- More robust for invoices with complex formatting

## Installation

Additional package required:
```bash
pip install llama-index-readers-file
```

## Usage Options

### Option 1: Simple Text Extraction
```python
from pdf_extraction_llamaindex import extract_text_from_pdf_llamaindex

text = extract_text_from_pdf_llamaindex("invoice.pdf")
```

### Option 2: Extraction with Metadata
```python
from pdf_extraction_llamaindex import extract_text_from_pdf_with_metadata

result = extract_text_from_pdf_with_metadata("invoice.pdf")
text = result["text"]
metadata = result["metadata"]
page_count = result["page_count"]
```

### Option 3: Complete Invoice Extraction
```python
from pdf_extraction_llamaindex import extract_invoice_with_llamaindex

invoice_data = extract_invoice_with_llamaindex("invoice.pdf")
```

## Integration with app.py

To integrate LlamaIndex into `app.py` without changing the existing code:

1. **Import the alternative function:**
   ```python
   from pdf_extraction_llamaindex import extract_text_from_pdf_llamaindex
   ```

2. **Replace the extraction call** (line 91 in app.py):
   ```python
   # Change from:
   full_text = extract_text_from_pdf(temp_pdf_path)
   
   # To:
   full_text = extract_text_from_pdf_llamaindex(temp_pdf_path)
   ```

3. **Or use metadata extraction:**
   ```python
   from pdf_extraction_llamaindex import extract_text_from_pdf_with_metadata
   
   extraction_result = extract_text_from_pdf_with_metadata(temp_pdf_path)
   full_text = extraction_result["text"]
   # You can also use extraction_result["metadata"] for page info
   ```

## Comparison

| Feature | pypdf | LlamaIndex |
|---------|-------|-----------|
| Basic text extraction | ✅ | ✅ |
| Table extraction | ❌ | ✅ |
| Metadata extraction | Limited | ✅ |
| Complex layouts | Basic | Advanced |
| Page-level info | ✅ | ✅ |
| Document structure | ❌ | ✅ |

## Testing

Test the LlamaIndex extraction:
```python
import tempfile
from pdf_extraction_llamaindex import extract_text_from_pdf_llamaindex

# Test with a PDF file
text = extract_text_from_pdf_llamaindex("test_invoice.pdf")
print(f"Extracted {len(text)} characters")
print(text[:500])  # Preview first 500 chars
```

## Notes

- LlamaIndex may be slightly slower than pypdf for simple PDFs
- For complex invoices with tables, LlamaIndex performs better
- Both libraries can coexist - you can switch between them
- The original `app.py` remains unchanged

