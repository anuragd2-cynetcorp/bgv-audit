"""
Provider extractor for Disa Global invoices.
"""
import re
import pdfplumber
from typing import List
from .base import BaseProvider, ExtractedInvoice, ExtractedLineItem
from src.logger import get_logger

logger = get_logger()


class DisaGlobalProvider(BaseProvider):
    """
    Extractor for Disa Global invoices.
    
    Format Characteristics:
    - Page 1: Invoice Summary (Invoice #, Total).
    - Pages 2-3: Category Summary (Skip these).
    - Page 4+: Detailed Case List in a Grid/Table format.
    - Table Columns: [Date, Order #, Subject, User, Order Content, Total]
    """
    
    def __init__(self):
        """Initialize the Disa Global provider."""
        super().__init__("Disa Global")
        self.identification_keywords = ["DISA Global Solutions", "Strongsville, OH", "Accounting.CLE@disa.com"]
    
    def identify(self, pdf_path: str) -> bool:
        """Check if this PDF belongs to Disa Global."""
        text = self._get_pdf_text(pdf_path)
        return "DISA Global Solutions" in text and "Strongsville" in text
    
    def extract(self, pdf_path: str) -> ExtractedInvoice:
        """
        Extract invoice data from Disa Global's PDF format.
        """
        invoice_number = "UNKNOWN"
        grand_total = 0.0
        line_items = []
        
        with pdfplumber.open(pdf_path) as pdf:
            # 1. Extract Header Info (Page 1)
            first_page_text = pdf.pages[0].extract_text()
            
            # Invoice Number
            # Pattern: 7-digit number followed by date (MM/DD/YYYY)
            inv_match = re.search(r'(\d{7})\s+\d{2}/\d{2}/\d{4}', first_page_text)
            if inv_match:
                invoice_number = inv_match.group(1)
            
            # Grand Total
            # Pattern: "BALANCE DUE" followed by dollar amount
            total_match = re.search(r'BALANCE DUE\s+\$([\d,]+\.\d{2})', first_page_text)
            if total_match:
                grand_total = float(total_match.group(1).replace(',', ''))

            # 2. Extract Line Items (Iterate all pages)
            # We are looking for the detailed table which usually starts on Page 4
            for page in pdf.pages:
                # Disa tables have vertical lines, so 'lines' strategy is best.
                # If that fails, 'text' strategy works for whitespace alignment.
                tables = page.extract_tables(table_settings={
                    "vertical_strategy": "lines", 
                    "horizontal_strategy": "lines",
                    "snap_tolerance": 3
                })
                
                # Fallback if lines aren't detected (sometimes headers don't have lines)
                if not tables:
                    tables = page.extract_tables(table_settings={
                        "vertical_strategy": "text",
                        "horizontal_strategy": "text"
                    })

                for table in tables:
                    for row in table:
                        # Clean row data (remove None and strip whitespace)
                        row = [cell.strip() if cell else "" for cell in row]
                        
                        # Filter out completely empty rows
                        if not any(row):
                            continue
                        
                        # We need a row with at least 6 columns
                        # [Date, Order #, Subject, User, Order Content, Total]
                        # But be flexible - sometimes columns might be merged or missing
                        if len(row) < 4:  # Minimum: Date, Order ID, something, Amount
                            continue
                            
                        # Check if this is a data row (First column looks like a date)
                        date_str = row[0]
                        if not date_str or not re.match(r'\d{1,2}/\d{1,2}/\d{4}', date_str):
                            continue
                        
                        # Normalize date format (ensure consistent format)
                        date_parts = date_str.split('/')
                        if len(date_parts) == 3:
                            month, day, year = date_parts
                            date_str = f"{month.zfill(2)}/{day.zfill(2)}/{year}"
                            
                        # Extract Fields with flexible column mapping
                        # Col 0: Date -> Service Date (already extracted)
                        # Col 1: Order # -> Candidate ID
                        # Col 2: Subject -> Candidate Name (stored in metadata)
                        # Col 3: User (stored in metadata)
                        # Col 4: Order Content -> Description
                        # Col 5: Total -> Amount
                        
                        # Order ID (required)
                        order_id = row[1] if len(row) > 1 else ""
                        if not order_id:
                            # Try to find order ID in other columns if column 1 is empty
                            for i, cell in enumerate(row[2:6], start=2):
                                if cell and re.match(r'^\d+$', cell):
                                    order_id = cell
                                    break
                        
                        if not order_id:
                            continue  # Skip if no order ID found
                        
                        # Extract candidate name from Subject column (column 2)
                        candidate_name = row[2] if len(row) > 2 and row[2] else order_id
                        # Use order ID as fallback if name is empty
                        if not candidate_name or not candidate_name.strip():
                            candidate_name = order_id
                        else:
                            candidate_name = candidate_name.strip()
                        
                        # Description: Extract from column 4 (Order Content)
                        # Handle multi-line descriptions and normalize
                        if len(row) > 4:
                            raw_desc = row[4].replace('\n', ' ').strip()
                        else:
                            # Fallback: try to find description in other columns
                            raw_desc = ""
                            for i, cell in enumerate(row[2:], start=2):
                                if cell and not re.match(r'^[\$]?[\d,]+\.\d{2}$', cell) and not re.match(r'^\d+$', cell):
                                    raw_desc = cell.replace('\n', ' ').strip()
                                    break
                        
                        # Normalize description (first meaningful words for fingerprinting)
                        if raw_desc:
                            desc_words = raw_desc.split()[:5]  # First 5 words sufficient
                            description = ' '.join(desc_words).strip()
                        else:
                            description = "Service"
                        
                        # Amount: Extract from last column (usually column 5)
                        amount = None
                        amount_str = None
                        
                        # Try column 5 first (standard position)
                        if len(row) > 5:
                            amount_str = row[5].replace('$', '').replace(',', '').strip()
                            try:
                                amount = float(amount_str)
                            except ValueError:
                                amount = None
                        
                        # Fallback: look for amount in any column (find last numeric value that looks like money)
                        if amount is None:
                            for i in range(len(row) - 1, -1, -1):  # Search backwards
                                cell = row[i]
                                if not cell:
                                    continue
                                # Try to extract amount from cell
                                amount_match = re.search(r'[\$]?([\d,]+\.\d{2})', str(cell))
                                if amount_match:
                                    amount_str = amount_match.group(1).replace(',', '')
                                    try:
                                        amount = float(amount_str)
                                        break
                                    except ValueError:
                                        continue
                        
                        # Skip if we couldn't extract amount
                        if amount is None:
                            continue
                            
                        # Extract metadata
                        subject = row[2] if len(row) > 2 else ""
                        user_ordered = row[3] if len(row) > 3 else ""
                        
                        # Create Line Item
                        item = ExtractedLineItem(
                            service_date=date_str,
                            candidate_id=order_id,
                            candidate_name=candidate_name,
                            amount=amount,
                            service_description=description,
                            metadata={
                                "user_ordered": user_ordered,
                                "subject": subject  # Store raw name in metadata for reference
                            }
                        )
                        line_items.append(item)
            
            # Check if extraction is complete by comparing sum with grand total
            # If no line items found, or if sum doesn't match grand total (and we have a grand total), try OCR fallback
            items_sum = sum(item.amount for item in line_items) if line_items else 0.0
            should_try_ocr = False
            
            if not line_items:
                should_try_ocr = True
                logger.info("No line items found with table extraction. Attempting OCR fallback for Disa Global invoice.")
            elif grand_total > 0.0 and abs(grand_total - items_sum) > 0.01:
                should_try_ocr = True
                logger.info(f"Table extraction found {len(line_items)} items with sum ${items_sum:.2f}, but grand total is ${grand_total:.2f}. Attempting OCR fallback for Disa Global invoice.")
            
            if should_try_ocr:
                try:
                    lines = self._get_text_lines(pdf_path, use_ocr=True)
                    ocr_line_items = self._parse_text_lines(lines)
                    ocr_sum = sum(item.amount for item in ocr_line_items) if ocr_line_items else 0.0
                    
                    # Use OCR results if they're better (more items or closer to grand total)
                    if not line_items or (grand_total > 0.0 and abs(grand_total - ocr_sum) < abs(grand_total - items_sum)):
                        line_items = ocr_line_items
                        logger.info(f"OCR extraction found {len(line_items)} line items with sum ${ocr_sum:.2f}.")
                    elif line_items:
                        logger.info(f"OCR extraction found {len(ocr_line_items)} items but table extraction had better match. Using table extraction results.")
                except Exception as e:
                    logger.error(f"OCR extraction failed: {str(e)}", exc_info=True)
                    # Continue with table extraction results if OCR fails

        if not line_items:
            raise ValueError("Could not extract line items. Format may have changed.")
            
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
        Parse text lines into line items using Disa Global-specific logic.
        This is a fallback when table extraction fails.
        
        Args:
            lines: List of text lines to parse
            
        Returns:
            List of ExtractedLineItem objects
        """
        # Disa Global primarily uses table extraction, so this is a minimal fallback
        # If OCR is needed, it would require understanding the text format
        # For now, return empty list to indicate table extraction is preferred
        return []