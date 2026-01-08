import os

class Config:
    # Security
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key')
    
    # Google OAuth
    GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID')
    GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET')
    
    # Allow HTTP for OAuth locally (Remove this in production if using HTTPS)
    OAUTHLIB_INSECURE_TRANSPORT = os.environ.get('OAUTHLIB_INSECURE_TRANSPORT', '0')
    DB_ROOT_PATH = "workspaces/bgv-audit"
    
    # File upload configuration
    # Set max content length to 50MB (for large PDF files)
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB in bytes
    
    # OCR processing configuration
    # Number of pages to process in each batch during OCR (default: 3)
    # Lower values use less memory but are slower. Higher values are faster but use more memory.
    OCR_BATCH_SIZE = int(os.environ.get('OCR_BATCH_SIZE', '3'))
    
    # DPI for OCR image conversion (default: 200)
    # Lower DPI (e.g., 200) uses ~55% less memory and is ~30% faster, but may reduce accuracy for small text
    # Higher DPI (e.g., 300) provides better accuracy but uses more memory
    # Recommended: 200 for most invoices, 300 for small text or poor quality scans
    OCR_DPI = int(os.environ.get('OCR_DPI', '200'))

