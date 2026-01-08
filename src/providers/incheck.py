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
            
            # Check if extraction is complete by comparing sum with grand total
            # If no line items found, or if sum doesn't match grand total (and we have a grand total), try OCR fallback
            items_sum = sum(item.amount for item in line_items) if line_items else 0.0
            should_try_ocr = False
            
            if not line_items:
                should_try_ocr = True
                logger.info("No line items found with text extraction. Attempting OCR fallback for InCheck invoice.")
            elif grand_total > 0.0 and abs(grand_total - items_sum) > 0.01:
                should_try_ocr = True
                logger.info(f"Text extraction found {len(line_items)} items with sum ${items_sum:.2f}, but grand total is ${grand_total:.2f}. Attempting OCR fallback for InCheck invoice.")
            
            if should_try_ocr:
                try:
                    lines = self._get_text_lines(pdf_path, use_ocr=True)
                    ocr_line_items = self._parse_text_lines(lines)
                    ocr_sum = sum(item.amount for item in ocr_line_items) if ocr_line_items else 0.0
                    
                    # Use OCR results if they're better (more items or closer to grand total)
                    if not line_items or (grand_total > 0.0 and abs(grand_total - ocr_sum) < abs(grand_total - items_sum)):
                        line_items = ocr_line_items
                        logger.info(f"OCR extraction found {len(line_items)} line items with sum ${ocr_sum:.2f}.")
                    elif line_items:
                        logger.info(f"OCR extraction found {len(ocr_line_items)} items but text extraction had better match. Using text extraction results.")
                except Exception as e:
                    logger.error(f"OCR extraction failed: {str(e)}", exc_info=True)
                    # Continue with text extraction results if OCR fails
        
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
            # Pattern: Date at start of line (MM/DD/YYYY) - more flexible
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
                
                date_str = date_match.group(1)
                # Normalize date format (ensure consistent format)
                date_parts = date_str.split('/')
                if len(date_parts) == 3:
                    month, day, year = date_parts
                    current_date = f"{month.zfill(2)}/{day.zfill(2)}/{year}"
                else:
                    current_date = date_str
                
                rest_of_line = date_match.group(2) or ""
                
                # Check for "Floating Name" (Name appeared on the line BEFORE the date)
                if potential_floating_name:
                    candidate_name_buffer.append(potential_floating_name)
                    potential_floating_name = None
                
                # Add text found on the same line as the date
                if rest_of_line.strip():
                    # Check if this line contains the SSN placeholder (Single line header)
                    # More flexible SSN pattern (case-insensitive, handle variations)
                    ssn_match = re.search(r'XXX-XXX-XXXX|XXX[-\s]XXX[-\s]XXXX', rest_of_line, re.IGNORECASE)
                    if ssn_match:
                        ssn_text = ssn_match.group(0)
                        parts = rest_of_line.split(ssn_text)
                        name_part = parts[0].strip()
                        if name_part:
                            candidate_name_buffer.append(name_part)
                        
                        # Extract File # from right side (more flexible pattern)
                        if len(parts) > 1:
                            file_match = re.search(r'(\d+)(?:\s*-\s*)?', parts[1].strip())
                            current_file_number = file_match.group(1) if file_match else "UNKNOWN"
                        else:
                            current_file_number = "UNKNOWN"
                        
                        # Optimized: Use file number as name (name not used for fingerprinting)
                        current_candidate_name = current_file_number
                        
                        # Normalize date format (ensure consistent format)
                        date_parts = current_date.split('/')
                        if len(date_parts) == 3:
                            month, day, year = date_parts
                            current_date = f"{month.zfill(2)}/{day.zfill(2)}/{year}"
                            
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
                # More flexible SSN pattern (case-insensitive, handle variations)
                ssn_match = re.search(r'XXX-XXX-XXXX|XXX[-\s]XXX[-\s]XXXX', line, re.IGNORECASE)
                if ssn_match:
                    ssn_text = ssn_match.group(0)
                    # Found the SSN line, closing the name capture
                    parts = line.split(ssn_text)
                    name_continuation = parts[0].strip()
                    if name_continuation:
                        candidate_name_buffer.append(name_continuation)
                    
                    # Extract File # (more flexible pattern)
                    if len(parts) > 1:
                        file_match = re.search(r'(\d+)(?:\s*-\s*)?', parts[1].strip())
                        current_file_number = file_match.group(1) if file_match else "UNKNOWN"
                    else:
                        current_file_number = "UNKNOWN"
                    
                    # Extract actual name from buffer
                    if candidate_name_buffer:
                        # Join all collected name parts
                        collected_name = ' '.join(candidate_name_buffer).strip()
                        # Use collected name if available, otherwise use file number
                        current_candidate_name = collected_name if collected_name else current_file_number
                    else:
                        current_candidate_name = current_file_number
                    
                    # Normalize date format (ensure consistent format)
                    if current_date:
                        date_parts = current_date.split('/')
                        if len(date_parts) == 3:
                            month, day, year = date_parts
                            current_date = f"{month.zfill(2)}/{day.zfill(2)}/{year}"
                    
                    capturing_candidate = False
                    candidate_name_buffer = []
                    continue 
                
                elif "$" in line or re.search(r'[\$]?[\d,]+\\.\d{2}', line):
                    # Safety Valve: We hit a price line but never found the SSN.
                    current_file_number = "UNKNOWN"
                    # Extract name from buffer if available
                    if candidate_name_buffer:
                        collected_name = ' '.join(candidate_name_buffer).strip()
                        current_candidate_name = collected_name if collected_name else current_file_number
                    else:
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
                # More flexible amount pattern - try multiple formats
                amount_match = None
                description = None
                amount = None
                
                # Pattern 1: Amount at the end with $ sign
                item_match = re.search(r'^(.+?)\s+\$([\d,]+\.\d{2})\s*$', line)
                if item_match:
                    description = item_match.group(1).strip()
                    amount_str = item_match.group(2).replace(',', '')
                    try:
                        amount = float(amount_str)
                    except ValueError:
                        amount = None
                
                # Pattern 2: Amount at the end without $ sign
                if amount is None:
                    item_match = re.search(r'^(.+?)\s+([\d,]+\.\d{2})\s*$', line)
                    if item_match:
                        description = item_match.group(1).strip()
                        amount_str = item_match.group(2).replace(',', '')
                        try:
                            amount = float(amount_str)
                        except ValueError:
                            amount = None
                
                # Pattern 3: More flexible - find amount anywhere near the end
                if amount is None:
                    amount_matches = list(re.finditer(r'[\$]?([\d,]+\.\d{2})', line))
                    if amount_matches:
                        # Use the last match (most likely to be the total price)
                        amount_match = amount_matches[-1]
                        amount_str = amount_match.group(1).replace(',', '')
                        try:
                            amount = float(amount_str)
                            # Description is everything before the amount
                            description = line[:amount_match.start()].strip()
                        except ValueError:
                            amount = None
                
                if amount is not None and description:
                    # Filter out headers/footers
                    if any(x in description.upper() for x in ["REPORT CHARGES", "TOTAL AMOUNT DUE", "SUBTOTAL"]):
                        continue
                    
                    # Normalize description (first meaningful words for fingerprinting)
                    desc_words = description.split()[:5]  # First 5 words sufficient
                    description = ' '.join(desc_words).strip()
                    
                    # Only add if we have a valid description
                    if description:
                        # Ensure we have a valid date (normalize if needed)
                        service_date = current_date if current_date else ""
                        if service_date:
                            date_parts = service_date.split('/')
                            if len(date_parts) == 3:
                                month, day, year = date_parts
                                service_date = f"{month.zfill(2)}/{day.zfill(2)}/{year}"
                        
                        item = ExtractedLineItem(
                            service_date=service_date,
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