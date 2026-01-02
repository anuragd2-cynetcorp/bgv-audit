"""
Provider extractor for Disa Global invoices.
"""
import re
from typing import List
from .base import BaseProvider, ExtractedInvoice, ExtractedLineItem


class DisaGlobalProvider(BaseProvider):
    """
    Extractor for Disa Global invoices.
    """
    
    def __init__(self):
        super().__init__("Disa Global")
        # Define provider-specific keywords for identification
        self.identification_keywords = [
            "Disa Global",
            "DISA GLOBAL",
            "disa-global.com"
        ]
    
    def identify(self, pdf_path: str) -> bool:
        """
        Check if this PDF belongs to Disa Global.
        """
        text = self._get_pdf_text(pdf_path)
        text_upper = text.upper()
        
        # Check for identification keywords
        for keyword in self.identification_keywords:
            if keyword.upper() in text_upper:
                return True
        
        return False
    
    def extract(self, pdf_path: str) -> ExtractedInvoice:
        """
        Extract invoice data from Disa Global's PDF format.
        TODO: Customize this method based on Disa Global's actual invoice layout.
        """
        text = self._get_pdf_text(pdf_path)
        tables = self._get_pdf_tables(pdf_path)
        
        # Extract Invoice Number
        invoice_number_match = re.search(r'Invoice\s*[#:]?\s*([A-Z0-9\-]+)', text, re.IGNORECASE)
        invoice_number = invoice_number_match.group(1) if invoice_number_match else BaseProvider.generate_unknown_invoice_number()
        
        # Extract Grand Total
        total_patterns = [
            r'Grand\s*Total[:\s]*\$?([\d,]+\.?\d*)',
            r'Total[:\s]*\$?([\d,]+\.?\d*)',
            r'Amount\s*Due[:\s]*\$?([\d,]+\.?\d*)'
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
        
        # Extract Line Items
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
            
            header_row = table[0]
            
            # Identify column indices - customize based on Disa Global's format
            candidate_name_idx = None
            candidate_id_idx = None
            service_desc_idx = None
            service_date_idx = None
            amount_idx = None
            
            for idx, header in enumerate(header_row):
                header_lower = str(header).lower() if header else ""
                if 'candidate' in header_lower and 'name' in header_lower:
                    candidate_name_idx = idx
                elif 'candidate' in header_lower and ('id' in header_lower or 'identifier' in header_lower):
                    candidate_id_idx = idx
                elif 'service' in header_lower or 'description' in header_lower:
                    service_desc_idx = idx
                elif 'date' in header_lower or 'service date' in header_lower:
                    service_date_idx = idx
                elif 'cost' in header_lower or 'amount' in header_lower or 'price' in header_lower:
                    amount_idx = idx
            
            # Extract data rows
            for row in table[1:]:
                if len(row) < max(filter(None, [candidate_name_idx, candidate_id_idx, service_desc_idx, amount_idx]), default=0):
                    continue
                
                try:
                    candidate_name = str(row[candidate_name_idx]).strip() if candidate_name_idx is not None else ""
                    candidate_id = str(row[candidate_id_idx]).strip() if candidate_id_idx is not None else ""
                    service_desc = str(row[service_desc_idx]).strip() if service_desc_idx is not None else ""
                    service_date = str(row[service_date_idx]).strip() if service_date_idx is not None else ""
                    amount_str = str(row[amount_idx]).strip() if amount_idx is not None else ""
                    
                    amount_str = re.sub(r'[^\d.]', '', amount_str)
                    if not amount_str:
                        continue
                    
                    amount = float(amount_str)
                    
                    if not candidate_id or not service_desc:
                        continue
                    
                    # If no service_date found, use empty string (will need to be handled by normalization)
                    if not service_date:
                        service_date = ""
                    
                    line_items.append(ExtractedLineItem(
                        service_date=service_date,
                        candidate_id=candidate_id,
                        candidate_name=candidate_name,
                        amount=amount,
                        service_description=service_desc
                    ))
                except (ValueError, IndexError):
                    continue
        
        return line_items
    
    def _extract_from_text(self, text: str) -> List[ExtractedLineItem]:
        """Extract line items from text if tables are not available."""
        line_items = []
        # TODO: Implement text-based extraction if needed
        return line_items

