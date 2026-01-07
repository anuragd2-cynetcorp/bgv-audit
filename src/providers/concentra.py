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
            total_match = re.search(r'Balance(?: Due)?\s*[:]?\s*\$?([\d,]+\.\d{2})', first_page_text, re.IGNORECASE)
            if total_match:
                grand_total = float(total_match.group(1).replace(',', ''))

            # 2. Extract Line Items
            # Try normal text extraction first
            lines = self._get_text_lines(pdf_path, use_ocr=False)
            line_items = self._parse_text_lines(lines)
            
            # If no line items found, try OCR fallback
            if not line_items:
                logger.info("No line items found with text extraction. Attempting OCR fallback for Concentra invoice.")
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
        Parse text lines into line items using Concentra-specific logic.
        Uses SSN-based parsing strategy to extract line items.
        
        Args:
            lines: List of text lines to parse
            
        Returns:
            List of ExtractedLineItem objects
        """
        line_items = []
        
        for line in lines:
            # --- Anchor Strategy: Find the SSN ---
            # Concentra always puts masked SSN (XXX-XX-####) in the middle of the line
            ssn_match = re.search(r'(XXX-XX-\d{4})', line)
            
            if ssn_match:
                # Split the line into two parts: Before SSN and After SSN
                pre_ssn = line[:ssn_match.start()]
                post_ssn = line[ssn_match.end():]
                
                candidate_id = ssn_match.group(1)
                
                # --- Parse Left Side (Date + Name) ---
                # Look for Date at the start
                date_match = re.match(r'^\s*(\d{1,2}/\d{1,2}/\d{4})', pre_ssn)
                
                if date_match:
                    service_date = date_match.group(1)
                    # Name is everything between Date and SSN
                    candidate_name = pre_ssn[date_match.end():].strip()
                    
                    # --- Parse Right Side (Description + Amount) ---
                    # Look for Amount at the very end of the line
                    amount_match = re.search(r'([\d,]+\.\d{2})\s*$', post_ssn)
                    
                    if amount_match:
                        amount_str = amount_match.group(1).replace(',', '')
                        amount = float(amount_str)
                        
                        # Description is everything between SSN and Amount
                        description = post_ssn[:amount_match.start()].strip()
                        
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
        
        return line_items