"""
Service for invoice processing and management.
"""
from typing import Dict, List, Optional
from src.models import Invoice, LineItemFingerprint
from src.services.base import BaseService
from src.providers.base import BaseProvider, ExtractedInvoice, ExtractedLineItem


class InvoiceService(BaseService[Invoice]):
    """
    Service for invoice-related operations.
    """
    
    def __init__(self):
        super().__init__(Invoice)
    
    def process_invoice(self, pdf_path: str, filename: str, uploaded_by: str, provider: BaseProvider) -> Invoice:
        """
        Process an uploaded invoice PDF.
        
        Args:
            pdf_path: Path to the uploaded PDF file
            filename: Original filename
            uploaded_by: Email of the user who uploaded the file
            provider: Provider instance to use for extraction
            
        Returns:
            Created Invoice instance
            
        Raises:
            ValueError: If processing fails
        """
        if not provider:
            raise ValueError("Provider instance is required")
        
        # Extract invoice data using the provided provider
        extracted = provider.extract(pdf_path)
        
        # Create invoice document
        # Use invoice_number as document ID for easy lookup
        invoice = self.create(
            doc_id=extracted.invoice_number,
            filename=filename,
            invoice_number=extracted.invoice_number,
            provider_name=extracted.provider_name,
            grand_total=extracted.grand_total,
            uploaded_by=uploaded_by,
            audit_status="PENDING"
        )
        
        # Store line item fingerprints for duplicate detection
        self._store_fingerprints(invoice.id, extracted)
        
        return invoice
    
    def _store_fingerprints(self, invoice_id: str, extracted: ExtractedInvoice):
        """
        Store fingerprints of line items for historical duplicate detection.
        
        Args:
            invoice_id: Invoice document ID
            extracted: ExtractedInvoice object
        """
        fingerprint_service = LineItemFingerprintService()
        
        for line_item in extracted.line_items:
            # Create fingerprint ID: candidate_id|service_description
            # Sanitize for Firestore: replace | with __ (Firestore doesn't allow | in doc IDs)
            fingerprint_id = line_item.fingerprint().replace('|', '__')
            
            # Check if this fingerprint already exists (historical duplicate)
            existing = fingerprint_service.get_by_id(fingerprint_id)
            
            if existing:
                # Update to mark as duplicate (we'll handle this in audit)
                fingerprint_service.create_or_update(
                    doc_id=fingerprint_id,
                    candidate_id=line_item.candidate_id,
                    service_description=line_item.service_description,
                    invoice_id=invoice_id,
                    invoice_number=extracted.invoice_number,
                    provider_name=extracted.provider_name,
                    cost=line_item.cost
                )
            else:
                # Create new fingerprint
                fingerprint_service.create(
                    doc_id=fingerprint_id,
                    candidate_id=line_item.candidate_id,
                    service_description=line_item.service_description,
                    invoice_id=invoice_id,
                    invoice_number=extracted.invoice_number,
                    provider_name=extracted.provider_name,
                    cost=line_item.cost
                )
    
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
        return Invoice.collection.filter('uploaded_by', '==', user_email).fetch()


class LineItemFingerprintService(BaseService[LineItemFingerprint]):
    """
    Service for managing line item fingerprints.
    """
    
    def __init__(self):
        super().__init__(LineItemFingerprint)
    
    def check_historical_duplicate(self, candidate_id: str, service_description: str, current_invoice_id: str) -> Optional[LineItemFingerprint]:
        """
        Check if a line item has been billed before in a different invoice.
        
        Args:
            candidate_id: Candidate ID
            service_description: Service description
            current_invoice_id: Current invoice ID (to exclude from check)
            
        Returns:
            LineItemFingerprint if duplicate found, None otherwise
        """
        # Use same sanitization as in _store_fingerprints
        fingerprint_id = f"{candidate_id}|{service_description}".replace('|', '__')
        existing = self.get_by_id(fingerprint_id)
        
        if existing and existing.invoice_id != current_invoice_id:
            return existing
        
        return None
    
    def get_fingerprints_by_invoice(self, invoice_id: str) -> List[LineItemFingerprint]:
        """
        Get all fingerprints for a specific invoice.
        
        Args:
            invoice_id: Invoice document ID
            
        Returns:
            List of LineItemFingerprint instances
        """
        return LineItemFingerprint.collection.filter('invoice_id', '==', invoice_id).fetch()

