"""
Provider extractor for Summit Health invoices.
"""
import re
from typing import List
from .base import BaseProvider, ExtractedInvoice, ExtractedLineItem


class SummitHealthProvider(BaseProvider):
    """Extractor for Summit Health invoices."""
    
    def __init__(self):
        super().__init__("Summit Health")
        self.identification_keywords = ["Summit Health", "SUMMIT HEALTH", "summithealth.com"]
    
    def identify(self, pdf_path: str) -> bool:
        """Check if this PDF belongs to Summit Health."""
        text = self._get_pdf_text(pdf_path)
        return any(kw.upper() in text.upper() for kw in self.identification_keywords)
    
    def extract(self, pdf_path: str) -> ExtractedInvoice:
        """Extract invoice data from Summit Health's PDF format."""
        text = self._get_pdf_text(pdf_path)
        tables = self._get_pdf_tables(pdf_path)
        
        invoice_number_match = re.search(r'Invoice\s*[#:]?\s*([A-Z0-9\-]+)', text, re.IGNORECASE)
        invoice_number = invoice_number_match.group(1) if invoice_number_match else BaseProvider.generate_unknown_invoice_number()
        
        match = re.search(r'Total[:\s]*\$?([\d,]+\.?\d*)', text, re.IGNORECASE)
        grand_total = float(match.group(1).replace(',', '')) if match else None
        
        if grand_total is None:
            raise ValueError("Could not extract grand total from invoice")
        
        line_items = self._extract_from_tables(tables) if tables else []
        if not line_items:
            raise ValueError("Could not extract line items from invoice")
        
        return ExtractedInvoice(
            invoice_number=invoice_number,
            provider_name=self.name,
            line_items=line_items,
            grand_total=grand_total
        )
    
    def _extract_from_tables(self, tables: List[List[List[str]]]) -> List[ExtractedLineItem]:
        """Extract line items from PDF tables."""
        # TODO: Implement based on Summit Health's format
        return []
    
    def _extract_from_text(self, text: str) -> List[ExtractedLineItem]:
        """Extract line items from text."""
        return []

