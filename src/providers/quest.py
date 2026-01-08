"""
Provider extractor for Quest invoices.
"""
import re
import pdfplumber
from typing import List, Optional
from .base import BaseProvider, ExtractedInvoice, ExtractedLineItem
from src.logger import get_logger

logger = get_logger()


class QuestProvider(BaseProvider):
    """
    Extractor for Quest Diagnostics invoices.
    
    Format Characteristics:
    - Header contains 'Invoice Number' and 'Amount Due'.
    - Data is grouped by Candidate (Patient).
    - A Candidate line starts with a Date (MM/DD/YYYY).
    - Service lines follow the Candidate line.
    - Service lines always contain a 7-digit CPT/Service code and a '$' amount.
    """
    
    def __init__(self):
        """Initialize the Quest provider with specific identification keywords."""
        super().__init__("Quest Diagnostics")
        
    def identify(self, pdf_path: str) -> bool:
        """
        Check for Quest logo text or specific address patterns.
        
        Args:
            pdf_path: Path to the PDF file.
            
        Returns:
            True if the PDF contains Quest identifiers.
        """
        text = self._get_pdf_text(pdf_path)
        # Check for common Quest identifiers in the raw text
        return "QUEST DIAGNOSTICS" in text.upper() or "QUESTDIAGNOSTICS.COM" in text.upper()

    def extract(self, pdf_path: str) -> ExtractedInvoice:
        """
        Extract invoice data from Quest's PDF format using a state machine approach.
        
        Args:
            pdf_path: Path to the PDF file.
            
        Returns:
            ExtractedInvoice object containing metadata and line items.
            
        Raises:
            ValueError: If critical information (Total, Line Items) cannot be found.
        """
        invoice_number = BaseProvider.generate_unknown_invoice_number()
        grand_total = 0.0
        line_items = []
        
        # State machine variables to hold context across lines
        current_date = None
        current_candidate_id = None
        current_candidate_name = None
        
        with pdfplumber.open(pdf_path) as pdf:
            # 1. Extract Header Info (usually found on Page 1)
            first_page_text = pdf.pages[0].extract_text()
            
            # Extract Invoice Number
            # Pattern: "<client> <code> <invoice_number> <date>" (Client | Code | Invoice | Date)
            # We look for the 10-digit number starting with 9 (common for Quest)
            inv_match = re.search(r'\d+\s+NDA\s+(\d+)\s+\d{2}/\d{2}/\d{4}', first_page_text)
            if inv_match:
                invoice_number = inv_match.group(1)
            
            # Extract Grand Total
            # Pattern: "Amount Due: ... $<amount>"
            total_match = re.search(r'Amount Due:[\s\S]*?\$([\d,]+\.\d{2})', first_page_text)
            if total_match:
                grand_total = float(total_match.group(1).replace(',', ''))

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
                logger.info("No line items found with text extraction. Attempting OCR fallback for Quest invoice.")
            elif grand_total > 0.0 and abs(grand_total - items_sum) > 0.01:
                should_try_ocr = True
                logger.info(f"Text extraction found {len(line_items)} items with sum ${items_sum:.2f}, but grand total is ${grand_total:.2f}. Attempting OCR fallback for Quest invoice.")
            
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
        
        # Validation: Ensure we actually extracted data
        if not line_items:
            # If regex failed, it might be a scanned image or a changed format
            raise ValueError("Could not extract line items from invoice. Format may have changed or file is scanned.")
        
        if grand_total == 0.0:
             raise ValueError("Could not extract Grand Total from invoice.")

        return ExtractedInvoice(
            invoice_number=invoice_number,
            provider_name=self.name,
            line_items=line_items,
            grand_total=grand_total
        )
    
    def _parse_text_lines(self, lines: List[str]) -> List[ExtractedLineItem]:
        """
        Parse text lines into line items using Quest-specific logic.
        Uses state machine to track candidate context and extract service lines.
        
        Args:
            lines: List of text lines to parse
            
        Returns:
            List of ExtractedLineItem objects
        """
        line_items = []
        
        # State machine variables to hold context across lines
        current_date = None
        current_candidate_id = None
        current_candidate_name = None
        
        for line in lines:
            line = line.strip()
            
            # --- Pattern A: New Candidate Line ---
            # Regex: Date | Specimen | Patient ID | Name
            # Format: "<date> <specimen_id> <patient_id> <name>"
            candidate_match = re.match(r'^(\d{2}/\d{2}/\d{4})\s+(\d+)\s+([A-Z0-9]+)\s+(.*)', line)
            
            if candidate_match:
                # Update State
                current_date = candidate_match.group(1)
                current_candidate_id = candidate_match.group(3)
                # Optimized: Use ID as name (name not used for fingerprinting)
                current_candidate_name = current_candidate_id
                continue
                
            # --- Pattern B: Service Line ---
            # Regex: Description | 7-digit Code | Amount
            # Format: "<description> <code> $<amount>"
            # We exclude "PATIENT TOTAL" explicitly as it is a sub-sum line
            
            if "PATIENT TOTAL" in line:
                continue

            # Look for 7 digit code followed by price at end of line
            service_match = re.search(r'(?P<desc>.+?)\s+(?P<code>\d{7})\s+\$(?P<amount>[\d,]+\.\d{2})$', line)
            
            # We only extract if we have a valid context (Candidate ID and Date)
            if service_match and current_candidate_id and current_date:
                description = service_match.group('desc').strip()
                amount = float(service_match.group('amount').replace(',', ''))
                
                # Normalize description (first meaningful words for fingerprinting)
                desc_words = description.split()[:5]  # First 5 words sufficient
                description = ' '.join(desc_words).strip()
                
                # Final validation before adding
                if not description:
                    continue

                # Create the standardized line item
                item = ExtractedLineItem(
                    candidate_name=current_candidate_name or "Unknown",
                    candidate_id=current_candidate_id,
                    amount=amount,
                    service_date=current_date,
                    service_description=description,
                    metadata={
                        "service_code": service_match.group('code')
                    }
                )
                line_items.append(item)
        
        return line_items
    


