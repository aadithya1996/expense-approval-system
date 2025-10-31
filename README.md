# Invoice Approval System

An intelligent expense approval system powered by LLM that automatically extracts invoice data from PDFs, analyzes expense bills against company policies, and routes them for human approval when needed. The system uses AI to detect disallowed items, check compliance, and learn from prior approval decisions.

## 🎯 Features

- **PDF Invoice Extraction**: Automatically extracts invoice data (supplier, date, amount, line items) from PDF files using LLM
- **Intelligent Alcohol Detection**: Uses LLM knowledge to identify alcohol-related items (brands, product types, supplier context)
- **Policy-Based Analysis**: Analyzes invoices against company expense policies with inline policy citations
- **Auto-Approval**: Automatically approves invoices below a certain threshold that meet policy requirements
- **Approval Routing**: Routes invoices to appropriate approvers based on amount thresholds:
- **Prior Case Learning**: References previous human approval decisions for consistency
- **Email Notifications**: Sends approval request emails via SendGrid
- **Web Interface**: Review and approve/decline invoices through a web interface
- **Duplicate Detection**: Prevents duplicate invoice submissions

## 🏗️ Architecture

```
┌─────────────┐
│ PDF Upload  │
└──────┬──────┘
       │
       ▼
┌─────────────────┐
│ Extract Invoice │ (LLM + pypdf)
│ Data from PDF   │
└──────┬──────────┘
       │
       ▼
┌─────────────────┐
│ Store Invoice   │ (SQLite)
│ in Database     │
└──────┬──────────┘
       │
       ▼
┌─────────────────┐
│ Analyze Invoice │ (LLM + Policy)
│ Against Policy  │
└──────┬──────────┘
       │
       ├─── Auto-approve (≤ $250, compliant)
       │
       └─── Route for Approval (> $250 or needs review)
            │
            ▼
       ┌─────────────────┐
       │ Send Email       │ (SendGrid)
       │ to Approver      │
       └──────┬──────────┘
              │
              ▼
       ┌─────────────────┐
       │ Human Review     │ (Web Interface)
       │ & Decision       │
       └──────────────────┘
```

## 📋 Prerequisites

- Python 3.8+
- OpenAI API key
- SendGrid API key (optional, for email notifications)
- SQLite (included with Python)

## 🚀 Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd LlmPars
   ```

2. **Create a virtual environment**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Create `.env` file**
   ```bash
   cp .env.example .env  # If you have an example file
   # Or create .env manually
   ```

5. **Configure environment variables** (see Configuration section below)

## ⚙️ Configuration

Create a `.env` file in the project root with the following variables:

```env
# Required
OPENAI_API_KEY=your_openai_api_key_here

# Email Configuration (Optional - for email notifications)
SENDGRID_API_KEY=your_sendgrid_api_key
FROM_EMAIL=your-email@company.com
APPROVAL_EMAIL=approver@company.com
SENDGRID_TEMPLATE_ID=your_sendgrid_template_id  # Optional: for dynamic templates

# Application Configuration
APP_BASE_URL=http://127.0.0.1:8000
APP_SECRET=your-secret-key-for-tokens

# File Paths (Optional - defaults provided)
POLICY_FILE_PATH=prompts/approval_policy.txt
APPROVAL_PROMPT_PATH=prompts/approval_prompt.txt
```

### Environment Variables Explained

- **OPENAI_API_KEY**: Required. Your OpenAI API key for LLM inference
- **SENDGRID_API_KEY**: Optional. SendGrid API key for email notifications
- **FROM_EMAIL**: Optional. Email address to send approval emails from
- **APPROVAL_EMAIL**: Optional. Email address to receive approval requests
- **SENDGRID_TEMPLATE_ID**: Optional. SendGrid dynamic template ID (if using templates)
- **APP_BASE_URL**: Base URL for the application (used in email links)
- **APP_SECRET**: Secret key for generating secure tokens

## 🎮 Usage

### Start the Server

```bash
uvicorn app:app --reload
```

The API will be available at `http://127.0.0.1:8000`

### API Documentation

Once the server is running, visit:
- **Swagger UI**: `http://127.0.0.1:8000/docs`
- **ReDoc**: `http://127.0.0.1:8000/redoc`

## 📡 API Endpoints

### 1. Extract Invoice from PDF

**POST** `/extract`

Extract invoice data from a PDF file and trigger approval workflow.

**Parameters:**
- `file` (required): PDF file to upload
- `submitter_name` (optional): Name of person submitting invoice
- `submitter_email` (optional): Email of submitter
- `submitter_team` (optional): Team/department of submitter
- `business_reason` (optional): Business justification for the expense
- `force` (optional): Override duplicate file check (default: false)
- `schema` (optional): Custom JSON schema for extraction

**Example using cURL:**
```bash
curl -X POST "http://127.0.0.1:8000/extract" \
  -F "file=@invoice.pdf" \
  -F "submitter_name=John Doe" \
  -F "submitter_email=john.doe@company.com" \
  -F "submitter_team=Finance" \
  -F "business_reason=Quarterly office supplies restock"
```

**Example using Python:**
```python
import requests

with open("invoice.pdf", "rb") as f:
    response = requests.post(
        "http://127.0.0.1:8000/extract",
        files={"file": f},
        data={
            "submitter_name": "John Doe",
            "submitter_email": "john.doe@company.com",
            "submitter_team": "Finance",
            "business_reason": "Quarterly office supplies restock"
        }
    )
print(response.json())
```

**Response:**
```json
{
  "id": 1,
  "data": {
    "invoice_id": "INV-2024-001",
    "supplier_name": "Office Supplies Co.",
    "invoice_date": "2024-12-15",
    "total_amount": 180.0,
    "currency": "USD",
    "line_items": [...]
  },
  "approval": {
    "approval_id": 1,
    "status": "approved"
  }
}
```

### 2. List Invoices

**GET** `/invoices?limit=50&offset=0`

Get a list of invoices.

### 3. Get Invoice Details

**GET** `/invoices/{invoice_id}`

Get details of a specific invoice.

### 4. Review Approval

**GET** `/approvals/{approval_id}/review?token={token}`

Web interface to review and approve/decline an invoice.

### 5. Decide on Approval

**POST** `/approvals/{approval_id}/decide`

Approve or decline an invoice.

**Parameters:**
- `action`: "approve" or "decline"
- `reason`: Reason for the decision
- `token`: Security token

## 🔄 Workflow

### 1. Invoice Submission

When an invoice PDF is uploaded:

1. **PDF Text Extraction**: Extracts text from PDF using `pypdf`
2. **Data Extraction**: LLM extracts structured data:
   - Invoice ID/Number
   - Supplier Name
   - Invoice Date
   - Total Amount
   - Currency
   - Line Items (description, quantity, unit price, total)
3. **Duplicate Check**: Verifies invoice hasn't been submitted before (by file hash and invoice ID)
4. **Database Storage**: Saves invoice to SQLite database

### 2. Approval Analysis

The system analyzes the invoice using LLM:

1. **Line Item Identification**: LLM uses its knowledge to identify what each item is:
   - Recognizes brands (e.g., "Bira" = alcohol brand)
   - Understands product types (e.g., "Single Malt" = whiskey)
   - Considers supplier context (e.g., "tap room" = bar/pub)
2. **Policy Compliance Check**: 
   - Checks for disallowed items (alcohol, weapons, gambling)
   - Verifies amount thresholds
   - Checks required fields (supplier, date, line items)
   - Validates invoice date (within 180 days)
3. **Prior Case Reference**: Reviews similar past decisions for consistency
4. **Decision Generation**: LLM generates decision with reasoning and citations

### 3. Auto-Approval Logic

For invoices ≤ $250:

1. **Amount Check**: If amount ≤ $250, proceed to auto-approval check
2. **Disallowed Items Check**: 
   - Checks LLM citations for alcohol mentions
   - Checks LLM reason for alcohol keywords
   - Checks if LLM decision is "declined"
3. **Required Fields Check**: Verifies supplier, date, line items exist
4. **Date Validation**: Checks invoice date is within 180 days
5. **Auto-Approve**: If all checks pass, invoice is auto-approved
6. **Route for Review**: If any check fails, invoice goes to human approval

### 4. Approval Routing

Based on invoice amount:

- **≤ $250**: Auto-approved if compliant
- **$250.01 - $2,500**: Manager approval (Robert Schrill)
- **$2,500.01 - $10,000**: Finance Manager approval (Sven Stevenon)
- **> $10,000**: Executive approval (Georly Daniel)

### 5. Email Notification

If invoice requires human approval:

1. **Email Generation**: Creates approval email with invoice details
2. **SendGrid Integration**: Sends email via SendGrid (if configured)
3. **Review Link**: Includes secure link to review page with token

### 6. Human Decision

Approver reviews invoice and:

1. **Views Invoice Details**: Sees invoice data, line items, business reason
2. **Reviews AI Recommendation**: Sees policy recommendations with citations
3. **Makes Decision**: Approves or declines with reason
4. **Decision Recorded**: Decision saved to database as prior case for future reference

## 📁 Project Structure

```
LlmPars/
├── app.py                      # FastAPI application & API endpoints
├── helper.py                   # Database helpers, email utilities
├── invoice_workflow.py         # Approval workflow logic
├── query_db.py                 # Database query utility
├── clear_db.py                 # Database clearing utility
├── requirements.txt            # Python dependencies
├── invoices.db                 # SQLite database (created automatically)
├── .env                        # Environment variables (create this)
│
├── prompts/
│   ├── approval_policy.txt    # Company expense policy
│   └── approval_prompt.txt    # LLM prompt template
│
└── templates/
    ├── approval_review.html    # Invoice review web interface
    └── email_template.html    # Email template
```

## 🔑 Key Components

### LLM-Based Invoice Analysis

The system uses OpenAI GPT models to:
- Extract structured data from PDF invoices
- Identify product types and brands using knowledge
- Detect disallowed items (alcohol, weapons, etc.)
- Generate policy-compliant recommendations
- Reference prior approval cases for consistency

### Policy-Based Decision Making

Decisions are based on:
- **Expense Policy** (`prompts/approval_policy.txt`): Defines thresholds, disallowed items, requirements
- **Approval Prompt** (`prompts/approval_prompt.txt`): Instructs LLM on how to analyze invoices
- **Prior Cases**: References past human decisions for consistency

### Auto-Approval Logic

Invoices ≤ $250 are auto-approved if:
- No disallowed items detected
- Supplier name present
- Invoice date present and within 180 days
- Line items present
- LLM doesn't flag any issues

## 🧪 Testing

### Submit a Test Invoice

```bash
curl -X POST "http://127.0.0.1:8000/extract" \
  -F "file=@test_invoice.pdf" \
  -F "submitter_name=Test User" \
  -F "submitter_email=test@example.com" \
  -F "submitter_team=Engineering" \
  -F "business_reason=Test expense"
```

### Query Database

```bash
python3 query_db.py shell
# Then run SQL queries:
SELECT * FROM invoices;
SELECT * FROM approvals;
```

### Clear Database

```bash
python3 clear_db.py
```

## 🛠️ Development

### Database Schema

**invoices** table:
- `id`: Primary key
- `filename`: Original PDF filename
- `supplier_name`: Supplier/vendor name
- `invoice_date`: Invoice date
- `total_amount`: Total amount
- `currency`: Currency code
- `line_items`: JSON array of line items
- `submitter_name`, `submitter_email`, `submitter_team`: Submitter info
- `business_reason`: Business justification
- `file_sha256`: File hash for duplicate detection
- `raw_json`: Full extracted JSON
- `created_at`: Timestamp

**approvals** table:
- `id`: Primary key
- `invoice_id`: Foreign key to invoices
- `status`: "approved", "declined", or "approval_inprogress"
- `reason`: Decision reason
- `decided_by`: "auto", "human:{email}", or "system_error"
- `approver_email`: Email of approver
- `model_decision`: Original LLM decision
- `model_confidence`: LLM confidence score
- `policy_citations`: JSON array of policy citations
- `previous_case_refs`: JSON array of prior case references
- `link_token`: Secure token for review link
- `created_at`, `updated_at`: Timestamps

### Customizing Policy

Edit `prompts/approval_policy.txt` to update:
- Approval thresholds
- Disallowed items
- Required fields
- Team-specific guidelines

### Customizing LLM Behavior

Edit `prompts/approval_prompt.txt` to:
- Modify decision framework
- Update examples
- Change reasoning instructions
- Adjust output format

## 📝 Notes

- **Invoice Format**: Works best with text-based PDFs (not scanned images)
- **Duplicate Detection**: Uses file SHA256 hash and invoice ID + supplier combination
- **Email Templates**: Supports both SendGrid dynamic templates and custom HTML templates
- **Approver Mapping**: Approvers are hardcoded in `helper.py` (can be made configurable)
- **Token Security**: Uses HMAC-based tokens for secure approval links

## 🐛 Troubleshooting

### Common Issues

1. **"OPENAI_API_KEY not found"**
   - Ensure `.env` file exists with `OPENAI_API_KEY` set

2. **"Duplicate file" error**
   - Use `?force=true` parameter to override duplicate check

3. **Emails not sending**
   - Check SendGrid API key and FROM_EMAIL in `.env`
   - Verify APPROVAL_EMAIL is set

4. **Database errors**
   - Delete `invoices.db` and restart server (database will be recreated)
   - Or run `python3 clear_db.py` to clear data

5. **PDF extraction fails**
   - Ensure PDF contains extractable text (not scanned images)
   - Check PDF is not corrupted

## 🙏 Acknowledgments

- OpenAI for LLM capabilities
- FastAPI for the web framework
- SendGrid for email services

