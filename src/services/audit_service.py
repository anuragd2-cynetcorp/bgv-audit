"""
Service for auditing invoices and detecting discrepancies.
"""
from typing import Dict, List
from src.models import Invoice
from src.services.invoice_service import InvoiceService, LineItemFingerprintService
from src.providers.provider_registry import get_registry


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
    3. Historical Duplication Check
    """
    
    def __init__(self):
        self.invoice_service = InvoiceService()
        self.fingerprint_service = LineItemFingerprintService()
        self.provider_registry = get_registry()
        self.rounding_tolerance = 0.01  # $0.01 tolerance for rounding differences
    
    def audit_invoice(self, invoice_id: str, pdf_path: str) -> AuditReport:
        """
        Perform complete audit on an invoice.
        
        Args:
            invoice_id: Invoice document ID (invoice number)
            pdf_path: Path to the original PDF file
            
        Returns:
            AuditReport object
        """
        # Get invoice
        invoice = self.invoice_service.get_by_id(invoice_id)
        if not invoice:
            raise ValueError(f"Invoice {invoice_id} not found")
        
        # Re-extract invoice data (we need line items for audit)
        extracted = self.provider_registry.extract_invoice(pdf_path, invoice.provider_name)
        
        # Perform all audit checks
        results = []
        
        # 1. Total Mismatch Check
        results.append(self._check_total_mismatch(extracted))
        
        # 2. Internal Duplication Check
        results.append(self._check_internal_duplicates(extracted))
        
        # 3. Historical Duplication Check
        results.append(self._check_historical_duplicates(extracted, invoice_id))
        
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
        calculated_total = sum(item.cost for item in extracted.line_items)
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
            fingerprint = item.fingerprint()
            if fingerprint in fingerprints:
                # Found duplicate
                duplicates.append({
                    'row_number': idx + 1,
                    'candidate_id': item.candidate_id,
                    'service_description': item.service_description,
                    'cost': item.cost,
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
    
    def _check_historical_duplicates(self, extracted, invoice_id: str) -> AuditResult:
        """
        Check if line items have been billed in previous invoices.
        
        Args:
            extracted: ExtractedInvoice object
            invoice_id: Current invoice ID
            
        Returns:
            AuditResult
        """
        historical_duplicates = []
        
        for idx, item in enumerate(extracted.line_items):
            # Use the same fingerprint format as in invoice_service
            fingerprint_id = item.fingerprint().replace('|', '__')
            existing = self.fingerprint_service.get_by_id(fingerprint_id)
            
            duplicate = None
            if existing and existing.invoice_id != invoice_id:
                duplicate = existing
            
            if duplicate:
                historical_duplicates.append({
                    'row_number': idx + 1,
                    'candidate_id': item.candidate_id,
                    'service_description': item.service_description,
                    'cost': item.cost,
                    'previously_billed_in': duplicate.invoice_number,
                    'previous_invoice_date': duplicate.processed_date.isoformat() if duplicate.processed_date else None
                })
        
        if not historical_duplicates:
            return AuditResult(
                check_name="Historical Duplication Check",
                passed=True,
                message="No historical duplicates found",
                details={'duplicate_count': 0}
            )
        else:
            return AuditResult(
                check_name="Historical Duplication Check",
                passed=False,
                message=f"Found {len(historical_duplicates)} historical duplicate(s)",
                details={
                    'duplicate_count': len(historical_duplicates),
                    'duplicates': historical_duplicates
                }
            )

