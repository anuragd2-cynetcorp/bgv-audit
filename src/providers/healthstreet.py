"""
Provider extractor for HealthStreet invoices.

Format Characteristics:
- Can be single or multi-page invoices
- Header contains 'Invoice #' and 'Total Invoice'/'Balance Due'
- Data lines: Date Name Service Fee
- Format: MM/DD/YYYY <Name> <Service Description> <Amount>
- Grand total may appear on first or last page
"""
import re
import pdfplumber
from typing import List
from .base import BaseProvider, ExtractedInvoice, ExtractedLineItem, normalize_description
from src.logger import get_logger

logger = get_logger()


class HealthStreetProvider(BaseProvider):
    """Extractor for HealthStreet invoices."""
    
    def __init__(self):
        super().__init__("HealthStreet")
        self.identification_keywords = ["Health Street", "HealthStreet", "healthstreet.com"]
    
    def identify(self, pdf_path: str) -> bool:
        """Check if this PDF belongs to HealthStreet."""
        text = self._get_pdf_text(pdf_path)
        text_upper = text.upper()
        # Check for Health Street (with or without space)
        return "HEALTH STREET" in text_upper or "HEALTHSTREET" in text_upper
    
    def extract(self, pdf_path: str) -> ExtractedInvoice:
        """
        Extract invoice data from HealthStreet's PDF format.
        
        Format is simple:
        - Invoice # on first page
        - Total Invoice or Balance Due for grand total
        - Data lines: Date Name Service Fee
        """
        invoice_number = BaseProvider.generate_unknown_invoice_number()
        grand_total = 0.0
        line_items = []
        
        with pdfplumber.open(pdf_path) as pdf:
            # 1. Extract Header Info
            # Invoice number is typically on first page
            first_page_text = pdf.pages[0].extract_text() or ""
            
            # Invoice Number - pattern: "Invoice # 55940-2025-11"
            invoice_match = re.search(r'Invoice\s*#\s*([A-Z0-9\-]+)', first_page_text, re.IGNORECASE)
            if invoice_match:
                invoice_number = invoice_match.group(1)
            
            # Grand Total - check all pages (may be on last page for multi-page invoices)
            # Pattern: "Total Invoice $558.00" or "Balance Due $558.00"
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                total_match = re.search(r'(?:Total Invoice|Balance Due)\s*\$?([\d,]+\.?\d*)', page_text, re.IGNORECASE)
                if total_match:
                    # Use the last found total (typically on last page)
                    grand_total = float(total_match.group(1).replace(',', ''))
        
        # 2. Extract Line Items
        # Try normal text extraction first
        lines = self._get_text_lines(pdf_path, use_ocr=False)
        line_items = self._parse_text_lines(lines)
        
        # Check if extraction is complete by comparing sum with grand total
        items_sum = sum(item.amount for item in line_items) if line_items else 0.0
        should_try_ocr = False
        
        if not line_items:
            should_try_ocr = True
            logger.info("No line items found with text extraction. Attempting OCR fallback for HealthStreet invoice.")
        elif grand_total > 0.0 and abs(grand_total - items_sum) > 0.01:
            should_try_ocr = True
            logger.info(f"Text extraction found {len(line_items)} items with sum ${items_sum:.2f}, but grand total is ${grand_total:.2f}. Attempting OCR fallback.")
        
        if should_try_ocr:
            try:
                ocr_lines = self._get_text_lines(pdf_path, use_ocr=True)
                ocr_line_items = self._parse_text_lines(ocr_lines)
                ocr_sum = sum(item.amount for item in ocr_line_items) if ocr_line_items else 0.0
                
                # Use OCR results if they're better
                if not line_items or (grand_total > 0.0 and abs(grand_total - ocr_sum) < abs(grand_total - items_sum)):
                    line_items = ocr_line_items
                    logger.info(f"OCR extraction found {len(line_items)} line items with sum ${ocr_sum:.2f}.")
                elif line_items:
                    logger.info(f"OCR extraction found {len(ocr_line_items)} items but text extraction had better match.")
            except Exception as e:
                logger.error(f"OCR extraction failed: {str(e)}", exc_info=True)
        
        if not line_items:
            raise ValueError("Could not extract line items from invoice")
        
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
        Parse text lines into line items using HealthStreet-specific logic.
        
        Format: MM/DD/YYYY <Name> <Service Description> <Amount>
        Example: 11/3/2025 Jenell Hillaire Instant 9 Panel Urine 93.00
        
        Args:
            lines: List of text lines to parse
            
        Returns:
            List of ExtractedLineItem objects
        """
        line_items = []
        
        # Pattern for data lines:
        # Date (MM/DD/YYYY or M/D/YYYY) followed by name, service, and amount
        # Example: "11/3/2025 Jenell Hillaire Instant 9 Panel Urine 93.00"
        data_pattern = re.compile(
            r'^(\d{1,2}/\d{1,2}/\d{4})\s+'  # Date
            r'(.+?)\s+'                       # Name (non-greedy)
            r'(\d+\.?\d*)$'                   # Amount at end
        )
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Skip header/footer lines
            if any(skip in line.lower() for skip in ['invoice', 'total', 'balance', 'payment', 'due date', 'page', 'date name service', 'cynet']):
                continue
            
            # Try to match data line
            match = data_pattern.match(line)
            if match:
                service_date = match.group(1)
                middle_part = match.group(2).strip()
                amount_str = match.group(3)
                
                try:
                    amount = float(amount_str)
                except ValueError:
                    continue
                
                # Parse middle part: Name + Service Description
                # The name is typically 2 words (First Last), rest is service
                words = middle_part.split()
                if len(words) >= 3:
                    # Assume first 2 words are name, rest is service
                    candidate_name = ' '.join(words[:2])
                    service_description = ' '.join(words[2:])
                elif len(words) == 2:
                    # Only 2 words, could be just name with no service
                    candidate_name = ' '.join(words)
                    service_description = "Service"
                else:
                    # Single word or empty
                    candidate_name = middle_part or "Unknown"
                    service_description = "Service"
                
                # Generate candidate_id from name (no SSN in HealthStreet format)
                # Use normalized name as ID
                candidate_id = candidate_name.upper().replace(' ', '')
                
                # Normalize description
                service_description = normalize_description(service_description)
                
                item = ExtractedLineItem(
                    candidate_name=candidate_id,  # Use ID as name for consistency
                    candidate_id=candidate_id,
                    amount=amount,
                    service_date=service_date,
                    service_description=service_description,
                    metadata={}
                )
                line_items.append(item)
        
        return line_items

