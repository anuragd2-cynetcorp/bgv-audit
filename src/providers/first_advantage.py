"""
Provider extractor for First Advantage invoices.
"""
import re
from typing import List
from .base import BaseProvider, ExtractedInvoice, ExtractedLineItem


class FirstAdvantageProvider(BaseProvider):
    """
    Extractor for First Advantage invoices.
    """
    
    def __init__(self):
        super().__init__("First Advantage")
        self.identification_keywords = [
            "First Advantage",
            "FIRST ADVANTAGE",
            "firstadvantage.com"
        ]
    
    def identify(self, pdf_path: str) -> bool:
        """Check if this PDF belongs to First Advantage."""
        text = self._get_pdf_text(pdf_path)
        text_upper = text.upper()
        for keyword in self.identification_keywords:
            if keyword.upper() in text_upper:
                return True
        return False
    
    def extract(self, pdf_path: str) -> ExtractedInvoice:
        """Extract invoice data from First Advantage's PDF format."""
        text = self._get_pdf_text(pdf_path)
        tables = self._get_pdf_tables(pdf_path)
        
        invoice_number_match = re.search(r'Invoice\s*[#:]?\s*([A-Z0-9\-]+)', text, re.IGNORECASE)
        invoice_number = invoice_number_match.group(1) if invoice_number_match else BaseProvider.generate_unknown_invoice_number()
        
        total_patterns = [
            r'Grand\s*Total[:\s]*\$?([\d,]+\.?\d*)',
            r'Total[:\s]*\$?([\d,]+\.?\d*)',
        ]
        grand_total = None
        for pattern in total_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                grand_total_str = match.group(1).replace(',', '')
                try:
                    grand_total = float(grand_total_str)
                    break
                except ValueError:
                    continue
        
        if grand_total is None:
            raise ValueError("Could not extract grand total from invoice")
        
        line_items = []
        if tables:
            line_items = self._extract_from_tables(tables)
        if not line_items:
            line_items = self._extract_from_text(text)
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
        line_items = []
        for table in tables:
            if not table or len(table) < 2:
                continue
            # TODO: Implement table extraction based on First Advantage's format
        return line_items
    
    def _extract_from_text(self, text: str) -> List[ExtractedLineItem]:
        """Extract line items from text."""
        return []

