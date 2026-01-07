"""
Provider extractor for CityMD invoices.
"""
import re
import pdfplumber
from typing import List
from .base import BaseProvider, ExtractedInvoice, ExtractedLineItem


class CityMDProvider(BaseProvider):
    """
    Extractor for CityMD invoices.
    
    Format Characteristics:
    - Header (Page 1) contains Invoice ID and Payment Due/Amount Due.
    - Data is grouped by Patient.
    - Patient Header: "Patient: [Name] Patient ID: [ID] ..."
    - Service Lines: Date | Procedure Code | Description | Amount
    - Service lines always start with a date (MM/DD/YYYY).
    """
    
    def __init__(self):
        """Initialize the CityMD provider."""
        super().__init__("CityMD")
        self.identification_keywords = ["CityMD", "CITYMD", "citymd.com", "City MD", "CITY MD"]
    
    def identify(self, pdf_path: str) -> bool:
        """Check if this PDF belongs to CityMD."""
        text = self._get_pdf_text(pdf_path)
        return any(kw in text for kw in self.identification_keywords)
    
    def extract(self, pdf_path: str) -> ExtractedInvoice:
        """
        Extract invoice data from CityMD's PDF format.
        """
        invoice_number = "UNKNOWN"
        grand_total = 0.0
        line_items = []
        
        # State variables
        current_candidate_name = None
        current_candidate_id = None
        
        with pdfplumber.open(pdf_path) as pdf:
            # 1. Extract Header Info (Page 1)
            first_page_text = pdf.pages[0].extract_text()
            
            # Invoice Number
            # Pattern: "ID #" or "Invoice ID:" followed by alphanumeric ID
            inv_match = re.search(r'(?:ID #|Invoice ID)\s*[:]?\s*([A-Z0-9]+)', first_page_text)
            if inv_match:
                invoice_number = inv_match.group(1)
            
            # Grand Total
            # Pattern: "Payment Due" or "Amount Due" followed by dollar amount
            total_match = re.search(r'(?:Payment|Amount) Due\s*\$([\d,]+\.\d{2})', first_page_text)
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
                    
                    # --- State Change: Patient Header ---
                    # Pattern: "Patient:" followed by name, then "Patient ID:" followed by ID
                    # Regex: Patient: (Name) Patient ID: (ID)
                    pat_match = re.search(r'Patient:\s*(.+?)\s+Patient ID:\s*(\d+)', line)
                    if pat_match:
                        current_candidate_name = pat_match.group(1).strip()
                        current_candidate_id = pat_match.group(2).strip()
                        continue
                    
                    # --- Extract Service Line ---
                    # Only process if we have a valid patient context
                    if current_candidate_name:
                        # Pattern: Date | Code | Description | Amount
                        # Regex: Start -> Date -> Space -> Code -> Space -> Description -> Space -> $Amount -> End
                        
                        # Check if line starts with a date to filter out headers/subtotals
                        if not re.match(r'^\d{2}/\d{2}/\d{4}', line):
                            continue
                            
                        # Updated regex to allow commas in procedure code
                        item_match = re.match(r'^(\d{2}/\d{2}/\d{4})\s+([A-Z0-9,]+)\s+(.+?)\s+\$([\d,]+\.\d{2})$', line)
                        
                        if item_match:
                            date_str = item_match.group(1)
                            proc_code = item_match.group(2)
                            description = item_match.group(3).strip()
                            amount = float(item_match.group(4).replace(',', ''))
                            item = ExtractedLineItem(
                                service_date=date_str,
                                candidate_id=current_candidate_id,
                                candidate_name=current_candidate_name,
                                amount=amount,
                                service_description=description,
                                metadata={
                                    "procedure_code": proc_code
                                }
                            )
                            line_items.append(item)

        if not line_items:
            raise ValueError("Could not extract line items from invoice. Format may have changed.")
            
        if grand_total == 0.0:
             # Fallback: Sum line items if header extraction failed
             grand_total = sum(item.amount for item in line_items)

        return ExtractedInvoice(
            invoice_number=invoice_number,
            provider_name=self.name,
            line_items=line_items,
            grand_total=grand_total
        )

