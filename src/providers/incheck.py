"""
Provider extractor for InCheck invoices.
"""
import re
import pdfplumber
from typing import List
from .base import BaseProvider, ExtractedInvoice, ExtractedLineItem
from src.logger import get_logger

logger = get_logger()


class InCheckProvider(BaseProvider):
    """
    Extractor for InCheck invoices.
    
    Format Characteristics:
    - Header (Page 1) contains Invoice # and Date.
    - Footer (Last Page) contains "Total Amount Due".
    - Data is grouped by Candidate.
    - Candidate Header format: Date | Name | SSN (masked) | Ordered By | File #
    - The Candidate Name can span multiple lines.
    - The SSN placeholder "XXX-XXX-XXXX" marks the end of the name block.
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
        Extract invoice data from InCheck's PDF format using a robust State Machine.
        """
        invoice_number = BaseProvider.generate_unknown_invoice_number()
        grand_total = 0.0
        line_items = []
        
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
            
            # 3. Extract Line Items
            # Try normal text extraction first
            lines = self._get_text_lines(pdf_path, use_ocr=False)
            line_items = self._parse_text_lines(lines)
            
            # If no line items found, try OCR fallback
            if not line_items:
                logger.info("No line items found with text extraction. Attempting OCR fallback for InCheck invoice.")
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
             grand_total = sum(item.amount for item in line_items)

        return ExtractedInvoice(
            invoice_number=invoice_number,
            provider_name=self.name,
            line_items=line_items,
            grand_total=grand_total
        )
    
    def _parse_text_lines(self, lines: List[str]) -> List[ExtractedLineItem]:
        """
        Parse text lines into line items using InCheck-specific logic.
        Uses complex state machine to handle multi-line headers and floating names.
        
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
        
        # Buffers
        candidate_name_buffer = []
        capturing_candidate = False
        potential_floating_name = None  # Stores a line that looks like a name but appeared before the Date
        
        for line in lines:
            line = line.strip()
            if not line: 
                continue
            
            # --- State 1: Detect Start of Candidate Block ---
            # Pattern: Date at start of line (MM/DD/YYYY)
            date_match = re.match(r'^\s*(\d{1,2}/\d{1,2}/\d{4})(?:\s+(.*))?$', line)
            
            if date_match:
                # If we were already capturing, force close the previous one (Safety Valve)
                if capturing_candidate and candidate_name_buffer:
                    # Optimized: Use file number or simplified name (name not used for fingerprinting)
                    current_file_number = "UNKNOWN"
                    current_candidate_name = current_file_number
                
                # Reset for new candidate
                capturing_candidate = False
                candidate_name_buffer = []
                
                current_date = date_match.group(1)
                rest_of_line = date_match.group(2) or ""
                
                # Check for "Floating Name" (Name appeared on the line BEFORE the date)
                if potential_floating_name:
                    candidate_name_buffer.append(potential_floating_name)
                    potential_floating_name = None
                
                # Add text found on the same line as the date
                if rest_of_line.strip():
                    # Check if this line contains the SSN placeholder (Single line header)
                    if "XXX-XXX-XXXX" in rest_of_line:
                        parts = rest_of_line.split("XXX-XXX-XXXX")
                        name_part = parts[0].strip()
                        if name_part:
                            candidate_name_buffer.append(name_part)
                        
                        # Extract File # from right side
                        if len(parts) > 1:
                            file_match = re.search(r'(\d+)(?:\s*-\s*)?$', parts[1].strip())
                            current_file_number = file_match.group(1) if file_match else "UNKNOWN"
                        else:
                            current_file_number = "UNKNOWN"
                        
                        # Optimized: Use file number as name (name not used for fingerprinting)
                        current_candidate_name = current_file_number
                            
                        # We found everything in one go
                        capturing_candidate = False
                        candidate_name_buffer = []
                    else:
                        # Multi-line header: Name starts here, SSN is on next line
                        candidate_name_buffer.append(rest_of_line.strip())
                        capturing_candidate = True
                        current_candidate_name = None
                else:
                    # Date line was empty of text, but we might have a floating name in buffer
                    capturing_candidate = True
                    current_candidate_name = None
                
                continue
                
            # --- State 2: Capture Multi-line Candidate Name ---
            if capturing_candidate:
                if "XXX-XXX-XXXX" in line:
                    # Found the SSN line, closing the name capture
                    parts = line.split("XXX-XXX-XXXX")
                    name_continuation = parts[0].strip()
                    if name_continuation:
                        candidate_name_buffer.append(name_continuation)
                    
                    # Extract File #
                    if len(parts) > 1:
                        file_match = re.search(r'(\d+)(?:\s*-\s*)?$', parts[1].strip())
                        current_file_number = file_match.group(1) if file_match else "UNKNOWN"
                    else:
                        current_file_number = "UNKNOWN"
                    
                    # Optimized: Use file number as name (name not used for fingerprinting)
                    current_candidate_name = current_file_number
                    
                    capturing_candidate = False
                    candidate_name_buffer = []
                    continue 
                
                elif "$" in line:
                    # Safety Valve: We hit a price line but never found the SSN.
                    current_file_number = "UNKNOWN"
                    # Optimized: Use file number as name (name not used for fingerprinting)
                    current_candidate_name = current_file_number
                    capturing_candidate = False
                    candidate_name_buffer = []
                    # Fall through to State 3 to process this line as an item
                
                else:
                    # Just another line of the name
                    candidate_name_buffer.append(line)
                    continue

            # --- State 3: Extract Line Items ---
            if current_candidate_name:
                # Skip Subtotal lines
                if "Subtotal for" in line:
                    continue
                
                # Regex for Line Item: Description ... $Amount
                item_match = re.search(r'^(.+?)\s+\$?([\d,]+\.\d{2})$', line)
                
                if item_match:
                    description = item_match.group(1).strip()
                    amount = float(item_match.group(2).replace(',', ''))
                    
                    # Filter out headers/footers
                    if "REPORT CHARGES" in description or "Total Amount Due" in description:
                        continue
                    
                    # Normalize description (first meaningful words for fingerprinting)
                    desc_words = description.split()[:5]  # First 5 words sufficient
                    description = ' '.join(desc_words).strip()
                    
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
                    # Reset potential floating name since we are processing items now
                    potential_floating_name = None
                    continue

            # --- State 4: Detect Floating Name (Orphaned Line) ---
            # If we are NOT capturing, and NOT in an item line, and the line looks like a name
            # (All Caps, contains comma, no $), save it. It might belong to the NEXT date line.
            if not capturing_candidate and "$" not in line and "," in line:
                # Heuristic: Names are usually UPPERCASE in InCheck
                if line.isupper():
                    potential_floating_name = line
                else:
                    potential_floating_name = None
            else:
                potential_floating_name = None
        
        return line_items