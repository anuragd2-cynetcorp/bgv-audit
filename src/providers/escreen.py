"""
Provider extractor for eScreen invoices.
"""
import re
import pdfplumber
from typing import List
from .base import BaseProvider, ExtractedInvoice, ExtractedLineItem
from src.logger import get_logger

logger = get_logger()


class EScreenProvider(BaseProvider):
    """
    Extractor for eScreen invoices.
    
    Format Characteristics:
    - Header contains 'Invoice Number' (Page 1).
    - Footer contains 'TOTAL :' (Last Page).
    - Line items are text rows starting with a Date.
    - Structure: Date | Description | Donor Name | SSN (4 digits) | Chain ID | ... | Total Price
    """
    
    def __init__(self):
        """Initialize the eScreen provider."""
        super().__init__("eScreen")
        self.identification_keywords = ["eScreen", "ESCREEN", "escreen.com"]
    
    def identify(self, pdf_path: str) -> bool:
        """Check if this PDF belongs to eScreen."""
        text = self._get_pdf_text(pdf_path)
        return any(kw.upper() in text.upper() for kw in self.identification_keywords)
    
    def extract(self, pdf_path: str) -> ExtractedInvoice:
        """
        Extract invoice data from eScreen's PDF format using Regex on raw text.
        Optimized for duplicate detection and total mismatch checking.
        """
        invoice_number = BaseProvider.generate_unknown_invoice_number()
        grand_total = 0.0
        line_items = []
        
        with pdfplumber.open(pdf_path) as pdf:
            # 1. Extract Invoice Number (Page 1)
            first_page_text = pdf.pages[0].extract_text()
            inv_match = re.search(r'Invoice Number:\s*(\d+)', first_page_text)
            if inv_match:
                invoice_number = inv_match.group(1)
            
            # 2. Extract Grand Total (Last Page)
            last_page_text = pdf.pages[-1].extract_text()
            total_match = re.search(r'TOTAL\s*:\s*\$([\d,]+\.\d{2})', last_page_text)
            if total_match:
                grand_total = float(total_match.group(1).replace(',', ''))
            
            # 3. Extract Line Items (optimized for duplicate detection and total mismatch)
            lines = self._get_text_lines(pdf_path, use_ocr=False)
            line_items = self._parse_text_lines(lines)
            
            # If no line items found, try OCR fallback
            if not line_items:
                logger.info("No line items found with text extraction. Attempting OCR fallback for eScreen invoice.")
                try:
                    lines = self._get_text_lines(pdf_path, use_ocr=True)
                    line_items = self._parse_text_lines(lines)
                    logger.info(f"OCR extraction found {len(line_items)} line items.")
                except Exception as e:
                    logger.error(f"OCR extraction failed: {str(e)}", exc_info=True)
                    # Continue to raise the original error if OCR also fails
        
        if not line_items:
            raise ValueError("Could not extract line items. Format may have changed or file is scanned.")
            
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
        Parse text lines into line items using eScreen-specific logic.
        
        Format: DATE DESCRIPTION NAME SSN CHAIN_ID CLIENT QTY UNIT_PRICE TOTAL_PRICE
        Descriptions can be split across multiple lines.
        
        Args:
            lines: List of text lines to parse
            lightweight: If True, only extract essentials for duplicate detection and total mismatch
                        (skips expensive name/description parsing)
            
        Returns:
            List of ExtractedLineItem objects
        """
        line_items = []
        
        # Pattern to identify lines that start a new item (date at start)
        date_pattern = re.compile(r'^(\d{1,2}/\d{1,2}/\d{4})\s+(.+)$')
        
        # Pattern to identify header/section lines to skip
        skip_pattern = re.compile(
            r'^(?:Tests for site|Collection|Date|INVOICE|Invoice|eScreen|Bill To|Sell To|Due Date|Product Ship Date|Tax|TOTAL|REMIT|Sell-To|Customer|FedEx)',
            re.IGNORECASE
        )
        
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            
            # Skip empty lines
            if not line:
                i += 1
                continue
            
            # Skip header/section lines
            if skip_pattern.match(line):
                i += 1
                continue
            
            # Check if this line starts with a date (potential line item start)
            date_match = date_pattern.match(line)
            if not date_match:
                i += 1
                continue
            
            # This looks like a line item start - merge continuation lines
            merged_parts = [line]
            date_str = date_match.group(1)
            rest_of_line = date_match.group(2)
            next_i = i + 1
            
            # Merge continuation lines (descriptions or client names split across lines)
            # Look ahead up to 3 lines for continuation
            look_ahead = 0
            while look_ahead < 3 and next_i < len(lines):
                next_line = lines[next_i].strip()
                
                # Skip empty lines
                if not next_line:
                    next_i += 1
                    look_ahead += 1
                    continue
                
                # If next line starts with a date, we've found the next item
                if date_pattern.match(next_line):
                    break
                
                # If next line is a section header, stop
                if skip_pattern.match(next_line):
                    break
                
                # If next line looks like a continuation (just text, no date), merge it
                # Common patterns: "Collection", "Inc.", description words, names, etc.
                # More aggressive merging - merge if it doesn't start with a date and doesn't end with amount
                is_date_line = date_pattern.match(next_line)
                has_amount_at_end = re.search(r'\$[\d,]+\.\d{2}\s*$', next_line)
                
                if not is_date_line and not has_amount_at_end:
                    # This looks like a continuation line
                    # Check if it's a section header
                    if not skip_pattern.match(next_line):
                        merged_parts.append(next_line)
                        next_i += 1
                        look_ahead += 1
                        continue
                
                # If next line is a section header or has amount, stop merging
                if skip_pattern.match(next_line) or has_amount_at_end:
                    break
                
                # If next line starts with date, we've found next item
                if is_date_line:
                    break
                
                # Otherwise, try merging if it's short text (likely continuation)
                if re.match(r'^[A-Za-z\s\-\.\,\']+$', next_line) and len(next_line) < 60:
                    merged_parts.append(next_line)
                    next_i += 1
                    look_ahead += 1
                else:
                    break
            
            # Merge all parts into one line
            merged_line = ' '.join(merged_parts)
            
            # Now try to extract the line item data
            # Strategy: Find date, SSN (4 digits), Chain ID (numeric), and amount (last $XX.XX)
            # Format: DATE DESCRIPTION NAME SSN CHAIN_ID CLIENT QTY UNIT_PRICE TOTAL_PRICE
            
            # Step 1: Extract date
            date_match = re.match(r'^(\d{1,2}/\d{1,2}/\d{4})\s+', merged_line)
            if not date_match:
                i = next_i
                continue
            
            date_str = date_match.group(1)
            
            # Step 2: Find SSN (4 digits) and Chain ID - this is our anchor
            # Look for pattern: space, 4 digits (SSN), space, Chain ID (numeric or alphanumeric)
            # Chain IDs can vary: numeric (8-12 digits) or alphanumeric (like BAT79282216)
            
            # Pattern 1: SSN (4 digits) followed by Chain ID (alphanumeric like BAT79282216)
            ssn_pattern = re.compile(r'\s+(\d{4})\s+([A-Z]{2,}[A-Z0-9]{5,})')  # SSN + alphanumeric Chain ID
            ssn_matches = list(ssn_pattern.finditer(merged_line))
            
            if not ssn_matches:
                # Pattern 2: SSN (4 digits) followed by numeric Chain ID (7+ digits)
                ssn_pattern = re.compile(r'\s+(\d{4})\s+(\d{7,})')
                ssn_matches = list(ssn_pattern.finditer(merged_line))
            
            if not ssn_matches:
                # Pattern 3: SSN (4 digits) followed by shorter numeric Chain ID (5-6 digits)
                ssn_pattern = re.compile(r'\s+(\d{4})\s+(\d{5,6})')
                ssn_matches = list(ssn_pattern.finditer(merged_line))
            
            # Pattern 4: No SSN, just Chain ID (8-10 digits numeric) - happens when SSN is "0000" or missing
            if not ssn_matches:
                # Look for Chain ID (8-10 digits) directly after name
                # But make sure it's not part of a date or other field
                chain_id_pattern = re.compile(r'\s+(\d{8,10})\s+')  # Chain ID (8-10 digits) followed by space
                chain_id_matches = list(chain_id_pattern.finditer(merged_line))
                
                if chain_id_matches:
                    # Use the first match as Chain ID, SSN is "0000" (not provided)
                    chain_id_match = chain_id_matches[0]
                    ssn = "0000"
                    chain_id = chain_id_match.group(1)
                    # Create a match object for compatibility with existing code
                    class ChainIDMatch:
                        def __init__(self, ssn, chain_id, start_pos):
                            self.groups = [ssn, chain_id]
                            self.start_pos = start_pos
                        def start(self):
                            return self.start_pos
                        def group(self, n):
                            if n == 1:
                                return self.groups[0]
                            elif n == 2:
                                return self.groups[1]
                            return None
                    ssn_match = ChainIDMatch(ssn, chain_id, chain_id_match.start())
                    ssn_matches = [ssn_match]
            
            if not ssn_matches:
                i = next_i
                continue
            
            # Use the last SSN match (sometimes there are multiple)
            ssn_match = ssn_matches[-1]
            # Check if it's our custom ChainIDMatch class
            if hasattr(ssn_match, 'start_pos'):
                # Custom ChainIDMatch object
                ssn = ssn_match.groups[0] if len(ssn_match.groups) > 0 else "0000"
                chain_id = ssn_match.groups[1] if len(ssn_match.groups) > 1 else ""
            else:
                # Regular regex match object
                ssn = ssn_match.group(1)
                chain_id = ssn_match.group(2)
            
            # Step 3: Extract amount (find all $ amounts, use the last one as total price)
            amount_matches = list(re.finditer(r'\$([\d,]+\.\d{2})', merged_line))
            if not amount_matches:
                i = next_i
                continue
            
            # Last amount is the total price
            amount_match = amount_matches[-1]
            amount_str = amount_match.group(1)
            
            # Step 4: Extract middle chunk (description + name) - everything between date and SSN/Chain ID
            if hasattr(ssn_match, 'start'):
                ssn_start_pos = ssn_match.start()
            else:
                # Fallback: find position of SSN or Chain ID in merged_line
                ssn_start_pos = merged_line.find(ssn if ssn != "0000" else chain_id, date_match.end())
                if ssn_start_pos == -1:
                    ssn_start_pos = len(merged_line)
            
            middle_chunk = merged_line[date_match.end():ssn_start_pos].strip()
            
            try:
                amount = float(amount_str.replace(',', ''))
            except ValueError:
                i = next_i
                continue
            
            # Determine ID (SSN or Chain ID) - needed for both modes
            final_id = ssn
            if ssn == "0000":
                final_id = chain_id
            
            # Optimized extraction: Extract essentials for duplicate detection and total mismatch
            # Try simple name extraction (last "Lastname, Firstname" pattern) without complex fallbacks
            # This gives reasonable names for display while being fast
            name_match = re.search(r'([A-Za-z\-\']+,\s+[A-Za-z\-\']+(?:\s+[A-Za-z\-\']+)?)\s*$', middle_chunk)
            if name_match:
                candidate_name = name_match.group(1).strip()
                description = middle_chunk[:name_match.start()].strip()
            else:
                # Fallback: use ID as name, use first part as description
                candidate_name = final_id
                # Extract description as first meaningful words
                words = middle_chunk.split()
                # Take first 5 words as description (usually enough for identification)
                description = ' '.join(words[:5]).strip()
            
            # Normalize description (remove extra whitespace)
            description = re.sub(r'\s+', ' ', description).strip().rstrip(' -')
            
            # Determine ID (SSN or Chain ID) - common for both lightweight and full modes
            final_id = ssn
            if ssn == "0000":
                final_id = chain_id
            
            item = ExtractedLineItem(
                service_date=date_str,
                candidate_id=final_id,
                candidate_name=candidate_name,
                amount=amount,
                service_description=description,
                metadata={
                    "chain_of_custody": chain_id,
                    "ssn_last_4": ssn
                }
            )
            line_items.append(item)
            
            i = next_i
        
        return line_items

