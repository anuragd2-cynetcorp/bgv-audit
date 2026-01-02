"""
Base provider class for PDF invoice extraction.
All provider-specific extractors must inherit from this class.
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Optional
from datetime import datetime
import hashlib
import PyPDF2
import pdfplumber


def generate_fingerprint_id(date: str, candidate_id: str, name: str, amount: float, service_description: str) -> str:
    """
    Generates a unique hash based on Date, Patient ID, Name, Amount, and Service Description.
    """
    # Format amount to 2 decimal places to avoid floating point mismatch
    amount_str = "{:.2f}".format(amount)
    
    # Create raw string: "<date>|<candidate_id>|<name>|<amount>|<service_description>"
    raw_string = f"{date}|{candidate_id}|{name}|{amount_str}|{service_description}"
    
    # Return MD5 hash
    return hashlib.md5(raw_string.encode('utf-8')).hexdigest()


def append_timestamp_to_invoice_number(invoice_number: str) -> str:
    """
    Append a timestamp to an invoice number to ensure uniqueness.
    Format: <invoice_number>_YYYYMMDD_HHMMSS_microseconds
    
    Args:
        invoice_number: The invoice number (can be "UNKNOWN" or actual number)
        
    Returns:
        Invoice number with timestamp appended
    """
    now = datetime.now()
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    microseconds = now.microsecond
    timestamp_suffix = f"{timestamp}_{microseconds:06d}"
    return f"{invoice_number}_{timestamp_suffix}"


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
        """Generate a unique fingerprint for duplicate detection."""
        return generate_fingerprint_id(self.service_date, self.candidate_id, self.candidate_name, self.amount, self.service_description)

class ExtractedInvoice:
    """Represents extracted data from an invoice."""
    def __init__(self, invoice_number: str, provider_name: str, line_items: List[ExtractedLineItem], grand_total: float):
        # Automatically append timestamp to invoice number for uniqueness
        self.invoice_number = append_timestamp_to_invoice_number(invoice_number)
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
        The timestamp will be automatically appended by ExtractedInvoice.__init__
        
        Returns:
            "UNKNOWN" string (timestamp will be added centrally)
        """
        return "UNKNOWN"
    
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

