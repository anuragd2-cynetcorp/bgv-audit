"""
Service for invoice processing and management.
"""
from typing import Dict, List, Optional
from src.models import Invoice, LineItemFingerprint
from src.services.base import BaseService
from src.providers.base import ExtractedInvoice, generate_fingerprint_id


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
        
        # Create invoice document
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
        Store fingerprints based on Service Date, ID, Name, and Amount.
        """
        fingerprint_service = LineItemFingerprintService()
        
        # Prepare bulk items list
        fingerprint_items = []
        
        for line_item in extracted.line_items:
            if not line_item.candidate_id or not line_item.service_date:
                print(f"Warning: Skipping line item missing ID or Date. ID: {line_item.candidate_id}")
                continue
            
            candidate_id = str(line_item.candidate_id).strip()
            candidate_name = str(line_item.candidate_name).strip()
            service_date = str(line_item.service_date).strip()
            amount = float(line_item.amount)
            service_description = str(line_item.service_description).strip()

            # Generate fingerprint ID
            fingerprint_id = generate_fingerprint_id(
                service_date, 
                candidate_id, 
                candidate_name, 
                amount,
                service_description
            )
            
            fingerprint_items.append({
                'doc_id': fingerprint_id,
                'invoice_id': invoice_id,
                'invoice_number': extracted.invoice_number,
                'provider_name': extracted.provider_name,
                'metadata': line_item.metadata,
                'candidate_id': candidate_id,
                'candidate_name': candidate_name,
                'service_date': service_date,
                'amount': amount,
                'service_description': service_description 
            })
        
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
        return Invoice.db().filter('uploaded_by', '==', user_email).fetch()


class LineItemFingerprintService(BaseService[LineItemFingerprint]):
    """
    Service for managing line item fingerprints.
    """
    
    def __init__(self):
        super().__init__(LineItemFingerprint)
    
    def check_historical_duplicate(self, service_date: str, candidate_id: str, patient_name: str, amount: float, service_description: str, current_invoice_id: str) -> Optional[LineItemFingerprint]:
        """
        Check if a line item has been billed before.
        """
        fingerprint_id = generate_fingerprint_id(
            service_date, 
            candidate_id, 
            patient_name, 
            amount,
            service_description
        )
        
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

