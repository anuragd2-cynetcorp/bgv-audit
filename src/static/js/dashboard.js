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
    
    // Filter management for multi-select with tags
    const statusCheckboxes = document.querySelectorAll('.status-checkbox');
    const statusTags = document.getElementById('statusTags');
    const statusPlaceholder = document.getElementById('statusPlaceholder');
    
    const providerCheckboxes = document.querySelectorAll('.provider-checkbox');
    const providerTags = document.getElementById('providerTags');
    const providerPlaceholder = document.getElementById('providerPlaceholder');
    
    const hiddenInputs = document.getElementById('hiddenInputs');
    
    // Status badge colors
    const statusColors = {
        'PASS': 'success',
        'FAIL': 'danger',
        'PENDING': 'warning text-dark'
    };
    
    // Update hidden inputs and tags
    function updateFilters() {
        if (!hiddenInputs) return;
        
        // Clear hidden inputs
        hiddenInputs.innerHTML = '';
        
        // Get selected statuses
        const selectedStatuses = Array.from(statusCheckboxes)
            .filter(cb => cb.checked)
            .map(cb => cb.value);
        
        // Get selected providers
        const selectedProviders = Array.from(providerCheckboxes)
            .filter(cb => cb.checked)
            .map(cb => cb.value);
        
        // Update status tags
        if (statusTags) {
            updateTags(statusTags, selectedStatuses, statusColors, 'status');
        }
        
        // Update provider tags
        if (providerTags) {
            updateTags(providerTags, selectedProviders, {}, 'provider');
        }
        
        // Update placeholders
        if (statusPlaceholder) {
            statusPlaceholder.textContent = selectedStatuses.length > 0 
                ? `${selectedStatuses.length} selected` 
                : 'Select Status';
        }
        if (providerPlaceholder) {
            providerPlaceholder.textContent = selectedProviders.length > 0 
                ? `${selectedProviders.length} selected` 
                : 'Select Provider';
        }
        
        // Add hidden inputs for form submission
        selectedStatuses.forEach(status => {
            const input = document.createElement('input');
            input.type = 'hidden';
            input.name = 'status';
            input.value = status;
            hiddenInputs.appendChild(input);
        });
        
        selectedProviders.forEach(provider => {
            const input = document.createElement('input');
            input.type = 'hidden';
            input.name = 'provider';
            input.value = provider;
            hiddenInputs.appendChild(input);
        });
    }
    
    // Update tags display
    function updateTags(container, values, colors, type) {
        container.innerHTML = '';
        values.forEach(value => {
            const colorClass = colors[value] || 'primary';
            const tag = document.createElement('span');
            tag.className = `badge bg-${colorClass} d-flex align-items-center gap-1 ${type}-tag`;
            tag.setAttribute('data-value', value);
            tag.innerHTML = `${value} <button type="button" class="btn-close btn-close-white" aria-label="Remove"></button>`;
            
            // Remove tag on close button click
            tag.querySelector('.btn-close').addEventListener('click', function(e) {
                e.stopPropagation();
                const checkbox = document.querySelector(`.${type}-checkbox[value="${value}"]`);
                if (checkbox) {
                    checkbox.checked = false;
                    updateFilters();
                }
            });
            
            container.appendChild(tag);
        });
    }
    
    // Prevent dropdown from closing when clicking checkboxes
    document.querySelectorAll('.dropdown-menu').forEach(menu => {
        menu.addEventListener('click', function(e) {
            if (e.target.type === 'checkbox' || e.target.closest('.form-check')) {
                e.stopPropagation();
            }
        });
    });
    
    // Handle checkbox changes
    statusCheckboxes.forEach(checkbox => {
        checkbox.addEventListener('change', updateFilters);
    });
    
    providerCheckboxes.forEach(checkbox => {
        checkbox.addEventListener('change', updateFilters);
    });
    
    // Initialize filters on page load
    if (statusCheckboxes.length > 0 || providerCheckboxes.length > 0) {
        updateFilters();
    }
});

