"""
Service for auditing invoices and detecting discrepancies.
"""
from typing import Dict, List
from src.models import Invoice
from src.services.invoice import InvoiceService
from src.providers.base import ExtractedInvoice


class AuditResult:
    """Represents the result of an audit check."""
    def __init__(self, check_name: str, passed: bool, message: str, details: Dict = None):
        self.check_name = check_name
        self.passed = passed
        self.message = message
        self.details = details or {}
    
    def to_dict(self) -> Dict:
        return {
            'check_name': self.check_name,
            'passed': self.passed,
            'message': self.message,
            'details': self.details
        }


class AuditReport:
    """Represents a complete audit report for an invoice."""
    def __init__(self, invoice_id: str, overall_status: str, results: List[AuditResult]):
        self.invoice_id = invoice_id
        self.overall_status = overall_status  # "PASS" or "FAIL"
        self.results = results
    
    def to_dict(self) -> Dict:
        return {
            'invoice_id': self.invoice_id,
            'overall_status': self.overall_status,
            'results': [r.to_dict() for r in self.results],
            'total_checks': len(self.results),
            'passed_checks': sum(1 for r in self.results if r.passed),
            'failed_checks': sum(1 for r in self.results if not r.passed)
        }


class AuditService:
    """
    Service for auditing invoices and detecting discrepancies.
    Performs:
    1. Total Mismatch Check
    2. Internal Duplication Check
    """
    
    def __init__(self):
        self.invoice_service = InvoiceService()
        self.rounding_tolerance = 0.01  # $0.01 tolerance for rounding differences
    
    def audit_invoice(self, invoice_id: str, extracted: ExtractedInvoice) -> AuditReport:
        """
        Perform complete audit on an invoice.
        
        Args:
            invoice_id: Invoice document ID (invoice number)
            extracted: Pre-extracted invoice data
            
        Returns:
            AuditReport object
        """
        # Get invoice
        # Try using invoice_number as doc_id (since that's what we use when creating)
        invoice = self.invoice_service.get_by_id(invoice_id)
        if not invoice:
            # If not found, try to get by invoice_number field as fallback
            # This handles cases where the document ID might differ
            try:
                invoices = self.invoice_service.list_invoices_by_user("")  # Empty to get all
                invoice = next((inv for inv in invoices if inv.invoice_number == invoice_id), None)
            except:
                pass
        
        if not invoice:
            raise ValueError(f"Invoice {invoice_id} not found. Please ensure the invoice was created successfully.")
        
        # Perform all audit checks
        results = []
        
        # 1. Total Mismatch Check
        results.append(self._check_total_mismatch(extracted))
        
        # 2. Internal Duplication Check
        results.append(self._check_internal_duplicates(extracted))
        
        # Determine overall status
        overall_status = "PASS" if all(r.passed for r in results) else "FAIL"
        
        # Create report
        report = AuditReport(invoice_id, overall_status, results)
        
        # Update invoice with audit results
        invoice.audit_status = overall_status
        invoice.audit_report = report.to_dict()
        invoice.save()
        
        return report
    
    def _check_total_mismatch(self, extracted) -> AuditResult:
        """
        Check if the sum of line items matches the grand total.
        
        Args:
            extracted: ExtractedInvoice object
            
        Returns:
            AuditResult
        """
        calculated_total = sum(item.amount for item in extracted.line_items)
        difference = abs(calculated_total - extracted.grand_total)
        
        if difference <= self.rounding_tolerance:
            return AuditResult(
                check_name="Total Mismatch Check",
                passed=True,
                message=f"Total matches: ${extracted.grand_total:.2f}",
                details={'calculated_total': calculated_total, 'invoice_total': extracted.grand_total}
            )
        else:
            return AuditResult(
                check_name="Total Mismatch Check",
                passed=False,
                message=f"Total mismatch: Calculated ${calculated_total:.2f} vs Invoice ${extracted.grand_total:.2f} (Difference: ${difference:.2f})",
                details={
                    'calculated_total': calculated_total,
                    'invoice_total': extracted.grand_total,
                    'difference': difference
                }
            )
    
    def _check_internal_duplicates(self, extracted) -> AuditResult:
        """
        Check for duplicate line items within the same invoice.
        
        Args:
            extracted: ExtractedInvoice object
            
        Returns:
            AuditResult
        """
        fingerprints = {}
        duplicates = []
        
        for idx, item in enumerate(extracted.line_items):
            fingerprint = item.fingerprint
            if fingerprint in fingerprints:
                # Found duplicate
                duplicates.append({
                    'row_number': idx + 1,
                    'candidate_id': item.candidate_id,
                    'candidate_name': item.candidate_name,
                    'service_description': item.service_description,
                    'amount': item.amount,
                    'duplicate_of_row': fingerprints[fingerprint] + 1
                })
            else:
                fingerprints[fingerprint] = idx
        
        if not duplicates:
            return AuditResult(
                check_name="Internal Duplication Check",
                passed=True,
                message="No internal duplicates found",
                details={'duplicate_count': 0}
            )
        else:
            return AuditResult(
                check_name="Internal Duplication Check",
                passed=False,
                message=f"Found {len(duplicates)} internal duplicate(s)",
                details={
                    'duplicate_count': len(duplicates),
                    'duplicates': duplicates
                }
            )
    
