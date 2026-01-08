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
            
            # Invoice Number - try multiple patterns
            invoice_patterns = [
                r'Invoice\s*#\s*([A-Z0-9\-]+)',
                r'Invoice[:\s]+([A-Z0-9\-]+)',
                r'INVOICE[:\s]+([A-Z0-9\-]+)',
                r'Invoice\s+Number[:\s]+([A-Z0-9\-]+)',
            ]
            for pattern in invoice_patterns:
                invoice_match = re.search(pattern, first_page_text, re.IGNORECASE)
                if invoice_match:
                    invoice_number = invoice_match.group(1)
                    break
            
            # Grand Total - check all pages (may be on last page for multi-page invoices)
            # Try multiple patterns
            total_patterns = [
                r'(?:Total Invoice|Balance Due|Total|Amount Due)\s*\$?([\d,]+\.?\d*)',
                r'\$\s*([\d,]+\.?\d*)\s*(?:Total|Due|Balance)',
                r'Total[:\s]+\$?([\d,]+\.?\d*)',
            ]
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                for pattern in total_patterns:
                    total_match = re.search(pattern, page_text, re.IGNORECASE)
                    if total_match:
                        # Use the last found total (typically on last page)
                        try:
                            grand_total = float(total_match.group(1).replace(',', ''))
                            break
                        except ValueError:
                            continue
                if grand_total > 0.0:
                    break
        
        # 2. Extract Line Items
        # Try table extraction first (some HealthStreet PDFs use tables)
        line_items = self._parse_tables(pdf_path)
        
        # If table extraction didn't work, try text extraction
        if not line_items:
            lines = self._get_text_lines(pdf_path, use_ocr=False)
            line_items = self._parse_text_lines(lines)
        
        # Check if extraction is complete by comparing sum with grand total
        items_sum = sum(item.amount for item in line_items) if line_items else 0.0
        should_try_ocr = False
        
        if not line_items:
            should_try_ocr = True
            logger.info("No line items found with text/table extraction. Attempting OCR fallback for HealthStreet invoice.")
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
        # Try multiple patterns to handle variations
        data_patterns = [
            # Pattern 1: Date Name Service $Amount (with dollar sign)
            re.compile(r'^(\d{1,2}/\d{1,2}/\d{4})\s+(.+?)\s+\$?(\d+\.\d{2})\s*$'),
            # Pattern 2: Date Name Service Amount (2 decimals, no dollar)
            re.compile(r'^(\d{1,2}/\d{1,2}/\d{4})\s+(.+?)\s+(\d+\.\d{2})\s*$'),
            # Pattern 3: Date Name Service Amount (flexible decimals)
            re.compile(r'^(\d{1,2}/\d{1,2}/\d{4})\s+(.+?)\s+(\d+\.?\d*)\s*$'),
            # Pattern 4: Date Name Amount (amount at very end, might have spaces)
            re.compile(r'^(\d{1,2}/\d{1,2}/\d{4})\s+(.+?)\s+(\d+\.?\d*)$'),
        ]
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Skip header/footer lines
            if any(skip in line.lower() for skip in ['invoice', 'total', 'balance', 'payment', 'due date', 'page', 'date name service', 'cynet', 'health street']):
                continue
            
            # Try to match data line with multiple patterns
            match = None
            for pattern in data_patterns:
                match = pattern.match(line)
                if match:
                    break
            
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
                # But we need to be smarter - the amount might be separated by spaces
                # Try to find where the amount starts by looking for number patterns
                
                # Split by whitespace
                words = middle_part.split()
                
                # Try to identify the name (typically first 2-3 capitalized words)
                # and the service description (rest)
                if len(words) >= 3:
                    # Check if last few words look like they might be part of amount
                    # (they shouldn't be, but let's be safe)
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
                
                # Clean up - remove any trailing numbers that might have been captured
                # (sometimes the regex might capture part of the amount in the middle)
                candidate_name = candidate_name.strip()
                service_description = service_description.strip()
                
                # If service_description looks like a number, it's probably wrong
                try:
                    float(service_description)
                    # If it's a number, it's probably part of the amount, not service
                    service_description = "Service"
                except ValueError:
                    pass
                
                # Generate candidate_id from name (no SSN in HealthStreet format)
                # Use normalized name as ID
                candidate_id = candidate_name.upper().replace(' ', '')
                
                # Normalize description
                service_description = normalize_description(service_description)
                
                item = ExtractedLineItem(
                    candidate_name=candidate_name,  # Use actual name for display
                    candidate_id=candidate_id,
                    amount=amount,
                    service_date=service_date,
                    service_description=service_description,
                    metadata={}
                )
                line_items.append(item)
        
        return line_items
    
    def _parse_tables(self, pdf_path: str) -> List[ExtractedLineItem]:
        """
        Try to extract line items from tables in the PDF.
        Some HealthStreet PDFs may have table-based formats.
        
        Args:
            pdf_path: Path to the PDF file
            
        Returns:
            List of ExtractedLineItem objects, or empty list if no tables found
        """
        line_items = []
        
        try:
            tables = self._get_pdf_tables(pdf_path)
            if not tables:
                return line_items
            
            # Look for tables with date, name, service, amount columns
            for table in tables:
                if not table or len(table) < 2:
                    continue
                
                # Try to find header row
                header_row = None
                for i, row in enumerate(table[:3]):  # Check first 3 rows for header
                    if row and any(cell and ('date' in str(cell).lower() or 'name' in str(cell).lower() or 'service' in str(cell).lower()) for cell in row):
                        header_row = i
                        break
                
                # If no header found, assume first row is header
                if header_row is None:
                    header_row = 0
                
                # Process data rows
                for row in table[header_row + 1:]:
                    if not row or len(row) < 3:
                        continue
                    
                    # Clean row data
                    row = [str(cell).strip() if cell else "" for cell in row]
                    
                    # Skip empty rows
                    if not any(row):
                        continue
                    
                    # Try to find date in first few columns
                    date_match = None
                    date_col = None
                    for col_idx, cell in enumerate(row[:5]):
                        if cell:
                            date_match = re.search(r'(\d{1,2}/\d{1,2}/\d{4})', cell)
                            if date_match:
                                date_col = col_idx
                                break
                    
                    if not date_match:
                        continue
                    
                    service_date = date_match.group(1)
                    
                    # Find amount (usually in last column or second to last)
                    amount = None
                    amount_col = None
                    for col_idx in range(len(row) - 1, max(0, len(row) - 3), -1):
                        cell = row[col_idx]
                        if cell:
                            # Try to extract number
                            amount_match = re.search(r'(\d+\.\d{2})', cell.replace(',', ''))
                            if amount_match:
                                try:
                                    amount = float(amount_match.group(1))
                                    amount_col = col_idx
                                    break
                                except ValueError:
                                    continue
                    
                    if amount is None:
                        continue
                    
                    # Extract name and service from columns between date and amount
                    if date_col is not None and amount_col is not None and date_col < amount_col:
                        middle_cols = row[date_col + 1:amount_col]
                    else:
                        # Fallback: use columns between first and last
                        middle_cols = row[1:-1] if len(row) > 2 else row[1:]
                    middle_text = ' '.join([c for c in middle_cols if c]).strip()
                    
                    if not middle_text:
                        continue
                    
                    # Parse name and service (first 2 words are name, rest is service)
                    words = middle_text.split()
                    if len(words) >= 2:
                        candidate_name = ' '.join(words[:2])
                        service_description = ' '.join(words[2:]) if len(words) > 2 else "Service"
                    else:
                        candidate_name = middle_text
                        service_description = "Service"
                    
                    # Generate candidate_id
                    candidate_id = candidate_name.upper().replace(' ', '')
                    
                    # Normalize description
                    service_description = normalize_description(service_description)
                    
                    item = ExtractedLineItem(
                        candidate_name=candidate_name,
                        candidate_id=candidate_id,
                        amount=amount,
                        service_date=service_date,
                        service_description=service_description,
                        metadata={}
                    )
                    line_items.append(item)
        
        except Exception as e:
            logger.debug(f"Table extraction failed: {str(e)}")
        
        return line_items

