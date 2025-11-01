# LlamaIndex PDF Extraction - Prompt Usage Explained

## Current Implementation (No Prompt to LlamaIndex)

### Current Flow:

```
PDF File
   ↓
LlamaIndex SimpleDirectoryReader (NO PROMPT)
   ↓
Raw Text Extraction (just reads PDF text)
   ↓
Plain Text String
   ↓
OpenAI LLM with Prompt (extracts structured data)
   ↓
JSON Data
```

**LlamaIndex's Role**: Just extracts raw text (like pypdf did)
**Prompt Usage**: Happens AFTER text extraction, sent to OpenAI LLM

### Current Code:

```python
# Step 1: LlamaIndex extracts RAW TEXT (no prompt)
def extract_text_from_pdf_llamaindex(temp_pdf_path: str) -> str:
    reader = SimpleDirectoryReader(input_files=[temp_pdf_path])
    documents = reader.load_data()
    text = "\n\n".join([doc.text for doc in documents])
    return text  # Just plain text, no structured extraction

# Step 2: OpenAI LLM extracts STRUCTURED DATA (with prompt)
extraction_prompt = f"""
Parse the following invoice text and extract key information...
Invoice Text: {full_text}
"""
response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": extraction_prompt}],
    response_format={"type": "json_object"}
)
```

## Can We Use Prompts with LlamaIndex?

**Yes, but it's not necessary** for our use case. Here's why:

### Option 1: LlamaIndex Query Engine (with Prompt)

```python
from llama_index.core import VectorStoreIndex
from llama_index.core import Settings

# Create index from PDF
reader = SimpleDirectoryReader(input_files=[temp_pdf_path])
documents = reader.load_data()
index = VectorStoreIndex.from_documents(documents)

# Query with prompt
query_engine = index.as_query_engine()
response = query_engine.query(
    "Extract invoice number, supplier name, date, total amount, and line items"
)
```

**Pros:**
- LlamaIndex can use LLM to query the document
- Can extract structured data directly

**Cons:**
- More complex setup
- Requires vector store/embedding
- Overkill for simple text extraction
- We already do structured extraction with OpenAI

### Option 2: LlamaIndex with Pydantic Structured Outputs

```python
from llama_index.core.program import LLMTextCompletionProgram
from pydantic import BaseModel

class InvoiceData(BaseModel):
    invoice_id: str
    supplier_name: str
    invoice_date: str
    total_amount: float
    line_items: List[Dict]

# Use LlamaIndex to extract with structured output
program = LLMTextCompletionProgram.from_defaults(
    output_cls=InvoiceData,
    prompt_template_str="Extract invoice data from: {text}"
)
result = program(text=full_text)
```

**Pros:**
- Structured extraction directly from LlamaIndex
- Type-safe output

**Cons:**
- More complex than current approach
- Still requires LLM call (same as OpenAI)
- No clear advantage over current method

## Why We Don't Use Prompts with LlamaIndex

### Current Architecture is Optimal:

1. **Separation of Concerns**:
   - LlamaIndex: PDF parsing (handles complex layouts)
   - OpenAI LLM: Structured data extraction (with our custom prompt)

2. **Efficiency**:
   - LlamaIndex extracts text once (fast)
   - OpenAI does structured extraction (what we need)
   - No need for two LLM calls

3. **Flexibility**:
   - We control the extraction prompt precisely
   - Can easily modify prompt without changing LlamaIndex setup
   - Works with any PDF reader (pypdf, LlamaIndex, etc.)

## Comparison: Current vs. Prompt-Based Approach

### Current Approach (Recommended):

```
PDF → LlamaIndex (raw text) → OpenAI LLM (structured extraction)
      [No prompt]            [Custom prompt]
```

**Advantages:**
- Simple and clear
- Fast (one LLM call)
- Full control over extraction logic
- Easy to debug

### Alternative Approach (If We Used Prompts):

```
PDF → LlamaIndex (with prompt) → Structured Data
      [Prompt for extraction]
```

**Advantages:**
- All-in-one solution
- Could use LlamaIndex's retrieval capabilities

**Disadvantages:**
- More complex setup
- Harder to customize prompt
- Requires vector store/indexing
- Slower for simple extraction

## Summary

**Answer: No, we currently don't share a prompt to LlamaIndex for text extraction.**

**Why:**
- LlamaIndex is used ONLY for PDF text extraction (parsing)
- The prompt is sent to OpenAI LLM AFTER text extraction
- This separation is optimal for our use case

**Could we use prompts?**
- Yes, but it's not necessary
- Current approach is simpler and more flexible
- LlamaIndex prompt would be for structured extraction, which we already do with OpenAI

**Current Flow:**
1. LlamaIndex: Extract raw text from PDF (no prompt needed)
2. OpenAI LLM: Extract structured data from text (with our custom prompt)

This is the recommended approach for invoice extraction!

