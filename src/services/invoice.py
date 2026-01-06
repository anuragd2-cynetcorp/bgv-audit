"""
Service for invoice processing and management.
"""
from typing import Dict, List, Optional
from src.models import Invoice
from src.services.base import BaseService
from src.providers.base import ExtractedInvoice, append_timestamp_to_invoice_number, hash_invoice_id
from src.utils.paginator import Paginator
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
        
        # Store raw invoice number (convert "__" to "_" if not found)
        raw_invoice_number = extracted.invoice_number if extracted.invoice_number != "__" else "_"
        
        # Generate unique ID with timestamp, then hash it for consistent format
        timestamped_invoice_number = append_timestamp_to_invoice_number(extracted.invoice_number)
        invoice_id = hash_invoice_id(timestamped_invoice_number)
        
        # Create invoice document
        # The doc_id becomes the document ID, accessible via invoice.id
        invoice = self.create_or_update(
            doc_id=invoice_id,
            filename=filename,
            invoice_number=raw_invoice_number,
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
    
    def list_invoices_paginated(self, user_email: str, page: int = 1, per_page: int = 10) -> Dict:
        """
        List invoices with pagination using the reusable Paginator utility.
        
        Args:
            user_email: User's email address
            page: Page number (1-indexed)
            per_page: Number of records per page
            
        Returns:
            Dictionary with 'invoices' (list), 'total' (int), 'page' (int), 'per_page' (int), 'total_pages' (int)
        """
        # Base query: filter by user
        query = Invoice.db().filter('uploaded_by', '==', user_email)
        
        # Use Paginator utility
        pagination_result = Paginator.paginate(query, page=page, per_page=per_page)
        
        # Map to expected format (using 'invoices' instead of 'items')
        return {
            'invoices': pagination_result['items'],
            'total': pagination_result['total'],
            'page': pagination_result['page'],
            'per_page': pagination_result['per_page'],
            'total_pages': pagination_result['total_pages']
        }

