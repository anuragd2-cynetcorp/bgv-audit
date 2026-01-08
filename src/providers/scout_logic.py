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
            
            # Check if extraction is complete by comparing sum with grand total
            # If no line items found, or if sum doesn't match grand total (and we have a grand total), try OCR fallback
            items_sum = sum(item.amount for item in line_items) if line_items else 0.0
            should_try_ocr = False
            
            if not line_items:
                should_try_ocr = True
                logger.info("No line items found with text extraction. Attempting OCR fallback for Scout Logic invoice.")
            elif grand_total > 0.0 and abs(grand_total - items_sum) > 0.01:
                should_try_ocr = True
                logger.info(f"Text extraction found {len(line_items)} items with sum ${items_sum:.2f}, but grand total is ${grand_total:.2f}. Attempting OCR fallback for Scout Logic invoice.")
            
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
                # Reset previous candidate context when encountering a new date line
                current_candidate_name = None
                current_date = None
                current_file_number = None
                
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
                # Reset previous candidate context
                current_candidate_name = None
                current_date = None
                current_file_number = None
                
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
                # Skip headers and subtotals - more comprehensive filtering
                skip_keywords = [
                    "DATE NAME SSN", "Subtotal for", "REPORT CHARGES",
                    "Total Amount Due", "Total Amount", "Amount Due",
                    "Invoice Total", "Grand Total", "TOTAL", "Total:",
                    "Summary", "Subtotal:", "Sub-total"
                ]
                if any(x in line.upper() for x in [kw.upper() for kw in skip_keywords]):
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
                    
                    # Additional filtering: Skip if description looks like a total/subtotal line
                    description_upper = description.upper()
                    if any(x in description_upper for x in ["TOTAL", "SUBtotal", "AMOUNT DUE", "SUMMARY"]):
                        continue

                    # Normalize description (first meaningful words for fingerprinting)
                    desc_words = description.split()[:5]  # First 5 words sufficient
                    description = ' '.join(desc_words).strip()
                    
                    # Skip empty descriptions
                    if not description:
                        continue

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