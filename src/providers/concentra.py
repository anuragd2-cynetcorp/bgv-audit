"""
Provider extractor for Concentra invoices.
"""
import re
import pdfplumber
from typing import List
from .base import BaseProvider, ExtractedInvoice, ExtractedLineItem
from src.logger import get_logger

logger = get_logger()


class ConcentraProvider(BaseProvider):
    """
    Extractor for Concentra invoices.
    
    Format Characteristics:
    - Header contains 'Invoice:' or 'Invoice Number'.
    - Line Items are text rows.
    - Structure: Date | Name | SSN (masked) | Description | Amount
    - Strategy: Use the distinct SSN pattern (XXX-XX-####) to split the line.
    """
    
    def __init__(self):
        """Initialize the Concentra provider."""
        super().__init__("Concentra")
        self.identification_keywords = ["Concentra", "Occupational Health Centers"]
    
    def identify(self, pdf_path: str) -> bool:
        """Check if this PDF belongs to Concentra."""
        text = self._get_pdf_text(pdf_path)
        return any(kw in text for kw in self.identification_keywords)
    
    def extract(self, pdf_path: str) -> ExtractedInvoice:
        """
        Extract invoice data from Concentra's PDF format.
        """
        invoice_number = "UNKNOWN"
        grand_total = 0.0
        line_items = []
        
        with pdfplumber.open(pdf_path) as pdf:
            # 1. Extract Header Info (Page 1)
            first_page_text = pdf.pages[0].extract_text()
            
            # Invoice Number
            inv_match = re.search(r'Invoice(?:\s*Number)?\s*[:#]?\s*(\d+)', first_page_text, re.IGNORECASE)
            if inv_match:
                invoice_number = inv_match.group(1)
            
            # Grand Total
            # Try normal pattern first
            total_match = re.search(r'Balance(?: Due)?\s*[:]?\s*[5S]?\s*([\d,]+\.\d{2})', first_page_text, re.IGNORECASE)
            if total_match:
                grand_total = float(total_match.group(1).replace(',', ''))

            # 2. Extract Line Items
            # Try normal text extraction first
            lines = self._get_text_lines(pdf_path, use_ocr=False)
            line_items = self._parse_text_lines(lines)
            
            # Check if extraction is complete by comparing sum with grand total
            # If no line items found, or if sum doesn't match grand total (and we have a grand total), try OCR fallback
            items_sum = sum(item.amount for item in line_items) if line_items else 0.0
            should_try_ocr = False
            
            if not line_items:
                should_try_ocr = True
                logger.info("No line items found with text extraction. Attempting OCR fallback for Concentra invoice.")
            elif grand_total > 0.0 and abs(grand_total - items_sum) > 0.01:
                should_try_ocr = True
                logger.info(f"Text extraction found {len(line_items)} items with sum ${items_sum:.2f}, but grand total is ${grand_total:.2f}. Attempting OCR fallback for Concentra invoice.")
            
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
        Parse text lines into line items using Concentra-specific logic.
        Uses SSN-based parsing strategy to extract line items.
        Handles multi-line descriptions and flexible amount formats.
        
        Args:
            lines: List of text lines to parse
            
        Returns:
            List of ExtractedLineItem objects
        """
        line_items = []
        
        # Pattern for SSN (XXX-XX-####) - can vary slightly with OCR
        ssn_pattern = re.compile(r'XXX-XX-\d{4}|XXX[-\s]XX[-\s]\d{4}', re.IGNORECASE)
        date_pattern = re.compile(r'^\s*(\d{1,2}/\d{1,2}/\d{4})')
        
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            
            if not line:
                i += 1
                continue
            
            # --- Anchor Strategy: Find the SSN ---
            # Concentra always puts masked SSN (XXX-XX-####) in the middle of the line
            ssn_match = ssn_pattern.search(line)
            
            if not ssn_match:
                i += 1
                continue
            
            # Split the line into two parts: Before SSN and After SSN
            pre_ssn = line[:ssn_match.start()]
            post_ssn = line[ssn_match.end():]
            
            candidate_id = ssn_match.group(0).upper().replace(' ', '-')  # Normalize SSN format
            
            # --- Parse Left Side (Date + Name) ---
            # Look for Date at the start (more flexible pattern)
            date_match = date_pattern.match(pre_ssn)
            
            if not date_match:
                i += 1
                continue
            
            service_date = date_match.group(1)
            # Normalize date format (ensure consistent format)
            date_parts = service_date.split('/')
            if len(date_parts) == 3:
                month, day, year = date_parts
                service_date = f"{month.zfill(2)}/{day.zfill(2)}/{year}"
            
            # Optimized: Use SSN as name (name not used for fingerprinting)
            candidate_name = candidate_id
            
            # --- Parse Right Side (Description + Amount) ---
            # Try multiple patterns for amount extraction
            
            # Pattern 1: Amount at the end with $ sign
            amount_match = re.search(r'\$([\d,]+\.\d{2})\s*$', post_ssn)
            
            # Pattern 2: Amount at the end without $ sign
            if not amount_match:
                amount_match = re.search(r'([\d,]+\.\d{2})\s*$', post_ssn)
            
            # Pattern 3: Amount anywhere near the end (last 20 chars)
            if not amount_match:
                end_portion = post_ssn[-30:] if len(post_ssn) > 30 else post_ssn
                amount_matches = list(re.finditer(r'[\$]?([\d,]+\.\d{2})', end_portion))
                if amount_matches:
                    amount_match = amount_matches[-1]  # Use last match (most likely to be total)
            
            # Check for multi-line description
            merged_post_ssn = post_ssn
            next_i = i + 1
            
            # Look ahead for continuation lines (descriptions split across lines)
            while next_i < len(lines) and next_i < i + 3:  # Check up to 2 lines ahead
                next_line = lines[next_i].strip()
                
                if not next_line:
                    next_i += 1
                    continue
                
                # If next line starts with date or has SSN, we've found the next item
                if date_pattern.match(next_line) or ssn_pattern.search(next_line):
                    break
                
                # If next line looks like continuation (text without date/SSN), merge it
                if re.match(r'^[A-Za-z]', next_line) and not ssn_pattern.search(next_line):
                    merged_post_ssn += ' ' + next_line
                    next_i += 1
                else:
                    break
            
            # Re-extract amount from merged description if needed
            if amount_match:
                # Find amount in merged description
                merged_amount_match = re.search(r'[\$]?([\d,]+\.\d{2})\s*$', merged_post_ssn)
                if merged_amount_match:
                    amount_match = merged_amount_match
            
            if not amount_match:
                i = next_i
                continue
            
            amount_str = amount_match.group(1).replace(',', '')
            try:
                amount = float(amount_str)
            except ValueError:
                i = next_i
                continue
            
            # Description is everything between SSN and Amount (use merged if available)
            description = merged_post_ssn[:amount_match.start()].strip()
            
            # Normalize description (first meaningful words for fingerprinting)
            if description:
                desc_words = description.split()[:5]  # First 5 words sufficient
                description = ' '.join(desc_words).strip()
            else:
                description = "Service"
            
            # Create metadata
            metadata = {
                "source_ssn": candidate_id
            }
            
            # Create Line Item
            item = ExtractedLineItem(
                service_date=service_date,
                candidate_id=candidate_id,
                candidate_name=candidate_name,
                amount=amount,
                service_description=description,
                metadata=metadata
            )
            line_items.append(item)
            
            # Move to next line (or past continuation lines)
            i = next_i
        
        return line_items