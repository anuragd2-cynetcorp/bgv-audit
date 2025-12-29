# Project Requirements: BGV Audit Automation

## 1. Project Overview
The goal of this project is to build an automated system to audit invoices received from third-party Background Verification (BGV) providers. The system must ingest PDF invoices, extract line-item data using deterministic methods, and flag financial discrepancies with high accuracy.

## 2. Core Philosophy & Constraints
*   **Zero Hallucination:** The system must **not** use Large Language Models (LLMs) or generative AI for data extraction. Accuracy is paramount.
*   **Deterministic Extraction:** Extraction logic must be rule-based and specific to each provider's layout.
*   **Minimal Storage:** The system should not act as a document warehouse. It should store only the minimum data required to perform historical audits and generate reports.

## 3. Input Specifications
*   **Source:** PDF files uploaded by the user.
*   **Variety:** There are exactly **15 known, fixed formats** (one per provider).
*   **Content:** Invoices contain header information (Invoice #, Date), a table of line items (Candidate Name, ID, Service Type, Cost), and a footer (Grand Total).

## 4. Functional Requirements

### A. Provider Identification & Extraction
*   The system must automatically identify which of the 15 providers the PDF belongs to (based on keywords, logos, or headers).
*   The system must apply a specific extraction template/rule set corresponding to that provider.
*   **Data to Extract:**
    *   Invoice Number
    *   Provider Name
    *   Line Items: Candidate Name, Candidate ID (Unique Identifier), Service Description, Cost.
    *   Invoice Grand Total (from the footer).

### B. Audit Logic (Discrepancy Detection)
The system must perform the following checks on every uploaded invoice:

1.  **Total Mismatch Check:**
    *   Sum the cost of all extracted line items.
    *   Compare the calculated sum against the extracted "Grand Total" from the PDF footer.
    *   Flag if the difference exceeds a small rounding tolerance.

2.  **Internal Duplication Check:**
    *   Identify if the same Candidate ID + Service Description appears more than once within the *current* file.
    *   Flag these rows as "Internal Duplicates."

3.  **Historical Duplication Check:**
    *   Compare the current line items against a database of previously processed line items.
    *   Flag if a Candidate ID + Service Description has been billed in a *previous* invoice.
    *   This requires storing a "fingerprint" of past records.

### C. Reporting
*   Generate a user-friendly report for every processed invoice.
*   The report must clearly list:
    *   Pass/Fail status.
    *   Specific rows causing errors.
    *   Type of error (Math Mismatch, Duplicate, Historical Duplicate).

## 5. Data Storage Strategy
To adhere to the "Minimal Storage" requirement:
*   **Do Store:**
    *   User credentials (for access control).
    *   Invoice Metadata (Filename, Upload Date, Provider, Total Amount).
    *   Line Item Fingerprints (Candidate ID + Service Type + Invoice Reference) to enable historical duplicate checking.
    *   The final Audit Report (JSON or text summary of errors).
*   **Do Not Store:**
    *   The physical PDF files (process and discard, or store temporarily).
    *   Full raw text dumps of the PDF content.

## 6. User Workflows
1.  **Upload:** User selects a provider (optional) and uploads a PDF file.
2.  **Process:** System parses the file, runs audit logic, and saves results.
3.  **Review:** User views a summary screen showing the audit results and any flagged discrepancies.

## 7. Non-Functional Requirements
*   **Accuracy:** Extraction rules must handle specific table layouts (grid vs. whitespace) without merging columns or losing rows.
*   **Performance:** Parsing and auditing should happen in near real-time.
*   **Scalability:** The architecture must allow for easily adding a 16th provider template without rewriting the core engine.