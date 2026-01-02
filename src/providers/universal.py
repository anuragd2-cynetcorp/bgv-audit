"""
Provider extractor for Universal invoices.
"""
import re
import pdfplumber
from typing import List
from .base import BaseProvider, ExtractedInvoice, ExtractedLineItem


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
        
        # State variables
        current_date = None
        current_candidate_name = None
        current_order_id = None
        
        with pdfplumber.open(pdf_path) as pdf:
            # 1. Attempt to find Invoice Number (if it exists on page 1)
            first_page_text = pdf.pages[0].extract_text()
            inv_match = re.search(r'Invoice\s*#?\s*[:.]?\s*([A-Z0-9\-]+)', first_page_text, re.IGNORECASE)
            if inv_match:
                invoice_number = inv_match.group(1)

            # 2. Iterate through all pages
            for page in pdf.pages:
                text = page.extract_text(layout=True) # layout=True helps separate columns visually
                if not text:
                    continue
                
                lines = text.split('\n')
                for line in lines:
                    line = line.strip()
                    
                    # --- Check for Grand Total (usually last page) ---
                    # Pattern: "Invoice Total $<amount>"
                    total_match = re.search(r'Invoice Total\s+\$([\d,]+\.\d{2})', line)
                    if total_match:
                        grand_total = float(total_match.group(1).replace(',', ''))
                        continue

                    # --- Check for Candidate Header ---
                    # Pattern: "<date> <name> - (Order # <id>)"
                    # Regex: Date | Name | - | (Order # ID)
                    header_match = re.match(r'^(\d{1,2}/\d{1,2}/\d{4})\s+(.+?)\s+-\s+\(Order\s+#\s+(\d+)\)', line)
                    if header_match:
                        current_date = header_match.group(1)
                        current_candidate_name = header_match.group(2).strip()
                        current_order_id = header_match.group(3)
                        continue

                    # --- Check for Subtotal Line (Skip) ---
                    if line.startswith("Subtotal for Order"):
                        continue
                        
                    # --- Check for Table Headers (Skip) ---
                    if "Candidate name - order number" in line:
                        continue

                    # --- Check for Line Item ---
                    # Pattern: Description followed by Amount at the end
                    # Format: "<description> $<amount>"
                    # Regex: Start of line, anything (lazy), space, currency at end
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

                        # Create Line Item
                        # We use the Order ID as the Candidate ID because it is unique per request
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