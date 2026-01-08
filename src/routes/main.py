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
# Use NamedTemporaryFile for more reliable cross-platform temp file handling

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
    
    try:
        pagination_data = invoice_service.list_invoices_paginated(
            user_email=user_email,
            page=page,
            per_page=10
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
                        pagination=pagination_data)

@main_bp.route('/upload', methods=['POST'])
@login_required
def upload_invoice():
    """
    Handle invoice PDF upload and processing.
    Returns JSON response for AJAX requests.
    """
    # Enhanced logging for debugging file upload issues
    logger.info(f"Upload request received. Content-Type: {request.content_type}")
    logger.info(f"Request method: {request.method}")
    logger.info(f"Request content length: {request.content_length}")
    logger.info(f"Request files keys: {list(request.files.keys())}")
    logger.info(f"Request files dict: {dict(request.files)}")
    logger.info(f"Request form keys: {list(request.form.keys())}")
    logger.info(f"Request form dict: {dict(request.form)}")
    logger.info(f"Request headers: {dict(request.headers)}")
    
    # Warn if Content-Type doesn't match (but don't fail - Cloud Run proxy might modify it)
    if not request.content_type or 'multipart/form-data' not in request.content_type:
        logger.warning(f"Content-Type may be incorrect: {request.content_type}. Expected multipart/form-data")
        # Don't fail here - continue to check if files are present
    
    # Check if request.files is empty (might indicate parsing issue)
    if not request.files:
        logger.error("request.files is completely empty - multipart data may not be parsed correctly")
        logger.error(f"Request has_data: {request.data is not None}, data length: {len(request.data) if request.data else 0}")
        return jsonify({
            'success': False,
            'message': 'File upload failed. Please ensure the file is selected and try again.'
        }), 400
    
    # Check if file is in request
    if 'file' not in request.files:
        logger.warning("'file' key not found in request.files")
        logger.warning(f"Available keys in request.files: {list(request.files.keys())}")
        # Try to get the first file if 'file' key doesn't exist
        if request.files:
            first_key = list(request.files.keys())[0]
            logger.warning(f"Found file with key '{first_key}' instead of 'file'")
            # Use the first available file
            file = request.files[first_key]
        else:
            return jsonify({
                'success': False,
                'message': 'No file provided'
            }), 400
    else:
        file = request.files['file']
    
    provider_name = request.form.get('provider_name', '').strip()
    
    # Check if file was actually selected
    if file.filename == '' or not file.filename:
        logger.warning("File filename is empty")
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
    
    # Use NamedTemporaryFile for reliable cross-platform temp file handling
    temp_file = None
    temp_path = None
    
    try:
        # Save uploaded file to a temporary file
        filename = secure_filename(file.filename)
        # Use NamedTemporaryFile which handles permissions and cleanup better
        # delete=False because we need to keep it until processing is done
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
        temp_path = temp_file.name
        file.save(temp_path)
        temp_file.close()  # Close the file handle so pdfplumber can open it
        logger.info(f"File saved to temporary path: {temp_path}")
        
        # Get provider instance
        provider = get_provider_instance(provider_name)
        if not provider:
            return jsonify({
                'success': False,
                'message': f'Provider class not found for: {provider_name}'
            }), 400
        
        # Extract invoice data once
        try:
            extracted = provider.extract(temp_path)
        except Exception as e:
            logger.error(f"Error extracting invoice data: {str(e)}", exc_info=True)
            # Clean up temp file
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception as cleanup_error:
                    logger.warning(f"Error cleaning up temp file: {cleanup_error}")
            return jsonify({
                'success': False,
                'message': 'Unable to extract data from the invoice PDF.',
                'provider_name': provider_name,
                'is_extraction_error': True
            }), 400
        
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
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
                logger.info(f"Temporary file cleaned up: {temp_path}")
            except Exception as cleanup_error:
                logger.warning(f"Error cleaning up temp file: {cleanup_error}")
        
        return jsonify({
            'success': True,
            'message': f'Invoice {invoice.invoice_number} processed successfully. Status: {audit_report.overall_status}',
            'invoice_number': invoice.invoice_number,
            'audit_status': audit_report.overall_status,
            'redirect_url': url_for('main.view_invoice', invoice_id=invoice.id)
        }), 200
    
    except ValueError as e:
        logger.error(f"ValueError in upload_invoice: {str(e)}", exc_info=True)
        # Clean up temp file on error
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except:
                pass
        return jsonify({
            'success': False,
            'message': f'Processing error: {str(e)}',
            'provider_name': provider_name
        }), 400
    except Exception as e:
        logger.error(f"Unexpected error in upload_invoice: {str(e)}", exc_info=True)
        # Clean up temp file on error
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except:
                pass
        return jsonify({
            'success': False,
            'message': f'Unexpected error: {str(e)}',
            'provider_name': provider_name
        }), 500

@main_bp.route('/invoice/<invoice_id>')
@login_required
def view_invoice(invoice_id):
    """
    View invoice details and audit results.
    """
    invoice_service = InvoiceService()
    invoice = invoice_service.get_by_id(invoice_id)
    
    if not invoice:
        flash('Invoice not found', 'error')
        return redirect(url_for('main.dashboard'))
    
    # Check if user owns this invoice
    if invoice.uploaded_by != session['user']['email']:
        flash('Access denied', 'error')
        return redirect(url_for('main.dashboard'))
    
    return render_template('invoice_detail.html', invoice=invoice)

