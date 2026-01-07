"""
Provider extractor for HealthStreet invoices.
"""
import re
from typing import List
from .base import BaseProvider, ExtractedInvoice, ExtractedLineItem
from src.logger import get_logger

logger = get_logger()


class HealthStreetProvider(BaseProvider):
    """Extractor for HealthStreet invoices."""
    
    def __init__(self):
        super().__init__("HealthStreet")
        self.identification_keywords = ["HealthStreet", "HEALTHSTREET", "healthstreet.com"]
    
    def identify(self, pdf_path: str) -> bool:
        """Check if this PDF belongs to HealthStreet."""
        text = self._get_pdf_text(pdf_path)
        return any(kw.upper() in text.upper() for kw in self.identification_keywords)
    
    def extract(self, pdf_path: str) -> ExtractedInvoice:
        """Extract invoice data from HealthStreet's PDF format."""
        import pdfplumber
        
        invoice_number = BaseProvider.generate_unknown_invoice_number()
        grand_total = 0.0
        line_items = []
        
        with pdfplumber.open(pdf_path) as pdf:
            # 1. Extract Header Info (Page 1)
            first_page_text = pdf.pages[0].extract_text()
            
            # Invoice Number
            invoice_number_match = re.search(r'Invoice\s*[#:]?\s*([A-Z0-9\-]+)', first_page_text, re.IGNORECASE)
            if invoice_number_match:
                invoice_number = invoice_number_match.group(1)
            
            # Grand Total
            match = re.search(r'Total[:\s]*\$?([\d,]+\.?\d*)', first_page_text, re.IGNORECASE)
            if match:
                grand_total = float(match.group(1).replace(',', ''))
            
            # 2. Extract Line Items
            # Try normal text extraction first
            lines = self._get_text_lines(pdf_path, use_ocr=False)
            line_items = self._parse_text_lines(lines)
            
            # If no line items found, try OCR fallback
            if not line_items:
                logger.info("No line items found with text extraction. Attempting OCR fallback for HealthStreet invoice.")
                try:
                    lines = self._get_text_lines(pdf_path, use_ocr=True)
                    line_items = self._parse_text_lines(lines)
                    logger.info(f"OCR extraction found {len(line_items)} line items.")
                except Exception as e:
                    logger.error(f"OCR extraction failed: {str(e)}", exc_info=True)
                    # Continue to raise the original error if OCR also fails
        
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
        
        Args:
            lines: List of text lines to parse
            
        Returns:
            List of ExtractedLineItem objects
        """
        # TODO: Implement based on HealthStreet's format
        return []

