from flask import Blueprint, render_template, session, redirect, url_for, request, jsonify, flash
from werkzeug.utils import secure_filename
from src.decorators import login_required
from src.services.invoice import InvoiceService
from src.services.audit import AuditService
from src.providers.enum import Provider
from src.helpers import get_provider_instance
from src.logger import get_logger
import os
import tempfile

logger = get_logger()

main_bp = Blueprint('main', __name__)

# Configure upload settings
ALLOWED_EXTENSIONS = {'pdf'}
UPLOAD_FOLDER = tempfile.gettempdir()  # Use temp directory for uploads

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@main_bp.route('/')
def index():
    if 'user' in session:
        return redirect(url_for('main.dashboard'))
    return render_template('index.html')

@main_bp.route('/dashboard')
@login_required
def dashboard():
    invoice_service = InvoiceService()
    user_email = session['user']['email']
    
    # Get pagination parameters
    try:
        page = int(request.args.get('page', 1))
        if page < 1:
            page = 1
    except (ValueError, TypeError):
        page = 1
    
    # Get filter parameters (multiselect - can have multiple values)
    statuses = request.args.getlist('status') or None
    selected_providers = request.args.getlist('provider') or None
    
    # Check if filters are active
    has_filters = (statuses and len(statuses) > 0) or (selected_providers and len(selected_providers) > 0)
    
    try:
        if has_filters:
            # When filters are active, show all results without pagination
            invoices = invoice_service.list_invoices_filtered(
                user_email=user_email,
                statuses=statuses,
                providers=selected_providers
            )
            # Create pagination data structure for template compatibility
            pagination_data = {
                'invoices': invoices,
                'total': len(invoices),
                'page': 1,
                'per_page': len(invoices),
                'total_pages': 1
            }
        else:
            # No filters: use paginated method
            pagination_data = invoice_service.list_invoices_paginated(
                user_email=user_email,
                page=page,
                per_page=10,
                statuses=statuses,
                providers=selected_providers
            )
            invoices = pagination_data['invoices']
    except Exception as e:
        logger.error(f"Error fetching invoices: {e}", exc_info=True)
        invoices = []
        pagination_data = {
            'invoices': [],
            'total': 0,
            'page': 1,
            'per_page': 10,
            'total_pages': 1
        }
    
    # Get list of all available providers from enum
    all_providers = Provider.list_all()
    
    return render_template('dashboard.html', 
                        user=session['user'],
                        invoices=invoices,
                        providers=all_providers,
                        pagination=pagination_data,
                        current_statuses=statuses or [],
                        current_providers=selected_providers or [],
                        has_filters=has_filters)

@main_bp.route('/upload', methods=['POST'])
@login_required
def upload_invoice():
    """
    Handle invoice PDF upload and processing.
    Returns JSON response for AJAX requests.
    """
    if 'file' not in request.files:
        return jsonify({
            'success': False,
            'message': 'No file provided'
        }), 400
    
    file = request.files['file']
    provider_name = request.form.get('provider_name', '').strip()
    
    if file.filename == '':
        return jsonify({
            'success': False,
            'message': 'No file selected'
        }), 400
    
    if not provider_name:
        return jsonify({
            'success': False,
            'message': 'Please select a provider'
        }), 400
    
    # Validate provider name
    try:
        Provider.from_string(provider_name)
    except ValueError:
        return jsonify({
            'success': False,
            'message': f'Invalid provider selected: {provider_name}'
        }), 400
    
    if not allowed_file(file.filename):
        return jsonify({
            'success': False,
            'message': 'Invalid file type. Only PDF files are allowed.'
        }), 400
    
    try:
        # Save uploaded file temporarily
        filename = secure_filename(file.filename)
        temp_path = os.path.join(UPLOAD_FOLDER, filename)
        file.save(temp_path)
        
        # Get provider instance
        provider = get_provider_instance(provider_name)
        if not provider:
            return jsonify({
                'success': False,
                'message': f'Provider class not found for: {provider_name}'
            }), 400
        
        # Extract invoice data once
        extracted = provider.extract(temp_path)
        
        # Process invoice
        invoice_service = InvoiceService()
        user_email = session['user']['email']
        
        invoice = invoice_service.process_invoice(
            filename=filename,
            uploaded_by=user_email,
            extracted=extracted
        )
        
        # Perform audit (reuses extracted data)
        audit_service = AuditService()
        audit_report = audit_service.audit_invoice(invoice.id, extracted=extracted)
        
        # Clean up temp file
        try:
            os.remove(temp_path)
        except:
            pass
        
        return jsonify({
            'success': True,
            'message': f'Invoice {invoice.invoice_number} processed successfully. Status: {audit_report.overall_status}',
            'invoice_number': invoice.invoice_number,
            'audit_status': audit_report.overall_status,
            'redirect_url': url_for('main.view_invoice', invoice_number=invoice.invoice_number)
        }), 200
    
    except ValueError as e:
        logger.error(f"ValueError in upload_invoice: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'message': f'Processing error: {str(e)}'
        }), 400
    except Exception as e:
        logger.error(f"Unexpected error in upload_invoice: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'message': f'Unexpected error: {str(e)}'
        }), 500

@main_bp.route('/invoice/<invoice_number>')
@login_required
def view_invoice(invoice_number):
    """
    View invoice details and audit results.
    """
    invoice_service = InvoiceService()
    invoice = invoice_service.get_by_id(invoice_number)
    
    if not invoice:
        flash('Invoice not found', 'error')
        return redirect(url_for('main.dashboard'))
    
    # Check if user owns this invoice
    if invoice.uploaded_by != session['user']['email']:
        flash('Access denied', 'error')
        return redirect(url_for('main.dashboard'))
    
    return render_template('invoice_detail.html', invoice=invoice)

