/**
 * Dashboard JavaScript for invoice upload functionality
 */
document.addEventListener('DOMContentLoaded', function() {
    const uploadForm = document.getElementById('uploadForm');
    if (!uploadForm) {
        return; // Form not found, exit early
    }
    
    const uploadAlert = document.getElementById('uploadAlert');
    const fullPageLoader = document.getElementById('fullPageLoader');
    const submitBtn = document.getElementById('submitBtn');
    const cancelBtn = document.getElementById('cancelBtn');
    const uploadModal = document.getElementById('uploadModal');
    // Get or create modal instance - getInstance returns null if modal hasn't been initialized
    const modal = uploadModal ? (bootstrap.Modal.getInstance(uploadModal) || new bootstrap.Modal(uploadModal)) : null;
    
    // Get upload URL from form data attribute
    const uploadUrl = uploadForm.getAttribute('data-upload-url');
    if (!uploadUrl) {
        console.error('Upload URL not found. Please set data-upload-url attribute on the form.');
        return;
    }
    
    uploadForm.addEventListener('submit', function(e) {
        e.preventDefault();
        
        // Disable submit and cancel buttons to prevent multiple submissions
        if (submitBtn) {
            submitBtn.disabled = true;
            const originalText = submitBtn.innerHTML;
            submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Processing...';
            submitBtn.dataset.originalText = originalText;
        }
        if (cancelBtn) {
            cancelBtn.disabled = true;
        }
        
        // Hide any previous alerts
        if (uploadAlert) {
            uploadAlert.classList.add('d-none');
            uploadAlert.classList.remove('alert-success', 'alert-danger', 'show');
            const alertContent = document.getElementById('uploadAlertContent');
            if (alertContent) {
                alertContent.innerHTML = '';
            }
        }
        
        // Close modal immediately
        if (modal) {
            modal.hide();
        }
        
        // Show full-page loader
        if (fullPageLoader) {
            fullPageLoader.classList.remove('d-none');
        }
        
        // Create FormData
        const formData = new FormData(uploadForm);
        
        // Make AJAX request
        fetch(uploadUrl, {
            method: 'POST',
            body: formData,
            headers: {
                'X-Requested-With': 'XMLHttpRequest'
            }
        })
        .then(async response => {
            if (!response.ok) {
                // Try to parse JSON error first
                let errorData = null;
                try {
                    errorData = await response.json();
                } catch (e) {
                    // If JSON parsing fails, try to get text
                    try {
                        const text = await response.text();
                        errorData = { message: text || 'An error occurred while processing the invoice.' };
                    } catch (e2) {
                        // If both fail, use a user-friendly default
                        errorData = { message: 'An error occurred while processing the invoice. Please try again.' };
                    }
                }
                
                // Get provider name from form as fallback
                const providerName = errorData.provider_name || uploadForm.querySelector('#provider_name')?.value || '';
                
                const error = new Error(errorData.message || 'An error occurred while processing the invoice.');
                error.providerName = providerName;
                error.isExtractionError = errorData.is_extraction_error !== undefined ? errorData.is_extraction_error : true;
                throw error;
            }
            return response.json();
        })
        .then(data => {
            if (data.success) {
                // Redirect to invoice detail page
                // Keep loader visible during redirect to prevent flash of content
                if (data.redirect_url) {
                    window.location.href = data.redirect_url;
                } else {
                    // If no redirect URL, reload the page
                    // Hide loader before reload since we're staying on same page
                    if (fullPageLoader) {
                        fullPageLoader.classList.add('d-none');
                    }
                    window.location.reload();
                }
            } else {
                // Hide loader and show error
                if (fullPageLoader) {
                    fullPageLoader.classList.add('d-none');
                }
                // Re-enable buttons on error
                if (submitBtn) {
                    submitBtn.disabled = false;
                    submitBtn.innerHTML = submitBtn.dataset.originalText || '<i class="bi bi-upload me-2"></i>Upload & Process';
                }
                if (cancelBtn) {
                    cancelBtn.disabled = false;
                }
                
                // Clean up error message
                let errorMessage = data.message || 'An error occurred while processing the invoice.';
                errorMessage = errorMessage.replace(/^Error:\s*/i, '').trim();
                
                // Show error in modal first
                showErrorInModal(errorMessage, data.provider_name, data.is_extraction_error);
                
                // Reopen modal to show error
                if (uploadModal) {
                    // Get or create modal instance
                    let errorModal = bootstrap.Modal.getInstance(uploadModal);
                    if (!errorModal) {
                        errorModal = new bootstrap.Modal(uploadModal, {
                            backdrop: true,
                            keyboard: true
                        });
                    }
                    
                    // Wait for any ongoing hide animation to complete, then show
                    setTimeout(() => {
                        // Ensure modal is fully hidden first
                        uploadModal.classList.remove('show');
                        document.body.classList.remove('modal-open');
                        const backdrop = document.querySelector('.modal-backdrop');
                        if (backdrop) {
                            backdrop.remove();
                        }
                        
                        // Now show the modal with error
                        errorModal.show();
                    }, 300);
                }
            }
        })
        .catch(error => {
            // Hide full-page loader
            if (fullPageLoader) {
                fullPageLoader.classList.add('d-none');
            }
            
            // Re-enable buttons on error
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.innerHTML = submitBtn.dataset.originalText || '<i class="bi bi-upload me-2"></i>Upload & Process';
            }
            if (cancelBtn) {
                cancelBtn.disabled = false;
            }
            
            // Get provider name from error object or form
            const providerName = error.providerName || uploadForm.querySelector('#provider_name')?.value || '';
            const isExtractionError = error.isExtractionError !== undefined ? error.isExtractionError : true;
            
            // Show user-friendly error message (never show generic HTTP errors)
            let errorMessage = error.message || 'An error occurred while processing the invoice. Please try again.';
            
            // Remove "Error: " prefix if it exists (to avoid duplication)
            errorMessage = errorMessage.replace(/^Error:\s*/i, '').trim();
            
            // Replace generic HTTP error messages with user-friendly ones
            if (errorMessage.includes('HTTP error!') || errorMessage.includes('status:')) {
                errorMessage = 'An error occurred while processing the invoice. Please check your file and try again.';
            }
            
            // Show error in modal first
            showErrorInModal(errorMessage, providerName, isExtractionError);
            console.error('Error:', error);
            
            // Reopen modal to show error
            if (uploadModal) {
                // Get or create modal instance
                let errorModal = bootstrap.Modal.getInstance(uploadModal);
                if (!errorModal) {
                    errorModal = new bootstrap.Modal(uploadModal, {
                        backdrop: true,
                        keyboard: true
                    });
                }
                
                // Wait for any ongoing hide animation to complete, then show
                setTimeout(() => {
                    // Ensure modal is fully hidden first
                    uploadModal.classList.remove('show');
                    document.body.classList.remove('modal-open');
                    const backdrop = document.querySelector('.modal-backdrop');
                    if (backdrop) {
                        backdrop.remove();
                    }
                    
                    // Now show the modal with error
                    errorModal.show();
                }, 300);
            }
        });
    
    // Function to show error message in modal alert
    function showErrorInModal(message, providerName, isExtractionError) {
        if (!uploadAlert) return;
        
        const alertContent = document.getElementById('uploadAlertContent');
        if (!alertContent) return;
        
        let errorMessage = message;
        
        // If it's an extraction error and we have a provider name, show enhanced message
        if (isExtractionError && providerName) {
            errorMessage = `
                <div class="mb-2">
                    <strong>Unable to process invoice for ${providerName}.</strong>
                </div>
                <div class="mb-2">
                    ${message}
                </div>
                <div class="mt-3">
                    <strong>Possible reasons:</strong>
                    <ul class="mb-0 mt-2">
                        <li>You may have selected the wrong provider for this PDF</li>
                        <li>The invoice format may have been changed by ${providerName}</li>
                        <li>The PDF may be a scanned image (not text-searchable)</li>
                    </ul>
                </div>
            `;
        } else if (providerName) {
            // For other errors, still mention the provider if available
            errorMessage = `
                <div class="mb-2">
                    <strong>Error processing invoice for ${providerName}:</strong>
                </div>
                <div>${message}</div>
            `;
        }
        
        // Set the error message content
        alertContent.innerHTML = errorMessage;
        
        // Make sure alert is visible
        uploadAlert.classList.remove('d-none', 'alert-success');
        uploadAlert.classList.add('alert-danger', 'show');
        
        // Force display to ensure it's visible
        uploadAlert.style.display = 'block';
    }
    });
    
    // Reset form when modal is closed
    if (uploadModal) {
        uploadModal.addEventListener('hidden.bs.modal', function() {
            uploadForm.reset();
            if (uploadAlert) {
                uploadAlert.classList.add('d-none');
                uploadAlert.classList.remove('alert-success', 'alert-danger', 'show');
                const alertContent = document.getElementById('uploadAlertContent');
                if (alertContent) {
                    alertContent.innerHTML = '';
                }
            }
            if (submitBtn) submitBtn.disabled = false;
            if (cancelBtn) cancelBtn.disabled = false;
        });
    }
});

