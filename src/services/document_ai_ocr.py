"""
Service for Google Cloud Document AI OCR processing.
Replaces Tesseract OCR to eliminate memory issues and improve accuracy.
"""
from typing import List
import os
from google.cloud import documentai
from google.api_core.client_options import ClientOptions
from src.config import Config
from src.logger import get_logger

logger = get_logger()


class DocumentAIOCRService:
    """
    Service for extracting text from PDFs using Google Cloud Document AI OCR.
    This eliminates local memory issues and provides better accuracy for invoices.
    """
    
    def __init__(self):
        """Initialize the Document AI OCR service."""
        self.project_id = self._get_project_id()
        self.location = Config.DOCUMENT_AI_LOCATION
        self.processor_id = Config.DOCUMENT_AI_PROCESSOR_ID
        
        # Initialize the client with proper endpoint (matching rules-actions-django pattern)
        opts = ClientOptions(api_endpoint=f"{self.location}-documentai.googleapis.com")
        self.client = documentai.DocumentProcessorServiceClient(client_options=opts)
        
        # Get processor name (required - matching rules-actions-django pattern)
        if not self.processor_id:
            raise ValueError(
                "DOCUMENT_AI_PROCESSOR_ID is required. "
                "Please set DOCUMENT_AI_PROCESSOR_ID environment variable. "
                "You can create an OCR processor at: "
                "https://console.cloud.google.com/ai/document-ai/processors"
            )
        
        # Build processor path (matching rules-actions-django pattern)
        self.processor_name = self.client.processor_path(
            self.project_id, self.location, self.processor_id
        )
        logger.info(f"Document AI initialized: project={self.project_id}, location={self.location}, processor={self.processor_id}")
    
    def _get_project_id(self) -> str:
        """
        Get the GCP project ID from environment or credentials.
        
        Returns:
            Project ID string
            
        Raises:
            ValueError: If project ID cannot be determined
        """
        # First check environment variable
        if Config.DOCUMENT_AI_PROJECT_ID:
            return Config.DOCUMENT_AI_PROJECT_ID
        
        # Try to get from GOOGLE_APPLICATION_CREDENTIALS
        creds_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
        if creds_path and os.path.exists(creds_path):
            import json
            try:
                with open(creds_path, 'r') as f:
                    creds = json.load(f)
                    if 'project_id' in creds:
                        return creds['project_id']
            except Exception as e:
                logger.warning(f"Could not read project_id from credentials: {e}")
        
        # Try to get from gcloud config
        try:
            import subprocess
            result = subprocess.run(
                ['gcloud', 'config', 'get-value', 'project'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception as e:
            logger.warning(f"Could not get project from gcloud: {e}")
        
        raise ValueError(
            "Could not determine GCP project ID. Set DOCUMENT_AI_PROJECT_ID environment variable."
        )
    
    
    def extract_text_lines(self, pdf_path: str) -> List[str]:
        """
        Extract text lines from a PDF using Document AI OCR.
        
        Args:
            pdf_path: Path to the PDF file
            
        Returns:
            List of text lines extracted from the PDF
            
        Raises:
            ValueError: If processing fails
            FileNotFoundError: If PDF file doesn't exist
        """
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")
        
        try:
            # Read the PDF file
            with open(pdf_path, "rb") as pdf_file:
                pdf_content = pdf_file.read()
            
            logger.info(f"Processing PDF with Document AI OCR: {pdf_path} ({len(pdf_content)} bytes)")
            
            # Configure the process request (matching rules-actions-django pattern)
            request = documentai.ProcessRequest(
                name=self.processor_name,
                raw_document=documentai.RawDocument(
                    content=pdf_content,
                    mime_type="application/pdf"
                ),
                skip_human_review=True  # Matching rules-actions-django pattern
            )
            
            # Process the document
            result = self.client.process_document(request=request)
            document = result.document
            
            # Extract text lines from the document
            all_lines = []
            
            # Document AI provides text in pages with layout information
            # We'll extract text line by line maintaining the order
            for page in document.pages:
                # Extract lines from the page
                for line in page.lines:
                    # Get text for this line
                    line_text = self._layout_to_text(line.layout, document.text)
                    if line_text and line_text.strip():
                        all_lines.append(line_text.strip())
            
            # If no lines found via page.lines, fall back to extracting paragraphs
            if not all_lines:
                logger.warning("No lines found, extracting paragraphs instead")
                for page in document.pages:
                    for paragraph in page.paragraphs:
                        para_text = self._layout_to_text(paragraph.layout, document.text)
                        if para_text and para_text.strip():
                            # Split paragraph into lines
                            para_lines = para_text.strip().split('\n')
                            all_lines.extend([line.strip() for line in para_lines if line.strip()])
            
            # If still no lines, extract from full text
            if not all_lines and document.text:
                logger.warning("No structured lines found, using full text extraction")
                all_lines = [line.strip() for line in document.text.split('\n') if line.strip()]
            
            logger.info(f"Document AI OCR extracted {len(all_lines)} text lines from PDF")
            return all_lines
            
        except Exception as e:
            logger.error(f"Error during Document AI OCR extraction: {str(e)}", exc_info=True)
            raise ValueError(f"Document AI OCR extraction failed: {str(e)}")
    
    def _layout_to_text(self, layout: documentai.Document.Page.Layout, full_text: str) -> str:
        """
        Convert Document AI layout to text string.
        
        Args:
            layout: Document AI layout object
            full_text: Full document text
            
        Returns:
            Text string for the layout
        """
        if not layout.text_anchor or not layout.text_anchor.text_segments:
            return ""
        
        # Extract text segments
        text_parts = []
        for segment in layout.text_anchor.text_segments:
            start_index = int(segment.start_index) if segment.start_index else 0
            end_index = int(segment.end_index) if segment.end_index else len(full_text)
            text_parts.append(full_text[start_index:end_index])
        
        return "".join(text_parts)

