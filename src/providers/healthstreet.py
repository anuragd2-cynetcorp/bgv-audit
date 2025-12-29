"""
Provider extractor for HealthStreet invoices.
"""
import re
from typing import List
from .base import BaseProvider, ExtractedInvoice, ExtractedLineItem


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
        text = self._get_pdf_text(pdf_path)
        tables = self._get_pdf_tables(pdf_path)
        
        invoice_number_match = re.search(r'Invoice\s*[#:]?\s*([A-Z0-9\-]+)', text, re.IGNORECASE)
        invoice_number = invoice_number_match.group(1) if invoice_number_match else "UNKNOWN"
        
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
        # TODO: Implement based on HealthStreet's format
        return []
    
    def _extract_from_text(self, text: str) -> List[ExtractedLineItem]:
        """Extract line items from text."""
        return []

