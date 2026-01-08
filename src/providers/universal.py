"""
Provider extractor for Universal invoices.
"""
import re
import pdfplumber
from typing import List
from .base import BaseProvider, ExtractedInvoice, ExtractedLineItem
from src.logger import get_logger

logger = get_logger()


class UniversalProvider(BaseProvider):
    """
    Extractor for Universal invoices.
    
    Format Characteristics:
    - Hierarchical structure:
      - Header Line: Date | Candidate Name - (Order #)
      - Item Lines: Description | Amount
      - Subtotal Line: Subtotal for Order # | Amount
    - Grand Total is at the very end of the document.
    """
    
    def __init__(self):
        """Initialize the Universal provider."""
        super().__init__("Universal")
        # Keywords to identify this specific format
        self.identification_keywords = ["Candidate name - order number", "Billing Code", "Item Total"]
    
    def identify(self, pdf_path: str) -> bool:
        """Check if this PDF belongs to Universal based on column headers."""
        text = self._get_pdf_text(pdf_path)
        # The word "Universal" might not be text-searchable, so we look for the unique column headers
        return "Candidate name - order number" in text and "Item Total" in text
    
    def extract(self, pdf_path: str) -> ExtractedInvoice:
        """
        Extract invoice data from Universal's PDF format using a State Machine.
        """
        invoice_number = BaseProvider.generate_unknown_invoice_number()  # Universal invoices in this format often lack a top-level invoice #
        grand_total = 0.0
        line_items = []
        
        with pdfplumber.open(pdf_path) as pdf:
            # 1. Attempt to find Invoice Number (if it exists on page 1)
            first_page_text = pdf.pages[0].extract_text()
            inv_match = re.search(r'Invoice\s*#?\s*[:.]?\s*([A-Z0-9\-]+)', first_page_text, re.IGNORECASE)
            if inv_match:
                invoice_number = inv_match.group(1)

            # 2. Extract Grand Total (usually last page)
            last_page_text = pdf.pages[-1].extract_text()
            total_match = re.search(r'Invoice Total\s+\$([\d,]+\.\d{2})', last_page_text)
            if total_match:
                grand_total = float(total_match.group(1).replace(',', ''))
            
            # 3. Extract Line Items
            # Try normal text extraction first
            lines = self._get_text_lines(pdf_path, use_ocr=False)
            line_items = self._parse_text_lines(lines)
            
            # Check if extraction is complete by comparing sum with grand total
            # If no line items found, or if sum doesn't match grand total (and we have a grand total), try OCR fallback
            items_sum = sum(item.amount for item in line_items) if line_items else 0.0
            should_try_ocr = False
            
            if not line_items:
                should_try_ocr = True
                logger.info("No line items found with text extraction. Attempting OCR fallback for Universal invoice.")
            elif grand_total > 0.0 and abs(grand_total - items_sum) > 0.01:
                should_try_ocr = True
                logger.info(f"Text extraction found {len(line_items)} items with sum ${items_sum:.2f}, but grand total is ${grand_total:.2f}. Attempting OCR fallback for Universal invoice.")
            
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
        Parse text lines into line items using Universal-specific logic.
        Uses state machine to track order context.
        
        Args:
            lines: List of text lines to parse
            
        Returns:
            List of ExtractedLineItem objects
        """
        line_items = []
        
        # State variables
        current_date = None
        current_candidate_name = None
        current_order_id = None
        
        for line in lines:
            line = line.strip()
            
            # --- Check for Candidate Header ---
            # Pattern: "<date> <name> - (Order # <id>)"
            header_match = re.match(r'^(\d{1,2}/\d{1,2}/\d{4})\s+(.+?)\s+-\s+\(Order\s+#\s+(\d+)\)', line)
            if header_match:
                current_date = header_match.group(1)
                current_order_id = header_match.group(3)
                # Extract actual name from group(2)
                candidate_name = header_match.group(2).strip()
                # Use actual name if available, otherwise use order ID
                current_candidate_name = candidate_name if candidate_name else current_order_id
                continue

            # --- Check for Subtotal Line (Skip) ---
            if line.startswith("Subtotal for Order"):
                continue
                
            # --- Check for Table Headers (Skip) ---
            if "Candidate name - order number" in line:
                continue

            # --- Check for Line Item ---
            # Pattern: Description followed by Amount at the end
            item_match = re.match(r'^(.+?)\s+\$([\d,]+\.\d{2})$', line)
            
            if item_match and current_order_id:
                description = item_match.group(1).strip()
                amount_str = item_match.group(2)
                
                try:
                    amount = float(amount_str.replace(',', ''))
                except ValueError:
                    continue
                    
                # Filter out lines that might be headers or noise
                if description.lower() == "item total":
                    continue

                # Normalize description (first meaningful words for fingerprinting)
                desc_words = description.split()[:5]  # First 5 words sufficient
                description = ' '.join(desc_words).strip()

                # Create Line Item
                item = ExtractedLineItem(
                    service_date=current_date,
                    candidate_id=current_order_id, 
                    candidate_name=current_candidate_name,
                    amount=amount,
                    service_description=description,
                    metadata={
                        "order_number": current_order_id
                    }
                )
                line_items.append(item)
        
        return line_items