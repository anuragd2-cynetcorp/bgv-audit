"""
Provider extractor for Quest invoices.
"""
import re
import pdfplumber
from typing import List, Optional
from .base import BaseProvider, ExtractedInvoice, ExtractedLineItem


class QuestProvider(BaseProvider):
    """
    Extractor for Quest Diagnostics invoices.
    
    Format Characteristics:
    - Header contains 'Invoice Number' and 'Amount Due'.
    - Data is grouped by Candidate (Patient).
    - A Candidate line starts with a Date (MM/DD/YYYY).
    - Service lines follow the Candidate line.
    - Service lines always contain a 7-digit CPT/Service code and a '$' amount.
    """
    
    def __init__(self):
        super().__init__("Quest Diagnostics")
        
    def identify(self, pdf_path: str) -> bool:
        """Check for Quest logo text or specific address patterns."""
        text = self._get_pdf_text(pdf_path)
        return "QUEST DIAGNOSTICS" in text.upper() or "QUESTDIAGNOSTICS.COM" in text.upper()

    def extract(self, pdf_path: str) -> ExtractedInvoice:
        invoice_number = "UNKNOWN"
        grand_total = 0.0
        line_items = []
        
        # State machine variables
        current_candidate_id = None
        current_candidate_name = None
        
        with pdfplumber.open(pdf_path) as pdf:
            # 1. Extract Header Info (usually Page 1)
            first_page_text = pdf.pages[0].extract_text()
            
            # Extract Invoice Number
            # Pattern: "12069956 NDA 9218249080 11/24/2025" (Client | Code | Invoice | Date)
            # We look for the 10-digit number starting with 9 (common for Quest) or just the position
            inv_match = re.search(r'\d+\s+NDA\s+(\d+)\s+\d{2}/\d{2}/\d{4}', first_page_text)
            if inv_match:
                invoice_number = inv_match.group(1)
            
            # Extract Grand Total
            # Pattern: "Amount Due: ... $2,412.30"
            total_match = re.search(r'Amount Due:[\s\S]*?\$([\d,]+\.\d{2})', first_page_text)
            if total_match:
                grand_total = float(total_match.group(1).replace(',', ''))

            # 2. Extract Line Items (Iterate all pages)
            for page in pdf.pages:
                text = page.extract_text()
                if not text:
                    continue
                    
                lines = text.split('\n')
                
                for line in lines:
                    line = line.strip()
                    
                    # --- Pattern A: New Candidate Line ---
                    # Regex: Date | Specimen | Patient ID | Name
                    # Example: "10/31/2025 0789055 244677729 BAUTISTA,B"
                    candidate_match = re.match(r'^(\d{2}/\d{2}/\d{4})\s+(\d+)\s+([A-Z0-9]+)\s+(.*)', line)
                    
                    if candidate_match:
                        # Update State
                        # Group 2 is Specimen Number (Unique per visit)
                        # Group 3 is Patient ID (Employee ID/SSN - Unique per person)
                        # Group 4 is Name
                        
                        # We use Patient ID (Group 3) as the primary ID for historical duplicate checking
                        # If Group 3 looks like a name (alpha only), swap logic (handling OCR quirks)
                        raw_id = candidate_match.group(3)
                        raw_name = candidate_match.group(4)
                        
                        current_candidate_id = raw_id
                        current_candidate_name = raw_name
                        
                        # Note: Sometimes the first service is on the SAME line as the candidate.
                        # We check if the end of this line looks like a service cost.
                        # However, in the provided screenshots, services are usually on the next line 
                        # or the line ends with the name. We will rely on the Service Line check below 
                        # to catch it if it wraps or is on the same line.
                        
                    # --- Pattern B: Service Line ---
                    # Regex: Description | 7-digit Code | Amount
                    # Example: "SAP 10-50 + OXY/MEP/N 0019507 $141.75"
                    # Example: "(U) COL PREF 0035499 $22.00"
                    # We exclude "PATIENT TOTAL" explicitly
                    
                    if "PATIENT TOTAL" in line:
                        continue

                    # Look for 7 digit code followed by price at end of line
                    service_match = re.search(r'(?P<desc>.+?)\s+(?P<code>\d{7})\s+\$(?P<amount>[\d,]+\.\d{2})$', line)
                    
                    if service_match and current_candidate_id:
                        description = service_match.group('desc').strip()
                        amount = float(service_match.group('amount').replace(',', ''))
                        
                        # Clean up description (sometimes it catches the candidate name if on same line)
                        # If description starts with the candidate name, strip it.
                        if current_candidate_name and description.startswith(current_candidate_name):
                            description = description.replace(current_candidate_name, "").strip()

                        item = ExtractedLineItem(
                            candidate_name=current_candidate_name,
                            candidate_id=current_candidate_id,
                            service_description=description,
                            cost=amount
                        )
                        line_items.append(item)

        if not line_items:
            raise ValueError("Could not extract line items from invoice")
        
        return ExtractedInvoice(
            invoice_number=invoice_number,
            provider_name=self.name,
            line_items=line_items,
            grand_total=grand_total
        )
    
    def _extract_from_tables(self, tables: List[List[List[str]]]) -> List[ExtractedLineItem]:
        """Extract line items from PDF tables."""
        # TODO: Implement based on Quest's format
        return []
    
    def _extract_from_text(self, text: str) -> List[ExtractedLineItem]:
        """Extract line items from text."""
        return []

