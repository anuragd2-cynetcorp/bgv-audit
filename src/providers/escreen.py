"""
Provider extractor for eScreen invoices.
"""
import re
import pdfplumber
from typing import List
from .base import BaseProvider, ExtractedInvoice, ExtractedLineItem


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
        invoice_number = "UNKNOWN"
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
            
            # 3. Extract Line Items (All Pages)
            for page in pdf.pages:
                # Use layout=True to preserve visual spacing between columns
                # This helps separate Description from Name if they are close
                text = page.extract_text(layout=True)
                if not text:
                    continue
                
                lines = text.split('\n')
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
                        # STRICT REGEX: 
                        # 1. [A-Za-z\-\']+   -> Last Name (One word, allows hyphens/apostrophes)
                        # 2. ,               -> Comma (Required)
                        # 3. \s+             -> Space
                        # 4. [A-Za-z\-\']+   -> First Name
                        # 5. (?: [A-Za-z]+)? -> Optional Middle Name
                        # 6. $               -> End of string
                        
                        name_match = re.search(r'([A-Za-z\-\']+, \s*[A-Za-z\-\']+(?: [A-Za-z\-\']+)?)$', middle_chunk)
                        
                        if name_match:
                            candidate_name = name_match.group(1).strip()
                            # Description is everything before the name match
                            description = middle_chunk[:name_match.start()].strip()
                        else:
                            # Fallback: If strict regex fails (e.g. "Van Buren, Martin"), try splitting by double space
                            # This relies on layout=True putting gaps between columns
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
                        print(f"Date: {date_str}, Candidate Name: {candidate_name}, Description: {description}, Amount: {amount}, Final ID: {final_id}")
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
    
    def _extract_from_tables(self, tables: List[List[List[str]]]) -> List[ExtractedLineItem]:
        """Extract line items from PDF tables."""
        # TODO: Implement based on eScreen's format
        return []
    
    def _extract_from_text(self, text: str) -> List[ExtractedLineItem]:
        """Extract line items from text."""
        return []

