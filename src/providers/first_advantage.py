"""
Provider extractor for First Advantage invoices.
"""
import re
import pdfplumber
from typing import List
from .base import BaseProvider, ExtractedInvoice, ExtractedLineItem
from src.logger import get_logger

logger = get_logger()


class FirstAdvantageProvider(BaseProvider):
    """
    Extractor for First Advantage invoices.
    
    Format Characteristics:
    - Header (Page 1) contains Invoice Number and Invoice Amount.
    - Footer (Last Page) contains "Background Services Total".
    - Data is grouped by "Case ID".
    - Structure:
      [Blue Header: Case ID | Name | Ordered Date]
      [Sub-headers: Package Products, Other Fees, Source Fees]
      [Line Items: Description | Qty | Unit Price | Ext Price]
    """
    
    def __init__(self):
        """Initialize the First Advantage provider."""
        super().__init__("First Advantage")
        self.identification_keywords = [
            "First Advantage",
            "Corporate Screening Services",
            "Background Services"
        ]
    
    def identify(self, pdf_path: str) -> bool:
        """Check if this PDF belongs to First Advantage."""
        text = self._get_pdf_text(pdf_path)
        return any(kw.upper() in text.upper() for kw in self.identification_keywords)
    
    def extract(self, pdf_path: str) -> ExtractedInvoice:
        """
        Extract invoice data from First Advantage's PDF format.
        """
        invoice_number = BaseProvider.generate_unknown_invoice_number()
        grand_total = 0.0
        line_items = []
        
        # State variables to hold context while iterating lines
        current_case_id = None
        current_candidate_name = None
        current_service_date = None
        
        with pdfplumber.open(pdf_path) as pdf:
            # 1. Extract Header Info (Page 1)
            first_page_text = pdf.pages[0].extract_text()
            
            # Invoice Number
            # Pattern: "Invoice Number <number>"
            inv_match = re.search(r'Invoice Number\s+([A-Z0-9\-]+)', first_page_text)
            if inv_match:
                invoice_number = inv_match.group(1)
            
            # Invoice Amount (Grand Total from Page 1 is usually reliable)
            # Pattern: "Invoice Amount $<amount>"
            total_match = re.search(r'Invoice Amount\s+\$([\d,]+\.\d{2})', first_page_text)
            if total_match:
                grand_total = float(total_match.group(1).replace(',', ''))
            
            # If not found on page 1, check last page footer
            if grand_total == 0.0:
                last_page_text = pdf.pages[-1].extract_text()
                footer_match = re.search(r'Background Services Total:\s+\$([\d,]+\.\d{2})', last_page_text)
                if footer_match:
                    grand_total = float(footer_match.group(1).replace(',', ''))

            # 2. Extract Line Items
            # Try normal text extraction first
            lines = self._get_text_lines(pdf_path, use_ocr=False)
            line_items = self._parse_text_lines(lines)
            
            # Check if extraction is complete by comparing sum with grand total
            # If no line items found, or if sum doesn't match grand total (and we have a grand total), try OCR fallback
            items_sum = sum(item.amount for item in line_items) if line_items else 0.0
            should_try_ocr = False
            
            if not line_items:
                should_try_ocr = True
                logger.info("No line items found with text extraction. Attempting OCR fallback for First Advantage invoice.")
            elif grand_total > 0.0 and abs(grand_total - items_sum) > 0.01:
                should_try_ocr = True
                logger.info(f"Text extraction found {len(line_items)} items with sum ${items_sum:.2f}, but grand total is ${grand_total:.2f}. Attempting OCR fallback for First Advantage invoice.")
            
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
                        logger.info(f"OCR extraction found {len(ocr_line_items)} items but text extraction had better match. Using text extraction results.")
                except Exception as e:
                    logger.error(f"OCR extraction failed: {str(e)}", exc_info=True)
                    # Continue with text extraction results if OCR fails
        
        if not line_items:
            raise ValueError("Could not extract line items. Format may have changed.")
            
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
        Parse text lines into line items using First Advantage-specific logic.
        Uses state machine to track case context and extract line items.
        
        Args:
            lines: List of text lines to parse
            
        Returns:
            List of ExtractedLineItem objects
        """
        line_items = []
        
        # State variables to hold context while iterating lines
        current_case_id = None
        current_candidate_name = None
        current_service_date = None
        
        for line in lines:
            line = line.strip()
            
            # --- State Change: New Case Header ---
            # Pattern 1: "Case ID: <id> <name> Ordered: <date> <amount>" (with or without pipes)
            # More flexible pattern to handle different formats
            case_match = re.search(r'Case ID[:]?\s*(\d+)\s+', line, re.IGNORECASE)
            if case_match:
                current_case_id = case_match.group(1)
                # Try to extract name from the line after Case ID
                after_case = line[case_match.end():].strip()
                # Look for name pattern (2-3 capitalized words)
                # Remove common suffixes like "Ordered", "Date", etc.
                name_match = re.search(r'([A-Z][a-z]+\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)', after_case)
                if name_match:
                    name = name_match.group(1).strip()
                    # Clean up common suffixes
                    name = re.sub(r'\s+Ordered.*$', '', name, flags=re.IGNORECASE)
                    name = re.sub(r'\s+Date.*$', '', name, flags=re.IGNORECASE)
                    current_candidate_name = name.strip()
                else:
                    # Fallback to Case ID if no name found
                    current_candidate_name = current_case_id
                # Reset date, look for it in this line or subsequent lines
                current_service_date = None
                
                # Check if date is on the same line (more flexible pattern)
                date_match = re.search(r'(\d{1,2}/\d{1,2}/\d{4})', line)
                if date_match:
                    date_str = date_match.group(1)
                    # Normalize date format (ensure consistent format)
                    date_parts = date_str.split('/')
                    if len(date_parts) == 3:
                        month, day, year = date_parts
                        current_service_date = f"{month.zfill(2)}/{day.zfill(2)}/{year}"
                continue

            # --- Capture Date if on subsequent line ---
            # If we have a case but no date yet, check if this line is just a date
            if current_case_id and not current_service_date:
                date_match = re.search(r'^\s*(\d{1,2}/\d{1,2}/\d{4})\s*$', line)
                if date_match:
                    date_str = date_match.group(1)
                    # Normalize date format
                    date_parts = date_str.split('/')
                    if len(date_parts) == 3:
                        month, day, year = date_parts
                        current_service_date = f"{month.zfill(2)}/{day.zfill(2)}/{year}"
                    continue

            # --- Skip Headers/Noise ---
            # More comprehensive list of headers to skip
            skip_keywords = [
                "Package Products:", "Other Fees:", "Source Fees:",
                "Custom Package", "Qty Price Ext Price",
                "Additional Products:", "Products:", "Background Services",
                "Ordered By:", "Background Services Total"
            ]
            if any(x in line for x in skip_keywords):
                continue
            
            # --- Extract Line Items ---
            # We only extract if we are inside a valid Case context
            if current_case_id:
                
                # Pattern A: Standard Line Item (Description | Qty | Unit Price | Ext Price)
                # More flexible - handle optional $ signs and spacing variations
                std_match = re.search(r'^(.+?)\s+(\d+)\s+\$?([\d,]+\.\d{2})\s+\$?([\d,]+\.\d{2})\s*$', line)
                
                if std_match:
                    description = std_match.group(1).strip()
                    try:
                        amount = float(std_match.group(4).replace(',', ''))
                    except ValueError:
                        amount = None
                    
                    if amount is not None:
                        # Normalize description (first meaningful words for fingerprinting)
                        desc_words = description.split()[:5]  # First 5 words sufficient
                        description = ' '.join(desc_words).strip()
                        
                        # Filter out empty descriptions or subtotal lines
                        if not description or description.lower() in ['subtotal', 'total', '']:
                            continue
                        
                        item = ExtractedLineItem(
                            service_date=current_service_date or "",
                            candidate_id=current_case_id,
                            candidate_name=current_candidate_name,
                            amount=amount,
                            service_description=description,
                            metadata={
                                "quantity": std_match.group(2),
                                "unit_price": std_match.group(3)
                            }
                        )
                        line_items.append(item)
                        continue
                
                # Pattern B: Source Fees / One-off items
                # Handle multi-column format: "Description | Name | Location | Amount"
                # Also handle simple format: "Description | Amount"
                
                # First try multi-column source fee pattern (with pipes)
                source_multi_match = re.search(r'^(.+?)\s*\|\s*.+?\s+\$?([\d,]+\.\d{2})\s*$', line)
                if source_multi_match:
                    description = source_multi_match.group(1).strip()
                    try:
                        amount = float(source_multi_match.group(2).replace(',', ''))
                    except ValueError:
                        amount = None
                    
                    if amount is not None:
                        # Filter out sub-totals or headers
                        if any(x in description.upper() for x in ["TOTAL", "INVOICE", "SUBtotal"]):
                            continue

                        # Normalize description (first meaningful words for fingerprinting)
                        desc_words = description.split()[:5]  # First 5 words sufficient
                        description = ' '.join(desc_words).strip()
                        
                        if description:  # Only add if we have a description
                            item = ExtractedLineItem(
                                service_date=current_service_date or "",
                                candidate_id=current_case_id,
                                candidate_name=current_candidate_name,
                                amount=amount,
                                service_description=description,
                                metadata={
                                    "type": "Source Fee/Other"
                                }
                            )
                            line_items.append(item)
                            continue
                
                # Pattern C: Simple Source Fees (Description | Ext Price) - no pipes
                source_match = re.search(r'^(.+?)\s+\$?([\d,]+\.\d{2})\s*$', line)
                
                if source_match:
                    description = source_match.group(1).strip()
                    try:
                        amount = float(source_match.group(2).replace(',', ''))
                    except ValueError:
                        amount = None
                    
                    if amount is not None:
                        # Filter out sub-totals or headers that might match this pattern
                        if any(x in description.upper() for x in ["TOTAL", "INVOICE", "SUBtotal", "BACKGROUND SERVICES"]):
                            continue
                        
                        # Skip if it looks like a table row with multiple columns (has numbers but not quantity/price format)
                        # Check if description is too short or contains numbers (might be part of table structure)
                        if len(description) < 3:
                            continue

                        # Normalize description (first meaningful words for fingerprinting)
                        desc_words = description.split()[:5]  # First 5 words sufficient
                        description = ' '.join(desc_words).strip()
                        
                        if description:  # Only add if we have a description
                            item = ExtractedLineItem(
                                service_date=current_service_date or "",
                                candidate_id=current_case_id,
                                candidate_name=current_candidate_name,
                                amount=amount,
                                service_description=description,
                                metadata={
                                    "type": "Source Fee/Other"
                                }
                            )
                            line_items.append(item)
        
        return line_items
    
