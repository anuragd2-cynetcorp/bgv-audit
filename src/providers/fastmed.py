"""
Provider extractor for FastMed invoices.
"""
import re
import pdfplumber
from typing import List
from .base import BaseProvider, ExtractedInvoice, ExtractedLineItem


class FastMedProvider(BaseProvider):
    """
    Extractor for FastMed invoices.
    
    Format Characteristics:
    - Summary Page (usually Page 3) contains "Account Number" and "Amount Due".
    - Detail Pages (Page 4+) contain a table with headers:
      [DOS, Invoice (HAR), Patient Name, SSN, Clinic, Description of Service, Total]
    """
    
    def __init__(self):
        """Initialize the FastMed provider."""
        super().__init__("FastMed")
        self.identification_keywords = ["FastMed", "FASTMED", "fastmed.com"]
    
    def identify(self, pdf_path: str) -> bool:
        """Check if this PDF belongs to FastMed."""
        text = self._get_pdf_text(pdf_path)
        return any(kw in text for kw in self.identification_keywords)
    
    def extract(self, pdf_path: str) -> ExtractedInvoice:
        """
        Extract invoice data from FastMed's PDF format.
        """
        invoice_number = "UNKNOWN"
        grand_total = 0.0
        line_items = []
        
        with pdfplumber.open(pdf_path) as pdf:
            # --- Step 1: Check if Scanned ---
            total_chars = sum(len(p.extract_text() or "") for p in pdf.pages[:3])
            if total_chars < 50:
                raise ValueError("PDF appears to be a scanned image (no text found). OCR is required.")

            # --- Step 2: Extract Header Info ---
            for i in range(min(3, len(pdf.pages))):
                page_text = pdf.pages[i].extract_text()
                if not page_text: continue
                
                if invoice_number == "UNKNOWN":
                    acct_match = re.search(r'Account\s*Number\s*[:.]?\s*(\d+)', page_text)
                    if acct_match:
                        invoice_number = acct_match.group(1)
                
                if grand_total == 0.0:
                    total_match = re.search(r'(?:Amount\s*Due|AMOUNT\s*YOU\s*OWE)\s*[:]?\s*\$?([\d,]+\.\d{2})', page_text, re.IGNORECASE)
                    if total_match:
                        grand_total = float(total_match.group(1).replace(',', ''))

            # --- Step 3: Extract Line Items (Table Strategy) ---
            for page in pdf.pages:
                # vertical_strategy='text' is best for tables with whitespace gaps instead of lines
                tables = page.extract_tables(table_settings={
                    "vertical_strategy": "text",
                    "horizontal_strategy": "text",
                    "snap_tolerance": 3,
                    "min_words_vertical": 1
                })
                
                for table in tables:
                    if not table or len(table) < 2: continue
                    
                    # Validate Headers
                    header_row = [str(c).strip().lower() for c in table[0] if c]
                    if not ("dos" in header_row and "patient name" in header_row):
                        continue
                        
                    for row in table[1:]:
                        # Filter empty rows
                        if not row or not row[0]: continue
                        
                        # Validate Date (Column 0)
                        date_str = str(row[0]).strip()
                        if not re.match(r'\d{1,2}/\d{1,2}/\d{4}', date_str):
                            continue
                            
                        try:
                            # --- Relative Indexing Strategy ---
                            # We assume the table structure:
                            # [Date, Ref, Name, ... (SSN/Clinic) ..., Desc, Amount]
                            
                            # 1. Anchors (Left)
                            ref_number = str(row[1]).strip() if len(row) > 1 else ""
                            patient_name = str(row[2]).strip() if len(row) > 2 else "Unknown"
                            
                            # 2. Anchors (Right)
                            amount_str = str(row[-1]).strip()
                            description = str(row[-2]).strip() if len(row) >= 5 else ""
                            
                            # 3. Middle (Metadata)
                            # Everything between Name (idx 2) and Description (idx -2)
                            # This handles cases where SSN is empty or Clinic is merged
                            metadata_cols = row[3:-2]
                            
                            ssn = ""
                            clinic = ""
                            
                            for cell in metadata_cols:
                                if not cell: continue
                                cell_str = str(cell).strip()
                                if "xxx-xx-" in cell_str.lower():
                                    ssn = cell_str
                                else:
                                    clinic = cell_str # Assume non-SSN text is Clinic

                            # Clean Amount
                            amount = float(amount_str.replace('$', '').replace(',', ''))
                            
                            # Determine ID
                            candidate_id = ssn if ssn else patient_name
                            
                            line_items.append(ExtractedLineItem(
                                service_date=date_str,
                                candidate_id=candidate_id,
                                candidate_name=patient_name,
                                amount=amount,
                                service_description=description,
                                metadata={
                                    "clinic": clinic,
                                    "reference_number": ref_number
                                }
                            ))
                        except (ValueError, IndexError):
                            continue

            # --- Step 4: Regex Fallback (if tables failed) ---
            if not line_items:
                for page in pdf.pages:
                    text = page.extract_text(layout=True)
                    if not text: continue
                    
                    lines = text.split('\n')
                    for line in lines:
                        line = line.strip()
                        
                        # Regex for FastMed Row: Date ... Amount
                        if not re.match(r'^\d{1,2}/\d{1,2}/\d{4}', line):
                            continue
                            
                        amount_match = re.search(r'\$?([\d,]+\.\d{2})$', line)
                        if not amount_match:
                            continue
                            
                        try:
                            amount = float(amount_match.group(1).replace(',', ''))
                            
                            # Split the rest
                            clean_line = line[:amount_match.start()].strip()
                            parts = clean_line.split()
                            
                            date_str = parts[0]
                            # Heuristic: Name is usually parts[2] and parts[3]
                            # This is a last resort fallback
                            name = f"{parts[2]} {parts[3]}" if len(parts) > 3 else "Unknown"
                            desc = " ".join(parts[4:])
                            
                            line_items.append(ExtractedLineItem(
                                service_date=date_str,
                                candidate_id=name,
                                candidate_name=name,
                                amount=amount,
                                service_description=desc
                            ))
                        except Exception:
                            continue

        if not line_items:
            raise ValueError("Could not extract line items from invoice. Format may have changed.")
            
        if grand_total == 0.0:
             grand_total = sum(item.amount for item in line_items)

        return ExtractedInvoice(
            invoice_number=invoice_number,
            provider_name=self.name,
            line_items=line_items,
            grand_total=grand_total
        )