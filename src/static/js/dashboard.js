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
    const loaderRotatingText = document.getElementById('loaderRotatingText');
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

    // ---- Full-page loader engagement (rotating text + timing stats) ----
    let stopLoaderEngagement = null;

    function setLoaderRotatingText(text) {
        if (!loaderRotatingText) return;
        loaderRotatingText.classList.remove('is-animating');
        // Trigger reflow so animation restarts
        // eslint-disable-next-line no-unused-expressions
        loaderRotatingText.offsetHeight;
        loaderRotatingText.textContent = text;
        loaderRotatingText.classList.add('is-animating');
    }

    function formatElapsed(ms) {
        const totalSeconds = Math.max(0, Math.floor(ms / 1000));
        const minutes = Math.floor(totalSeconds / 60);
        const seconds = totalSeconds % 60;
        return `${minutes}:${String(seconds).padStart(2, '0')}`;
    }

    function startLoaderEngagementLoop({ providerName, filename }) {
        // Fixed expectation: assume max ~5 minutes
        const expectedMaxMs = 5 * 60 * 1000;
        const startedAt = performance.now();

        const friendlyProvider = providerName ? ` (${providerName})` : '';
        const friendlyFile = filename ? ` • ${filename}` : '';

        const milestones = [
            { ms: 0, msg: `Uploading PDF${friendlyProvider}${friendlyFile}...` },
            { ms: 10_000, msg: `Reading invoice text${friendlyProvider}...` },
            { ms: 45_000, msg: `Extracting line items${friendlyProvider}...` },
            { ms: 120_000, msg: `Auditing totals & duplicates...` },
            { ms: 210_000, msg: `If needed, verifying via OCR...` },
            { ms: 270_000, msg: `Still working — this can take a few minutes...` }
        ];

        let nextIdx = 0;
        let stopped = false;

        setLoaderRotatingText(milestones[0].msg);

        const tick = () => {
            if (stopped) return;
            const elapsed = performance.now() - startedAt;

            while (nextIdx + 1 < milestones.length && elapsed >= milestones[nextIdx + 1].ms) {
                nextIdx += 1;
                setLoaderRotatingText(milestones[nextIdx].msg);
            }

            // If we exceed expected max, keep user informed without spamming.
            if (elapsed > expectedMaxMs && nextIdx === milestones.length - 1) {
                // no-op; last milestone already covers "still working"
            }
        };

        const intervalId = window.setInterval(tick, 500);

        // Return a stopper
        return ({ finalText } = {}) => {
            stopped = true;
            window.clearInterval(intervalId);
            if (finalText) {
                setLoaderRotatingText(finalText);
            }
        };
    }
    
    // Track if form submission is in progress to prevent multiple submissions
    let isSubmitting = false;
    
    uploadForm.addEventListener('submit', function(e) {
        e.preventDefault();
        
        // PREVENT MULTIPLE SUBMISSIONS: Check if already submitting
        if (isSubmitting) {
            console.warn('Form submission already in progress. Ignoring duplicate submission.');
            return false;
        }
        
        // Mark as submitting immediately
        isSubmitting = true;

        const providerName = uploadForm.querySelector('#provider_name')?.value || '';
        const fileInput = uploadForm.querySelector('#file');
        const filename = fileInput?.files?.[0]?.name || '';
        const startedAt = performance.now();
        
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
        
        // Disable form inputs to prevent changes during submission
        const formInputs = uploadForm.querySelectorAll('input, select, button[type="submit"]');
        formInputs.forEach(input => {
            if (input.id !== 'cancelBtn') { // Keep cancel enabled for now (it's handled separately)
                input.disabled = true;
            }
        });
        
        // Hide any previous alerts
        hideErrorInModal();
        
        // Close modal immediately
        if (modal) {
            modal.hide();
        }
        
        // Show full-page loader
        if (fullPageLoader) {
            fullPageLoader.classList.remove('d-none');
        }

        // Start loader engagement loop (rotating text + stats)
        if (typeof stopLoaderEngagement === 'function') {
            stopLoaderEngagement({ finalText: 'Starting...' });
        }
        stopLoaderEngagement = startLoaderEngagementLoop({ providerName, filename });
        
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
                if (typeof stopLoaderEngagement === 'function') {
                    stopLoaderEngagement({ finalText: 'Done. Opening invoice…' });
                }

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
                if (typeof stopLoaderEngagement === 'function') {
                    stopLoaderEngagement();
                }
                // Reset submission flag on error
                isSubmitting = false;
                
                // Re-enable buttons on error
                if (submitBtn) {
                    submitBtn.disabled = false;
                    submitBtn.innerHTML = submitBtn.dataset.originalText || '<i class="bi bi-upload me-2"></i>Upload & Process';
                }
                if (cancelBtn) {
                    cancelBtn.disabled = false;
                }
                
                // Re-enable form inputs (except buttons which are handled separately)
                const formInputs = uploadForm.querySelectorAll('input[type="file"], select');
                formInputs.forEach(input => {
                    input.disabled = false;
                });
                
                // Clean up error message
                let errorMessage = data.message || 'An error occurred while processing the invoice.';
                errorMessage = errorMessage.replace(/^Error:\s*/i, '').trim();
                
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
                        
                        // Show the modal first
                        errorModal.show();
                        
                        // Set error message after modal is fully shown
                        uploadModal.addEventListener('shown.bs.modal', function showErrorAfterModal() {
                            showErrorInModal(errorMessage, data.provider_name, data.is_extraction_error);
                            // Remove listener after use
                            uploadModal.removeEventListener('shown.bs.modal', showErrorAfterModal);
                        }, { once: true });
                    }, 300);
                }
            }
        })
        .catch(error => {
            // Reset submission flag on error
            isSubmitting = false;
            
            // Hide full-page loader
            if (fullPageLoader) {
                fullPageLoader.classList.add('d-none');
            }
            if (typeof stopLoaderEngagement === 'function') {
                stopLoaderEngagement();
            }
            
            // Re-enable buttons on error
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.innerHTML = submitBtn.dataset.originalText || '<i class="bi bi-upload me-2"></i>Upload & Process';
            }
            if (cancelBtn) {
                cancelBtn.disabled = false;
            }
            
            // Re-enable form inputs
            const formInputs = uploadForm.querySelectorAll('input[type="file"], select');
            formInputs.forEach(input => {
                input.disabled = false;
            });
            
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
                    
                    // Show the modal first
                    errorModal.show();
                    
                    // Set error message after modal is fully shown
                    uploadModal.addEventListener('shown.bs.modal', function showErrorAfterModal() {
                        showErrorInModal(errorMessage, providerName, isExtractionError);
                        // Remove listener after use
                        uploadModal.removeEventListener('shown.bs.modal', showErrorAfterModal);
                    }, { once: true });
                }, 300);
            }
        }); // End of fetch promise chain
    }); // End of submit event listener
    
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
        
        // Show the alert
        uploadAlert.classList.remove('d-none', 'alert-success');
        uploadAlert.classList.add('alert-danger');
    }
    
    // Function to hide error alert
    function hideErrorInModal() {
        if (!uploadAlert) return;
        uploadAlert.classList.add('d-none');
        uploadAlert.classList.remove('alert-danger', 'alert-success');
        const alertContent = document.getElementById('uploadAlertContent');
        if (alertContent) {
            alertContent.innerHTML = '';
        }
    }
    
    // Hide alert when modal is opened normally (user clicks upload button)
    if (uploadModal) {
        uploadModal.addEventListener('show.bs.modal', function() {
            // Hide alert when modal opens (unless we're about to show an error)
            // We'll show it explicitly if there's an error
            hideErrorInModal();
        });
        
        uploadModal.addEventListener('hidden.bs.modal', function() {
            // Reset form and submission state when modal is closed
            uploadForm.reset();
            hideErrorInModal();
            isSubmitting = false; // Reset submission flag
            
            // Re-enable all form elements
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.innerHTML = submitBtn.dataset.originalText || '<i class="bi bi-upload me-2"></i>Upload & Process';
            }
            if (cancelBtn) {
                cancelBtn.disabled = false;
            }
            
            // Re-enable all form inputs
            const formInputs = uploadForm.querySelectorAll('input, select, button[type="submit"]');
            formInputs.forEach(input => {
                input.disabled = false;
            });
        });
    }
});

