"""
Provider extractor for Quest invoices.
"""
import re
from typing import List
from .base_provider import BaseProvider, ExtractedInvoice, ExtractedLineItem


class QuestProvider(BaseProvider):
    """Extractor for Quest invoices."""
    
    def __init__(self):
        super().__init__("Quest")
        self.identification_keywords = ["Quest", "QUEST", "questdiagnostics.com"]
    
    def identify(self, pdf_path: str) -> bool:
        """Check if this PDF belongs to Quest."""
        text = self._get_pdf_text(pdf_path)
        text_upper = text.upper()
        return any(kw.upper() in text_upper for kw in self.identification_keywords)
    
    def extract(self, pdf_path: str) -> ExtractedInvoice:
        """Extract invoice data from Quest's PDF format."""
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
        # TODO: Implement based on Quest's format
        return []
    
    def _extract_from_text(self, text: str) -> List[ExtractedLineItem]:
        """Extract line items from text."""
        return []

