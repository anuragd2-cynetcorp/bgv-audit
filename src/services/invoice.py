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
        # Extract invoice data using the provided provider
        extracted = provider.extract(pdf_path)
        
        # Create invoice document
        # Use invoice_number as document ID for easy lookup
        invoice = self.create_or_update(
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
        Uses bulk create/update for efficiency.
        
        Args:
            invoice_id: Invoice document ID
            extracted: ExtractedInvoice object
        """
        fingerprint_service = LineItemFingerprintService()
        
        # Prepare bulk items list
        fingerprint_items = []
        
        for line_item in extracted.line_items:
            # Validate required fields
            if not line_item.candidate_id or not line_item.service_description:
                print(f"Warning: Skipping line item with missing candidate_id or service_description. "
                      f"candidate_id='{line_item.candidate_id}', service_description='{line_item.service_description}'")
                continue
            
            # Ensure candidate_id and service_description are strings and not empty
            candidate_id = str(line_item.candidate_id).strip()
            service_description = str(line_item.service_description).strip()
            
            if not candidate_id or not service_description:
                print(f"Warning: Skipping line item with empty candidate_id or service_description after stripping")
                continue
            
            # Create fingerprint ID: candidate_id|service_description
            fingerprint_str = f"{candidate_id}|{service_description}"
            
            # Sanitize for Firestore: replace | with __ and remove invalid characters
            # Firestore document ID restrictions:
            # - Cannot be empty
            # - Cannot contain certain characters (/, \, ?, #, [, ], *)
            # - Max length is 1500 bytes
            fingerprint_id = fingerprint_str.replace('|', '__')
            fingerprint_id = fingerprint_id.replace('/', '_').replace('\\', '_').replace('?', '_')
            fingerprint_id = fingerprint_id.replace('#', '_').replace('[', '_').replace(']', '_').replace('*', '_')
            
            # Ensure it's not empty after sanitization and has reasonable length
            if not fingerprint_id or len(fingerprint_id) == 0:
                print(f"Warning: Skipping line item with empty fingerprint after sanitization")
                continue
            
            if len(fingerprint_id) > 1500:
                print(f"Warning: Fingerprint too long ({len(fingerprint_id)} chars), truncating")
                fingerprint_id = fingerprint_id[:1500]
            
            # Prepare item for bulk operation
            fingerprint_items.append({
                'doc_id': fingerprint_id,
                'candidate_id': candidate_id,
                'service_description': service_description,
                'invoice_id': invoice_id,
                'invoice_number': extracted.invoice_number,
                'provider_name': extracted.provider_name,
                'cost': line_item.cost
            })
        
        # Bulk create or update all fingerprints at once
        if fingerprint_items:
            fingerprint_service.bulk_create_or_update(fingerprint_items, skip_existence_check=False)
    
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

