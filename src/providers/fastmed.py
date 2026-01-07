"""
Provider extractor for FastMed invoices.
"""
import re
import pdfplumber
from typing import List
from .base import BaseProvider, ExtractedInvoice, ExtractedLineItem
from src.logger import get_logger

logger = get_logger()


class FastMedProvider(BaseProvider):
    """
    Extractor for FastMed invoices.
    
    Format Characteristics:
    - Summary Page (usually Page 3) contains "Account Number" and "Amount Due".
    - Detail Pages (Page 4+) contain a table with headers:
      [DOS, Invoice (HAR), Patient Name, SSN, Clinic, Description of Service, Total]
    """
    
    def __init__(self):
        """Initialize the FastMed provider."""
        super().__init__("FastMed")
        self.identification_keywords = ["FastMed", "FASTMED", "fastmed.com"]
    
    def identify(self, pdf_path: str) -> bool:
        """Check if this PDF belongs to FastMed."""
        text = self._get_pdf_text(pdf_path)
        return any(kw in text for kw in self.identification_keywords)
    
    def _normalize_arabic_numbers(self, text: str) -> str:
        """Convert Arabic-Indic numerals and other Arabic characters to Western equivalents."""
        # Arabic-Indic numerals
        arabic_to_western = {
            '٠': '0', '١': '1', '٢': '2', '٣': '3', '٤': '4',
            '٥': '5', '٦': '6', '٧': '7', '٨': '8', '٩': '9',
            # Arabic letters that might be OCR'd as numbers in dates
            'ج': '6',  # Jeem - sometimes OCR'd in place of 6
        }
        for arabic, western in arabic_to_western.items():
            text = text.replace(arabic, western)
        return text
    
    def extract(self, pdf_path: str) -> ExtractedInvoice:
        """
        Extract invoice data from FastMed's PDF format.
        """
        invoice_number = "UNKNOWN"
        grand_total = 0.0
        line_items = []
        
        with pdfplumber.open(pdf_path) as pdf:
            # --- Step 1: Check if Scanned ---
            total_chars = sum(len(p.extract_text() or "") for p in pdf.pages[:3])
            if total_chars < 50:
                raise ValueError("PDF appears to be a scanned image (no text found). OCR is required.")

            # --- Step 2: Extract Header Info (check all pages) ---
            # Collect all candidates and prefer clean (non-Arabic) versions
            invoice_candidates = []
            for page in pdf.pages:
                page_text = page.extract_text()
                if not page_text: continue
                
                # Try various patterns for account number
                acct_match = re.search(r'Account\s*(?:Number|#)\s*[:.]?\s*([0-9٠-٩]+)', page_text, re.IGNORECASE)
                if acct_match:
                    raw_num = acct_match.group(1)
                    # Prefer clean numbers (only ASCII digits)
                    is_clean = all(c.isdigit() and ord(c) < 128 for c in raw_num)
                    invoice_candidates.append((raw_num, is_clean))
                
                if grand_total == 0.0:
                    # Try various patterns for total amount
                    total_match = re.search(r'(?:Amount\s*Due|AMOUNT\s*YOU\s*OWE|AM٠UNTY٠٧٠WE)\s*[:]?\s*[\$S]?([\d,]+\.\d{2})', page_text, re.IGNORECASE)
                    if total_match:
                        grand_total = float(total_match.group(1).replace(',', ''))
            
            # Pick the best invoice number (prefer clean, then longest)
            if invoice_candidates:
                # First try to find a clean one
                clean_candidates = [c[0] for c in invoice_candidates if c[1]]
                if clean_candidates:
                    invoice_number = max(clean_candidates, key=len)
                else:
                    # Fall back to normalizing the first one
                    invoice_number = self._normalize_arabic_numbers(invoice_candidates[0][0])

            # --- Step 3: Extract Line Items (Table Strategy) ---
            for page in pdf.pages:
                # vertical_strategy='text' is best for tables with whitespace gaps instead of lines
                tables = page.extract_tables(table_settings={
                    "vertical_strategy": "text",
                    "horizontal_strategy": "text",
                    "snap_tolerance": 3,
                    "min_words_vertical": 1
                })
                
                for table in tables:
                    if not table or len(table) < 2: continue
                    
                    # Validate Headers
                    header_row = [str(c).strip().lower() for c in table[0] if c]
                    if not ("dos" in header_row and "patient name" in header_row):
                        continue
                        
                    for row in table[1:]:
                        # Filter empty rows
                        if not row or not row[0]: continue
                        
                        # Validate Date (Column 0)
                        date_str = str(row[0]).strip()
                        if not re.match(r'\d{1,2}/\d{1,2}/\d{4}', date_str):
                            continue
                            
                        try:
                            # --- Relative Indexing Strategy ---
                            # We assume the table structure:
                            # [Date, Ref, Name, ... (SSN/Clinic) ..., Desc, Amount]
                            
                            # 1. Anchors (Left)
                            ref_number = str(row[1]).strip() if len(row) > 1 else ""
                            patient_name = str(row[2]).strip() if len(row) > 2 else "Unknown"
                            
                            # 2. Anchors (Right)
                            amount_str = str(row[-1]).strip()
                            description = str(row[-2]).strip() if len(row) >= 5 else ""
                            
                            # 3. Middle (Metadata)
                            # Everything between Name (idx 2) and Description (idx -2)
                            # This handles cases where SSN is empty or Clinic is merged
                            metadata_cols = row[3:-2]
                            
                            ssn = ""
                            clinic = ""
                            
                            for cell in metadata_cols:
                                if not cell: continue
                                cell_str = str(cell).strip()
                                if "xxx-xx-" in cell_str.lower():
                                    ssn = cell_str
                                else:
                                    clinic = cell_str # Assume non-SSN text is Clinic

                            # Clean Amount
                            amount = float(amount_str.replace('$', '').replace(',', ''))
                            
                            # Determine ID
                            candidate_id = ssn if ssn else patient_name
                            
                            line_items.append(ExtractedLineItem(
                                service_date=date_str,
                                candidate_id=candidate_id,
                                candidate_name=patient_name,
                                amount=amount,
                                service_description=description,
                                metadata={
                                    "clinic": clinic,
                                    "reference_number": ref_number
                                }
                            ))
                        except (ValueError, IndexError):
                            continue

            # --- Step 4: Regex Fallback (if tables failed) ---
            if not line_items:
                lines = self._get_text_lines(pdf_path, use_ocr=False)
                line_items = self._parse_text_lines(lines)
            
            # --- Step 5: OCR Fallback (if regex also failed) ---
            if not line_items:
                logger.info("No line items found with table and text extraction. Attempting OCR fallback for FastMed invoice.")
                try:
                    lines = self._get_text_lines(pdf_path, use_ocr=True)
                    line_items = self._parse_text_lines(lines)
                    logger.info(f"OCR extraction found {len(line_items)} line items.")
                except Exception as e:
                    logger.error(f"OCR extraction failed: {str(e)}", exc_info=True)
                    # Continue to raise the original error if OCR also fails

        if not line_items:
            raise ValueError("Could not extract line items from invoice. Format may have changed.")
            
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
        Parse text lines into line items using FastMed-specific regex logic.
        
        Format: DATE HAR# NAME [SSN] CLINIC CODE - Description AMOUNT
        Examples:
            4/23/2025 10616406 Donna Smith Clayton 97750 -Standard Physical S95.00
            5/9/2025 10663575 Jessica Henry ΧΧΧ-ΧΧ-5521 Durham 50305 - Drug Screen Full Screen 569.00
        
        Args:
            lines: List of text lines to parse
            
        Returns:
            List of ExtractedLineItem objects
        """
        line_items = []
        
        # Regex pattern for SSN variants (OCR may misread X as various chars)
        ssn_pattern = re.compile(r'[XΧхХ]{3}-[XΧхХ]{2}-\d{4}', re.IGNORECASE)
        
        # Pattern for service code (5-digit number followed by description)
        service_code_pattern = re.compile(r'(\d{5})\s*[-:]\s*(.+?)(?:\s+[S\$]?[\d,]+\.\d{2})?$')
        
        for line in lines:
            line = line.strip()
            
            # Must start with a date (handle OCR issues with date separators and Arabic numerals)
            # Arabic chars that might appear: ج (6), ث (could be /), م (could be part of date)
            # Pattern allows: digits or Arabic numerals, followed by / or Arabic chars, etc.
            date_match = re.match(r'^([0-9٠-٩ج]{1,2}[/ثم٠-٩]+[0-9٠-٩]{1,2}[/ثم٠-٩]*[0-9٠-٩]{4})', line)
            if not date_match:
                # Try simpler pattern for clean dates
                date_match = re.match(r'^(\d{1,2}/\d{1,2}/\d{4})', line)
                if not date_match:
                    continue
            
            # Extract amount from end (handle S instead of $ due to OCR)
            # Pattern: optional S or $ followed by digits.cents or digits:cents (colon is common OCR error)
            # Also handle cases like "S95.00" or "$95.00" or "595.00" (where S was read as 5)
            # Or "869:00" where colon is misread period
            amount_match = re.search(r'[S\$\s]?([\d,]+[\.:]\d{2})\s*$', line)
            if not amount_match:
                continue
            
            # Skip lines that look like summary/footer lines (Due Date, Amount Due, etc.)
            if re.search(r'(?:Due\s*Date|Amount\s*Due|AMOUNT\s*YOU\s*OWE|Payment|Questions)', line, re.IGNORECASE):
                continue
            
            # Skip lines that only have a date and amount (no other content) - likely summary lines
            # Check if the middle portion (between date and amount) is mostly whitespace
            middle_content = line[date_match.end():amount_match.start()].strip()
            if not middle_content or len(middle_content) < 5:
                continue
            
            try:
                # Normalize date (replace Arabic chars if any)
                date_str = date_match.group(1)
                # First normalize Arabic-Indic numerals
                date_str = self._normalize_arabic_numbers(date_str)
                # Replace Arabic chars that might be used as separators
                date_str = re.sub(r'[جثم]', '/', date_str)  # Replace Arabic chars with /
                date_str = re.sub(r'/+', '/', date_str)  # Normalize multiple slashes
                # Ensure proper date format (M/D/YYYY)
                date_parts = date_str.split('/')
                if len(date_parts) == 3:
                    date_str = f"{date_parts[0]}/{date_parts[1]}/{date_parts[2]}"
                
                amount_str = amount_match.group(1).replace(',', '').replace(':', '.')  # Normalize colon to period
                amount = float(amount_str)
                
                # Fix OCR issues where "$" or "S" is misread as a digit at the start
                # Common FastMed prices: $69, $95, $149
                # OCR errors: 569, 595, 5149 (5 prefix), 869 (8 prefix - $ misread as 8)
                if len(amount_str) >= 5 and amount > 500:
                    # Check if removing the leading digit gives a reasonable amount
                    potential_amount = float(amount_str[1:])
                    # Check if it matches a common price (with tolerance)
                    if abs(potential_amount - 69.00) < 0.01 or \
                       abs(potential_amount - 95.00) < 0.01 or \
                       abs(potential_amount - 149.00) < 0.01:
                        amount = potential_amount
                
                # Get the middle portion (between date and amount)
                middle = line[date_match.end():amount_match.start()].strip()
                
                # Extract HAR number (first numeric sequence after date)
                har_match = re.match(r"^'?(\d+)", middle)
                har_number = ""
                if har_match:
                    har_number = har_match.group(1)
                    middle = middle[har_match.end():].strip()
                
                # Check for SSN
                ssn = ""
                ssn_match = ssn_pattern.search(middle)
                if ssn_match:
                    ssn = ssn_match.group(0)
                
                # Find service code and description
                service_match = service_code_pattern.search(middle)
                service_code = ""
                description = ""
                
                if service_match:
                    service_code = service_match.group(1)
                    description = service_match.group(2).strip()
                    # Get everything before the service code as name+clinic
                    name_clinic = middle[:service_match.start()].strip()
                else:
                    # Fallback: try to find description after a dash
                    dash_match = re.search(r'\s+-\s*(.+)$', middle)
                    if dash_match:
                        description = dash_match.group(1).strip()
                        name_clinic = middle[:dash_match.start()].strip()
                    else:
                        name_clinic = middle
                
                # Remove SSN from name_clinic if present
                if ssn:
                    name_clinic = name_clinic.replace(ssn, '').strip()
                
                # Split name_clinic into name and clinic
                # Heuristic: First 2-3 capitalized words are likely the name
                words = name_clinic.split()
                patient_name = ""
                clinic = ""
                
                # Find where name ends (usually after 2-3 words, before a known clinic pattern)
                name_words = []
                clinic_words = []
                in_clinic = False
                
                for i, word in enumerate(words):
                    # Clinic indicators: hyphenated words, known clinic names, or after 3 name words
                    if in_clinic:
                        clinic_words.append(word)
                    elif '-' in word and i > 0:  # Hyphenated word (e.g., "Garner-Cleveland")
                        clinic_words.append(word)
                        in_clinic = True
                    elif i >= 2 and (word[0].isupper() or word.isalpha()):
                        # After 2 words, check if this looks like a clinic name
                        # Clinics often have location-style names
                        if len(name_words) >= 2:
                            clinic_words.append(word)
                            in_clinic = True
                        else:
                            name_words.append(word)
                    else:
                        name_words.append(word)
                
                patient_name = ' '.join(name_words) if name_words else "Unknown"
                clinic = ' '.join(clinic_words)
                
                # Clean up patient name (remove any stray punctuation)
                patient_name = re.sub(r'[^\w\s]', '', patient_name).strip()
                
                # Use SSN as candidate_id if available, else patient name
                candidate_id = ssn if ssn else patient_name
                
                line_items.append(ExtractedLineItem(
                    service_date=date_str,
                    candidate_id=candidate_id,
                    candidate_name=patient_name,
                    amount=amount,
                    service_description=f"{service_code} - {description}" if service_code else description,
                    metadata={
                        "clinic": clinic,
                        "reference_number": har_number,
                        "ssn": ssn
                    }
                ))
            except Exception as e:
                logger.debug(f"Failed to parse FastMed line: {line}, error: {e}")
                continue
        
        return line_items