"""
Provider extractor for CityMD invoices.
"""
import re
import pdfplumber
from typing import List
from .base import BaseProvider, ExtractedInvoice, ExtractedLineItem
from src.logger import get_logger

logger = get_logger()


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
                logger.info("No line items found with text extraction. Attempting OCR fallback for CityMD invoice.")
            elif grand_total > 0.0 and abs(grand_total - items_sum) > 0.01:
                should_try_ocr = True
                logger.info(f"Text extraction found {len(line_items)} items with sum ${items_sum:.2f}, but grand total is ${grand_total:.2f}. Attempting OCR fallback for CityMD invoice.")
            
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
             # Fallback: Sum line items if header extraction failed
             grand_total = sum(item.amount for item in line_items)

        return ExtractedInvoice(
            invoice_number=invoice_number,
            provider_name=self.name,
            line_items=line_items,
            grand_total=grand_total
        )
    
    def _parse_text_lines(self, lines: List[str]) -> List[ExtractedLineItem]:
        """
        Parse text lines into line items using CityMD-specific logic.
        Applies patient header and service line parsing strategy.
        
        Args:
            lines: List of text lines to parse
            
        Returns:
            List of ExtractedLineItem objects
        """
        line_items = []
        
        # State variables
        current_candidate_name = None
        current_candidate_id = None
        
        for line in lines:
            # --- State Change: Patient Header ---
            # Pattern: "Patient:" followed by name, then "Patient ID:" followed by ID
            pat_match = re.search(r'Patient:\s*(.+?)\s+Patient ID:\s*(\d+)', line)
            if pat_match:
                # Optimized: Use ID as name (name not used for fingerprinting)
                current_candidate_id = pat_match.group(2).strip()
                current_candidate_name = current_candidate_id
                continue
            
            # --- Extract Service Line ---
            # Only process if we have a valid patient context
            if current_candidate_name:
                # Pattern: Date | (Optional Code) | Description | Amount (can be negative)
                # More flexible date pattern: handle single/double digit months and days
                date_match = re.match(r'^(\d{1,2}/\d{1,2}/\d{4})', line)
                if not date_match:
                    continue
                
                date_str = date_match.group(1)
                
                # Try multiple patterns for more robust extraction
                proc_code = None
                description = None
                amount = None
                amount_str = None
                
                # Pattern 1: Date | Procedure Code | Description | Amount
                # Procedure code: alphanumeric, can contain commas (e.g., "81099,MMRV")
                item_match = re.match(r'^\d{1,2}/\d{1,2}/\d{4}\s+([A-Z0-9,]+)\s+(.+?)\s+(-?)\$?([\d,]+\.\d{2})\s*$', line)
                if item_match:
                    proc_code = item_match.group(1)
                    description = item_match.group(2).strip()
                    minus_sign = item_match.group(3)
                    amount_str = item_match.group(4).replace(',', '')
                    try:
                        amount = float(amount_str)
                        if minus_sign == '-':
                            amount = -amount
                    except ValueError:
                        amount = None
                
                # Pattern 2: Date | Description | Amount (no procedure code)
                if amount is None:
                    item_match = re.match(r'^\d{1,2}/\d{1,2}/\d{4}\s+(.+?)\s+(-?)\$?([\d,]+\.\d{2})\s*$', line)
                    if item_match:
                        description = item_match.group(1).strip()
                        minus_sign = item_match.group(2)
                        amount_str = item_match.group(3).replace(',', '')
                        try:
                            amount = float(amount_str)
                            if minus_sign == '-':
                                amount = -amount
                        except ValueError:
                            amount = None
                
                # Pattern 3: More flexible - find amount anywhere in line (OCR/formatting issues)
                if amount is None:
                    # Look for amount pattern (with or without $)
                    amount_matches = list(re.finditer(r'[\$]?([\d,]+\.\d{2})', line))
                    if amount_matches:
                        # Use the last amount (usually the total price)
                        amount_match = amount_matches[-1]
                        amount_str = amount_match.group(1).replace(',', '')
                        try:
                            amount = float(amount_str)
                            # Check for negative sign before amount
                            amount_start = amount_match.start()
                            if amount_start > 0 and line[amount_start - 1] == '-':
                                amount = -amount
                            # Extract description: everything between date and amount
                            description = line[date_match.end():amount_start].strip()
                        except ValueError:
                            amount = None
                
                # Skip if we couldn't extract amount
                if amount is None:
                    continue
                
                # Normalize description (first meaningful words for fingerprinting)
                if description:
                    desc_words = description.split()[:5]  # First 5 words sufficient
                    description = ' '.join(desc_words).strip()
                else:
                    description = "Service"
                
                # Normalize date format (ensure consistent format)
                # Convert single digit months/days to double digit if needed
                date_parts = date_str.split('/')
                if len(date_parts) == 3:
                    month, day, year = date_parts
                    date_str = f"{month.zfill(2)}/{day.zfill(2)}/{year}"
                
                metadata = {}
                if proc_code:
                    metadata["procedure_code"] = proc_code
                
                item = ExtractedLineItem(
                    service_date=date_str,
                    candidate_id=current_candidate_id,
                    candidate_name=current_candidate_name,
                    amount=amount,
                    service_description=description,
                    metadata=metadata
                )
                line_items.append(item)
        
        return line_items

