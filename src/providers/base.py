"""
Base provider class for PDF invoice extraction.
All provider-specific extractors must inherit from this class.
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Optional
from datetime import datetime
import hashlib
import re
import PyPDF2
import pdfplumber
from src.logger import get_logger
from src.config import Config

logger = get_logger()


def normalize_description(description: str) -> str:
    """
    Normalize service description for duplicate detection.
    Removes extra whitespace, converts to lowercase, and removes common variations.
    
    Args:
        description: Raw service description
        
    Returns:
        Normalized description string
    """
    if not description:
        return ""
    
    # Convert to lowercase and normalize whitespace
    normalized = description.lower().strip()
    normalized = re.sub(r'\s+', ' ', normalized)
    
    # Remove common punctuation and extra characters
    normalized = re.sub(r'[^\w\s\-]', '', normalized)
    
    # Remove trailing/leading hyphens
    normalized = normalized.strip('-').strip()
    
    return normalized


def generate_fingerprint_id(date: str, candidate_id: str, amount: float, service_description: str) -> str:
    """
    Generates a unique hash for duplicate detection based on:
    - Date (service date)
    - Candidate ID (SSN or Chain ID - reliable identifier)
    - Amount (exact to 2 decimal places)
    - Normalized Service Description (for distinguishing different services)
    
    Note: We don't use candidate_name for fingerprinting as it's unreliable and causes parsing overhead.
    Candidate ID is already unique and sufficient for duplicate detection.
    
    Args:
        date: Service date (normalized format)
        candidate_id: Candidate ID (SSN or Chain ID)
        amount: Service amount (will be formatted to 2 decimals)
        service_description: Service description (will be normalized)
        
    Returns:
        MD5 hash string for duplicate detection
    """
    # Format amount to 2 decimal places to avoid floating point mismatch
    amount_str = "{:.2f}".format(amount)
    
    # Normalize description for consistent fingerprinting
    normalized_desc = normalize_description(service_description)
    
    # Create raw string: "<date>|<candidate_id>|<amount>|<normalized_description>"
    raw_string = f"{date}|{candidate_id}|{amount_str}|{normalized_desc}"
    
    # Return MD5 hash
    return hashlib.md5(raw_string.encode('utf-8')).hexdigest()


def append_timestamp_to_invoice_number(invoice_number: str) -> str:
    """
    Append timestamp to an invoice number to ensure uniqueness.
    Format: <invoice_number>_YYYYMMDDHHMMSSmicroseconds
    If invoice_number is "__", result will be: __YYYYMMDDHHMMSSmicroseconds (no extra underscore)
    
    Args:
        invoice_number: The invoice number (can be "__" for unknown or actual number)
        
    Returns:
        Invoice number with timestamp appended
    """
    now = datetime.now()
    timestamp = now.strftime("%Y%m%d%H%M%S")
    microseconds = now.microsecond
    timestamp_suffix = f"{timestamp}{microseconds:06d}"
    
    # If invoice_number is "__" (unknown), don't add extra underscore
    if invoice_number == "__":
        return f"__{timestamp_suffix}"
    else:
        return f"{invoice_number}_{timestamp_suffix}"


def hash_invoice_id(timestamped_invoice_number: str) -> str:
    """
    Generate a consistent hash of the timestamped invoice number for use as document ID.
    This ensures consistent length and format for all document IDs.
    
    Args:
        timestamped_invoice_number: The invoice number with timestamp appended
        
    Returns:
        SHA256 hash (64 characters) of the timestamped invoice number
    """
    return hashlib.sha256(timestamped_invoice_number.encode('utf-8')).hexdigest()


class ExtractedLineItem:
    """Represents a single line item extracted from an invoice."""
    def __init__(
        self, 
        service_date: str,          # Normalized Date
        candidate_id: str, 
        candidate_name: str, 
        amount: float, 
        service_description: str,   # Normalized Description
        metadata: Dict = None       # Store extra provider-specific stuff here
    ):
        self.service_date = service_date
        self.candidate_id = candidate_id
        self.candidate_name = candidate_name
        self.amount = amount
        self.service_description = service_description
        self.metadata = metadata or {}
    
    def to_dict(self) -> Dict:
        """Convert line item to dictionary."""
        return {
            'service_date': self.service_date,
            'candidate_id': self.candidate_id,
            'candidate_name': self.candidate_name,
            'amount': self.amount,
            'service_description': self.service_description,
            'metadata': self.metadata
        }

    @property
    def fingerprint(self) -> str:
        """
        Generate a unique fingerprint for duplicate detection.
        Uses: date, candidate_id, amount, and normalized description.
        Note: candidate_name is NOT used for fingerprinting as it's unreliable and causes parsing overhead.
        """
        return generate_fingerprint_id(self.service_date, self.candidate_id, self.amount, self.service_description)

class ExtractedInvoice:
    """Represents extracted data from an invoice."""
    def __init__(self, invoice_number: str, provider_name: str, line_items: List[ExtractedLineItem], grand_total: float):
        # Store raw invoice number (timestamp and user_id will be added in process_invoice)
        self.invoice_number = invoice_number
        self.provider_name = provider_name
        self.line_items = line_items
        self.grand_total = grand_total
    
    def to_dict(self) -> Dict:
        """Convert invoice to dictionary."""
        return {
            'invoice_number': self.invoice_number,
            'provider_name': self.provider_name,
            'line_items': [item.to_dict() for item in self.line_items],
            'grand_total': self.grand_total
        }


class BaseProvider(ABC):
    """
    Base class for all provider-specific extractors.
    
    Each provider must implement:
    1. identify() - Check if this provider can handle the PDF
    2. extract() - Extract invoice data from the PDF
    """
    
    def __init__(self, name: str):
        """
        Initialize the provider.
        
        Args:
            name: Human-readable name of the provider
        """
        self.name = name
    
    @staticmethod
    def generate_unknown_invoice_number() -> str:
        """
        Generate invoice number placeholder when invoice ID is not found.
        The timestamp will be automatically appended in process_invoice.
        Result will be: __YYYYMMDDHHMMSSmicroseconds (double underscore)
        
        Returns:
            "__" string (timestamp will be added centrally)
        """
        return "__"
    
    @abstractmethod
    def identify(self, pdf_path: str) -> bool:
        """
        Check if this provider can handle the given PDF.
        
        This method should check for provider-specific markers like:
        - Company name/logo
        - Specific keywords in headers
        - Unique formatting patterns
        
        Args:
            pdf_path: Path to the PDF file
            
        Returns:
            True if this provider can handle the PDF, False otherwise
        """
        pass
    
    @abstractmethod
    def extract(self, pdf_path: str) -> ExtractedInvoice:
        """
        Extract invoice data from the PDF.
        
        This method must extract:
        - Invoice Number
        - Provider Name
        - Line Items (Candidate Name, ID, Service Description, Cost)
        - Grand Total
        
        Args:
            pdf_path: Path to the PDF file
            
        Returns:
            ExtractedInvoice object containing all extracted data
            
        Raises:
            ValueError: If extraction fails or data is invalid
        """
        pass
    
    def _get_pdf_text(self, pdf_path: str) -> str:
        """
        Helper method to extract text from PDF using pdfplumber.
        
        Args:
            pdf_path: Path to the PDF file
            
        Returns:
            Full text content of the PDF
        """
        text = ""
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text += page.extract_text() or ""
        return text
    
    def _get_pdf_tables(self, pdf_path: str) -> List[List[List[str]]]:
        """
        Helper method to extract tables from PDF using pdfplumber.
        
        Args:
            pdf_path: Path to the PDF file
            
        Returns:
            List of tables, where each table is a list of rows,
            and each row is a list of cell values
        """
        tables = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_tables = page.extract_tables()
                if page_tables:
                    tables.extend(page_tables)
        return tables
    
    def _get_pdf_pages(self, pdf_path: str) -> List:
        """
        Helper method to get PDF pages using pdfplumber.
        
        Args:
            pdf_path: Path to the PDF file
            
        Returns:
            List of pdfplumber Page objects
        """
        with pdfplumber.open(pdf_path) as pdf:
            return pdf.pages
    
    def _get_text_lines(self, pdf_path: str, use_ocr: bool = False) -> List[str]:
        """
        Extract text lines from PDF.
        
        Args:
            pdf_path: Path to the PDF file
            use_ocr: If True, use OCR. If False, use normal text extraction.
            
        Returns:
            List of text lines extracted from the PDF
        """
        all_lines = []
        
        if use_ocr:
            # Use Google Cloud Document AI OCR for better accuracy and no memory issues
            logger.info(f"Using Document AI OCR extraction for {self.name} invoice.")
            from src.services.document_ai_ocr import DocumentAIOCRService
            ocr_service = DocumentAIOCRService()
            all_lines = ocr_service.extract_text_lines(pdf_path)
            logger.info(f"Document AI OCR extracted {len(all_lines)} lines successfully")
        else:
            # Use normal text extraction
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    text = page.extract_text(layout=True)
                    if text:
                        page_lines = [line.strip() for line in text.split('\n') if line.strip()]
                        all_lines.extend(page_lines)
        
        return all_lines
    
    @abstractmethod
    def _parse_text_lines(self, lines: List[str]) -> List[ExtractedLineItem]:
        """
        Parse text lines into line items. Must be implemented by child classes.
        Each provider should optimize for their specific PDF structure.
        
        For duplicate detection and total mismatch, only these fields are needed:
        - service_date (normalized date)
        - candidate_id (SSN, Chain ID, or other unique identifier)
        - amount (exact amount to 2 decimal places)
        - service_description (normalized description for fingerprinting)
        
        Note: candidate_name is NOT used for fingerprinting (see generate_fingerprint_id).
        Extract it if needed for display, but it can be simplified to candidate_id for efficiency.
        
        Args:
            lines: List of text lines to parse
            
        Returns:
            List of ExtractedLineItem objects
            
        Raises:
            NotImplementedError: If not implemented by child class
        """
        raise NotImplementedError("Child class must implement _parse_text_lines")

