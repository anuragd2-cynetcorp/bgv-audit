"""
Service for invoice processing and management.
"""
from typing import Dict, List, Optional
from src.models import Invoice
from src.services.base import BaseService
from src.providers.base import ExtractedInvoice, append_timestamp_to_invoice_number
from src.logger import get_logger

logger = get_logger()


class InvoiceService(BaseService[Invoice]):
    """
    Service for invoice-related operations.
    """
    
    def __init__(self):
        super().__init__(Invoice)
    
    def process_invoice(self, filename: str, uploaded_by: str, extracted: ExtractedInvoice) -> Invoice:
        """
        Process an uploaded invoice PDF.
        
        Args:
            filename: Original filename
            uploaded_by: Email of the user who uploaded the file
            extracted: Pre-extracted invoice data
            
        Returns:
            Created Invoice instance
            
        Raises:
            ValueError: If processing fails
        """
        
        # Append timestamp to invoice number for uniqueness
        invoice_number_with_timestamp = append_timestamp_to_invoice_number(
            extracted.invoice_number
        )
        
        # Create invoice document
        invoice = self.create_or_update(
            doc_id=invoice_number_with_timestamp,
            filename=filename,
            invoice_number=invoice_number_with_timestamp,
            provider_name=extracted.provider_name,
            grand_total=extracted.grand_total,
            uploaded_by=uploaded_by,
            audit_status="PENDING"
        )
        
        return invoice
    
    def get_invoice_by_number(self, invoice_number: str) -> Optional[Invoice]:
        """
        Get an invoice by its invoice number.
        
        Args:
            invoice_number: Invoice number
            
        Returns:
            Invoice instance if found, None otherwise
        """
        return self.get_by_id(invoice_number)
    
    def list_invoices_by_user(self, user_email: str) -> List[Invoice]:
        """
        List all invoices uploaded by a specific user.
        
        Args:
            user_email: User's email address
            
        Returns:
            List of Invoice instances
        """
        # FireO query example - adjust based on your FireO version
        return Invoice.db().filter('uploaded_by', '==', user_email).fetch()

