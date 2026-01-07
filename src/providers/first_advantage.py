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
            
            # If no line items found, try OCR fallback
            if not line_items:
                logger.info("No line items found with text extraction. Attempting OCR fallback for First Advantage invoice.")
                try:
                    lines = self._get_text_lines(pdf_path, use_ocr=True)
                    line_items = self._parse_text_lines(lines)
                    logger.info(f"OCR extraction found {len(line_items)} line items.")
                except Exception as e:
                    logger.error(f"OCR extraction failed: {str(e)}", exc_info=True)
                    # Continue to raise the original error if OCR also fails
        
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
            # Pattern: "Case ID: <id> <name> Ordered:"
            case_match = re.search(r'Case ID:\s*(\d+)\s+(.+?)\s+(?:Ordered:|$)', line)
            if case_match:
                current_case_id = case_match.group(1)
                # Optimized: Use Case ID as name (name not used for fingerprinting)
                current_candidate_name = current_case_id
                # Reset date, look for it in this line or subsequent lines
                current_service_date = None
                
                # Check if date is on the same line
                date_match = re.search(r'(\d{1,2}/\d{1,2}/\d{4})', line)
                if date_match:
                    current_service_date = date_match.group(1)
                continue

            # --- Capture Date if on subsequent line ---
            # If we have a case but no date yet, check if this line is just a date
            if current_case_id and not current_service_date:
                date_match = re.search(r'^\s*(\d{1,2}/\d{1,2}/\d{4})\s*$', line)
                if date_match:
                    current_service_date = date_match.group(1)
                    continue

            # --- Skip Headers/Noise ---
            if any(x in line for x in ["Package Products:", "Other Fees:", "Source Fees:", "Custom Package", "Qty Price Ext Price"]):
                continue
            
            # --- Extract Line Items ---
            # We only extract if we are inside a valid Case context
            if current_case_id:
                
                # Pattern A: Standard Line Item (Description | Qty | Unit Price | Ext Price)
                std_match = re.search(r'^(.+?)\s+(\d+)\s+\$([\d,]+\.\d{2})\s+\$([\d,]+\.\d{2})$', line)
                
                if std_match:
                    description = std_match.group(1).strip()
                    amount = float(std_match.group(4).replace(',', ''))
                    
                    # Normalize description (first meaningful words for fingerprinting)
                    desc_words = description.split()[:5]  # First 5 words sufficient
                    description = ' '.join(desc_words).strip()
                    
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
                
                # Pattern B: Source Fees / One-off items (Description | Ext Price)
                source_match = re.search(r'^(.+?)\s+\$([\d,]+\.\d{2})$', line)
                
                if source_match:
                    description = source_match.group(1).strip()
                    amount = float(source_match.group(2).replace(',', ''))
                    
                    # Filter out sub-totals or headers that might match this pattern
                    if "Total" in description or "Invoice" in description:
                        continue

                    # Normalize description (first meaningful words for fingerprinting)
                    desc_words = description.split()[:5]  # First 5 words sufficient
                    description = ' '.join(desc_words).strip()

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
    
