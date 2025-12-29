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
    const modal = bootstrap.Modal.getInstance(uploadModal);
    
    // Get upload URL from form data attribute
    const uploadUrl = uploadForm.getAttribute('data-upload-url');
    if (!uploadUrl) {
        console.error('Upload URL not found. Please set data-upload-url attribute on the form.');
        return;
    }
    
    uploadForm.addEventListener('submit', function(e) {
        e.preventDefault();
        
        // Hide any previous alerts
        if (uploadAlert) {
            uploadAlert.classList.add('d-none');
            uploadAlert.classList.remove('alert-success', 'alert-danger');
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
        .then(response => {
            if (!response.ok) {
                // If response is not ok, try to parse JSON error
                return response.json().then(err => {
                    throw new Error(err.message || 'Server error');
                }).catch(() => {
                    throw new Error(`HTTP error! status: ${response.status}`);
                });
            }
            return response.json();
        })
        .then(data => {
            // Hide full-page loader
            if (fullPageLoader) {
                fullPageLoader.classList.add('d-none');
            }
            
            if (data.success) {
                // Redirect to invoice detail page
                if (data.redirect_url) {
                    window.location.href = data.redirect_url;
                } else {
                    // If no redirect URL, reload the page
                    window.location.reload();
                }
            } else {
                // Hide loader and show error
                if (fullPageLoader) {
                    fullPageLoader.classList.add('d-none');
                }
                alert('Error: ' + (data.message || 'An error occurred while processing the invoice.'));
                // Reopen modal to show error if needed
                if (modal) {
                    modal.show();
                }
            }
        })
        .catch(error => {
            // Hide full-page loader
            if (fullPageLoader) {
                fullPageLoader.classList.add('d-none');
            }
            
            // Show error alert
            alert('Error: ' + (error.message || 'An error occurred while processing the invoice. Please try again.'));
            console.error('Error:', error);
            
            // Reopen modal if needed
            if (modal) {
                modal.show();
            }
        });
    });
    
    // Reset form when modal is closed
    if (uploadModal) {
        uploadModal.addEventListener('hidden.bs.modal', function() {
            uploadForm.reset();
            if (uploadAlert) {
                uploadAlert.classList.add('d-none');
                uploadAlert.classList.remove('alert-success', 'alert-danger');
            }
            if (submitBtn) submitBtn.disabled = false;
            if (cancelBtn) cancelBtn.disabled = false;
        });
    }
});

