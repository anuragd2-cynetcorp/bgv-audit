"""
Provider extractor for InCheck invoices.
"""
import re
import pdfplumber
from typing import List
from .base import BaseProvider, ExtractedInvoice, ExtractedLineItem


class InCheckProvider(BaseProvider):
    """
    Extractor for InCheck invoices.
    
    Format Characteristics:
    - Header (Page 1) contains Invoice # and Date.
    - Footer (Last Page) contains "Total Amount Due".
    - Data is grouped by Candidate.
    - Candidate Header format: Date | Name | SSN (masked) | Ordered By | File #
    - Line Items follow the header: Description | Amount
    """
    
    def __init__(self):
        """Initialize the InCheck provider."""
        super().__init__("InCheck")
        self.identification_keywords = ["InCheck", "INCHECK", "inchecksolutions.com"]
    
    def identify(self, pdf_path: str) -> bool:
        """Check if this PDF belongs to InCheck."""
        text = self._get_pdf_text(pdf_path)
        return "InCheck" in text and "7500 W STATE STREET" in text
    
    def extract(self, pdf_path: str) -> ExtractedInvoice:
        """
        Extract invoice data from InCheck's PDF format.
        """
        invoice_number = BaseProvider.generate_unknown_invoice_number()
        grand_total = 0.0
        line_items = []
        
        # State variables
        current_date = None
        current_candidate_name = None
        current_file_number = None # Used as Candidate ID
        
        # Buffer for multi-line candidate names
        candidate_name_buffer = []
        capturing_candidate = False
        
        with pdfplumber.open(pdf_path) as pdf:
            # 1. Extract Invoice Number (Page 1)
            first_page_text = pdf.pages[0].extract_text()
            inv_match = re.search(r'Invoice\s*#\s*(\d+)', first_page_text)
            if inv_match:
                invoice_number = inv_match.group(1)
            
            # 2. Extract Grand Total (Last Page)
            last_page_text = pdf.pages[-1].extract_text()
            total_match = re.search(r'Total Amount Due:\s*\$([\d,]+\.\d{2})', last_page_text)
            if total_match:
                grand_total = float(total_match.group(1).replace(',', ''))
            
            # 3. Extract Line Items (Iterate all pages)
            for page in pdf.pages:
                text = page.extract_text()
                if not text:
                    continue
                
                lines = text.split('\n')
                
                for line in lines:
                    line = line.strip()
                    
                    # --- State 1: Detect Start of Candidate Block ---
                    # Pattern: Date at start of line (MM/DD/YYYY)
                    # Example: "09/29/2025 KUMAGA, SEFAKOR"
                    date_match = re.match(r'^(\d{2}/\d{2}/\d{4})\s+(.*)', line)
                    
                    if date_match:
                        current_date = date_match.group(1)
                        rest_of_line = date_match.group(2)
                        
                        # Check if this line also contains the SSN placeholder (Single line header)
                        # Example: "10/05/2025 BANKS, CARA... XXX-XXX-XXXX ... 1687062"
                        if "XXX-XXX-XXXX" in rest_of_line:
                            # Split by SSN to get Name (left) and Metadata (right)
                            parts = rest_of_line.split("XXX-XXX-XXXX")
                            current_candidate_name = parts[0].strip()
                            
                            # Try to extract File # from the right side (last digits on line)
                            # Right side: " Thomphashing, Magi 1680061"
                            file_num_match = re.search(r'(\d+)$', parts[1].strip())
                            if file_num_match:
                                current_file_number = file_num_match.group(1)
                            else:
                                current_file_number = "UNKNOWN"
                                
                            capturing_candidate = False
                        else:
                            # Multi-line header: Date and Name start here, SSN is on next line
                            candidate_name_buffer = [rest_of_line]
                            capturing_candidate = True
                        continue
                        
                    # --- State 2: Capture Multi-line Candidate Name ---
                    if capturing_candidate:
                        if "XXX-XXX-XXXX" in line:
                            # Found the SSN line, closing the name capture
                            # Line format: "CHILUFYA XXX-XXX-XXXX Thomphashing, Magi 1680061"
                            parts = line.split("XXX-XXX-XXXX")
                            name_continuation = parts[0].strip()
                            candidate_name_buffer.append(name_continuation)
                            
                            current_candidate_name = " ".join(candidate_name_buffer).strip()
                            
                            # Extract File #
                            file_num_match = re.search(r'(\d+)$', parts[1].strip())
                            if file_num_match:
                                current_file_number = file_num_match.group(1)
                            else:
                                current_file_number = "UNKNOWN"
                                
                            capturing_candidate = False
                            candidate_name_buffer = []
                        else:
                            # Just another line of the name? Or did we fail?
                            # Safety check: if line has a price, we missed the SSN line
                            if "$" in line:
                                capturing_candidate = False
                                candidate_name_buffer = []
                            else:
                                candidate_name_buffer.append(line)
                        continue

                    # --- State 3: Extract Line Items ---
                    if current_candidate_name:
                        # Skip Subtotal lines
                        if line.startswith("Subtotal for"):
                            continue
                        
                        # Regex for Line Item: Description ... $Amount
                        # Example: "Drug Test Scheduling Fee $30.00"
                        item_match = re.search(r'^(.+?)\s+\$([\d,]+\.\d{2})$', line)
                        
                        if item_match:
                            description = item_match.group(1).strip()
                            amount = float(item_match.group(2).replace(',', ''))
                            
                            # Filter out headers that look like items
                            if "REPORT CHARGES" in description or "Total Amount Due" in description:
                                continue
                                
                            item = ExtractedLineItem(
                                service_date=current_date,
                                candidate_id=current_file_number or current_candidate_name,
                                candidate_name=current_candidate_name,
                                amount=amount,
                                service_description=description,
                                metadata={
                                    "file_number": current_file_number
                                }
                            )
                            line_items.append(item)

        if not line_items:
            raise ValueError("Could not extract line items from invoice")
            
        if grand_total == 0.0:
             # Fallback: Sum line items if footer extraction failed
             grand_total = sum(item.amount for item in line_items)

        return ExtractedInvoice(
            invoice_number=invoice_number,
            provider_name=self.name,
            line_items=line_items,
            grand_total=grand_total
        )
    
    def _extract_from_tables(self, tables: List[List[List[str]]]) -> List[ExtractedLineItem]:
        """Extract line items from PDF tables."""
        # TODO: Implement based on InCheck's format
        return []
    
    def _extract_from_text(self, text: str) -> List[ExtractedLineItem]:
        """Extract line items from text."""
        return []

