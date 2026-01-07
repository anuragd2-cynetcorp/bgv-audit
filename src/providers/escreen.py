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
            
            # 3. Extract Line Items
            # Try normal text extraction first
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
        
        Args:
            lines: List of text lines to parse
            
        Returns:
            List of ExtractedLineItem objects
        """
        line_items = []
        
        for line in lines:
            line = line.strip()
            
            # Regex to capture the row structure:
            # Date | Middle Chunk (Desc + Name) | SSN | Chain ID | ... | Amount
            match = re.match(r'^(\d{1,2}/\d{1,2}/\d{4})\s+(.+?)\s+(\d{4})\s+(\d+)\s+.*?\$([\d,]+\.\d{2})$', line)
            
            if match:
                date_str = match.group(1)
                middle_chunk = match.group(2).strip()
                ssn = match.group(3)
                chain_id = match.group(4)
                amount_str = match.group(5)
                
                try:
                    amount = float(amount_str.replace(',', ''))
                except ValueError:
                    continue

                # --- IMPROVED NAME PARSING ---
                # We look for the Name at the END of the middle_chunk.
                # Format: "Lastname, Firstname" or "Lastname, Firstname Middle"
                name_match = re.search(r'([A-Za-z\-\']+, \s*[A-Za-z\-\']+(?: [A-Za-z\-\']+)?)$', middle_chunk)
                
                if name_match:
                    candidate_name = name_match.group(1).strip()
                    # Description is everything before the name match
                    description = middle_chunk[:name_match.start()].strip()
                else:
                    # Fallback: If strict regex fails, try splitting by double space
                    parts = re.split(r'\s{2,}', middle_chunk)
                    if len(parts) >= 2:
                        candidate_name = parts[-1]
                        description = " ".join(parts[:-1])
                    else:
                        # Last resort: assume it's a name if it has a comma, else description
                        if ',' in middle_chunk:
                            candidate_name = middle_chunk
                            description = "Unknown Service"
                        else:
                            candidate_name = "Unknown"
                            description = middle_chunk

                # Clean up description (remove trailing hyphens sometimes left by regex)
                description = description.rstrip(' -')

                # Determine ID (SSN or Chain ID)
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
        
        return line_items

