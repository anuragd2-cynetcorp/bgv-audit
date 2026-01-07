"""
Provider extractor for Scout Logic invoices.
"""
import re
import pdfplumber
from typing import List
from .base import BaseProvider, ExtractedInvoice, ExtractedLineItem
from src.logger import get_logger

logger = get_logger()


class ScoutLogicProvider(BaseProvider):
    """
    Extractor for Scout Logic invoices.
    
    Format Characteristics:
    - Header (Page 1) contains Invoice # and Date.
    - Footer (Last Page) contains "Total Amount Due".
    - Data is grouped by Candidate.
    - Candidate Header format: Date | Name | SSN (masked) | Ordered By | File #
    - **Crucial**: Candidate Name often spans two lines. The Date is on line 1, the SSN is on line 2.
    - Line Items follow the header: Description | Amount
    """
    
    def __init__(self):
        """Initialize the Scout Logic provider."""
        super().__init__("Scout Logic")
        self.identification_keywords = ["ScoutLogic", "SCOUTLOGIC", "scoutlogicscreening.com"]
    
    def identify(self, pdf_path: str) -> bool:
        """Check if this PDF belongs to Scout Logic."""
        text = self._get_pdf_text(pdf_path)
        return any(kw in text for kw in self.identification_keywords)
    
    def extract(self, pdf_path: str) -> ExtractedInvoice:
        """
        Extract invoice data from Scout Logic's PDF format.
        """
        invoice_number = "UNKNOWN"
        grand_total = 0.0
        line_items = []
        
        with pdfplumber.open(pdf_path) as pdf:
            # 1. Extract Invoice Number (Page 1)
            first_page_text = pdf.pages[0].extract_text()
            inv_match = re.search(r'Invoice\s+#(\d+)', first_page_text)
            if inv_match:
                invoice_number = inv_match.group(1)
            
            # 2. Extract Grand Total (Last Page)
            last_page_text = pdf.pages[-1].extract_text()
            # Pattern: "Total Amount Due:" followed by dollar amount
            total_match = re.search(r'Total Amount Due:\s*\$([\d,]+\.\d{2})', last_page_text)
            if total_match:
                grand_total = float(total_match.group(1).replace(',', ''))
            
            # 3. Extract Line Items
            # Try normal text extraction first
            lines = self._get_text_lines(pdf_path, use_ocr=False)
            line_items = self._parse_text_lines(lines)
            
            # If no line items found, try OCR fallback
            if not line_items:
                logger.info("No line items found with text extraction. Attempting OCR fallback for Scout Logic invoice.")
                try:
                    lines = self._get_text_lines(pdf_path, use_ocr=True)
                    line_items = self._parse_text_lines(lines)
                    logger.info(f"OCR extraction found {len(line_items)} line items.")
                except Exception as e:
                    logger.error(f"OCR extraction failed: {str(e)}", exc_info=True)
                    # Continue to raise the original error if OCR also fails
        
        if not line_items:
            raise ValueError("Could not extract line items from invoice. Format may have changed.")
            
        if grand_total == 0.0:
             # Fallback: Sum line items if footer extraction failed
             grand_total = sum(item.amount for item in line_items)

        return ExtractedInvoice(
            invoice_number=invoice_number,
            provider_name=self.name,
            line_items=line_items,
            grand_total=grand_total
        )
    
    def _parse_text_lines(self, lines: List[str]) -> List[ExtractedLineItem]:
        """
        Parse text lines into line items using Scout Logic-specific logic.
        Uses state machine to handle multi-line headers.
        
        Args:
            lines: List of text lines to parse
            
        Returns:
            List of ExtractedLineItem objects
        """
        line_items = []
        
        # State variables
        current_date = None
        current_candidate_name = None
        current_file_number = None
        
        # Multi-line header handling
        pending_date = None
        pending_name_part = None
        
        for line in lines:
            line = line.strip()
            if not line:
                continue

            # --- State 1: Check for Date at start of line ---
            # Pattern: Date (MM/DD/YYYY) at start of line
            date_match = re.match(r'^(\d{2}/\d{2}/\d{4})\s+(.*)', line)
            
            if date_match:
                temp_date = date_match.group(1)
                rest_of_line = date_match.group(2)
                
                # Check if SSN is on this line (Single Line Header)
                # Pattern: masked SSN (XXX-XX-####)
                if "XXX-XX-" in rest_of_line:
                    current_date = temp_date
                    
                    # Extract File # from the part after SSN
                    parts = re.split(r'XXX-XX-\d{4}', rest_of_line)
                    if len(parts) > 1:
                        file_match = re.search(r'(\d+)\s*-?$', parts[1].strip())
                        current_file_number = file_match.group(1) if file_match else "UNKNOWN"
                    else:
                        current_file_number = "UNKNOWN"
                    
                    # Optimized: Use file number as name (name not used for fingerprinting)
                    current_candidate_name = current_file_number
                    
                    # Reset pending state
                    pending_date = None
                    pending_name_part = None
                    
                else:
                    # SSN not found -> Multi-line Header
                    # Store what we have and wait for next line
                    pending_date = temp_date
                    pending_name_part = rest_of_line.strip()
                
                continue

            # --- State 2: Check for SSN on current line (Multi-line continuation) ---
            if pending_date and "XXX-XX-" in line:
                # This line contains the rest of the name and the SSN
                parts = re.split(r'XXX-XX-\d{4}', line)
                name_part_2 = parts[0].strip()
                
                # Extract File #
                current_date = pending_date
                if len(parts) > 1:
                    file_match = re.search(r'(\d+)\s*-?$', parts[1].strip())
                    current_file_number = file_match.group(1) if file_match else "UNKNOWN"
                else:
                    current_file_number = "UNKNOWN"
                
                # Optimized: Use file number as name (name not used for fingerprinting)
                current_candidate_name = current_file_number
                
                # Clear pending
                pending_date = None
                pending_name_part = None
                continue

            # --- State 3: Extract Line Items ---
            # We only extract if we have a valid candidate context
            if current_candidate_name:
                # Skip headers and subtotals
                if any(x in line for x in ["DATE NAME SSN", "Subtotal for", "REPORT CHARGES"]):
                    continue
                
                # Regex for Line Item: Description ... Amount
                # Handles negative amounts
                item_match = re.search(r'^(.+?)\s+(-?\$?[\d,]+\.\d{2})$', line)
                
                if item_match:
                    description = item_match.group(1).strip()
                    amount_str = item_match.group(2).replace('$', '').replace(',', '')
                    
                    try:
                        amount = float(amount_str)
                    except ValueError:
                        continue

                    # Normalize description (first meaningful words for fingerprinting)
                    desc_words = description.split()[:5]  # First 5 words sufficient
                    description = ' '.join(desc_words).strip()

                    # Create Line Item
                    item = ExtractedLineItem(
                        service_date=current_date,
                        candidate_id=current_file_number or "UNKNOWN",
                        candidate_name=current_candidate_name,
                        amount=amount,
                        service_description=description,
                        metadata={
                            "file_number": current_file_number
                        }
                    )
                    line_items.append(item)
        
        return line_items