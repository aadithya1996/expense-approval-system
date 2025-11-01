Subject: Invoice Approval System - AI-Powered Expense Management Solution

Hi Jonathan,

I wanted to share an intelligent invoice approval system we've built that automates expense management using LLM technology.

**What We Built:**
The system automatically extracts invoice data from PDFs using OpenAI's GPT models, analyzes expenses against company policies, and intelligently routes them for approval. Key features include:
- Automated PDF-to-structured-data extraction (supplier, date, amount, line items)
- AI-powered detection of disallowed items (e.g., alcohol using brand recognition)
- Policy-based analysis with inline citations
- Auto-approval for compliant invoices below threshold
- Prior case learning for consistency

**Database Structure:**
Two main tables:
- **invoices**: Stores invoice data (supplier, date, amount, line items, submitter info, business reason, file hash)
- **approvals**: Tracks approval decisions (status, reason, approver email, AI recommendations, policy citations, prior case references)

**Workflow:**
1. PDF upload → LLM extracts structured data → Stores in database
2. AI analyzes invoice against policy → Identifies disallowed items → Checks compliance
3. Auto-approves compliant invoices ≤ $250 OR routes to appropriate approver (Manager/Finance Manager/Executive) based on amount thresholds
4. Sends email notifications via SendGrid with secure review links
5. Human approvers review via web interface → Decision recorded → Used as prior case for future recommendations

**Repository:** https://github.com/aadithya1996/expense-approval-system

The system is production-ready and includes comprehensive documentation, REST API endpoints, and a web interface. Happy to walk you through it or answer any questions.

Best regards,
Aadithya


