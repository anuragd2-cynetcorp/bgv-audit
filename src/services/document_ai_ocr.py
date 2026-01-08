"""
Service for Google Cloud Document AI OCR processing.
Replaces Tesseract OCR to eliminate memory issues and improve accuracy.
"""
from typing import List
import os
import re
import tempfile
import PyPDF2
from google.cloud import documentai
from google.api_core.client_options import ClientOptions
from google.oauth2 import service_account
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
        
        # DOCUMENT_AI_CREDENTIALS is required - no fallback
        documentai_creds_path = os.environ.get('DOCUMENT_AI_CREDENTIALS')
        if not documentai_creds_path:
            raise ValueError(
                "DOCUMENT_AI_CREDENTIALS environment variable is required. "
                "Please set DOCUMENT_AI_CREDENTIALS to the path of your Document AI service account JSON file."
            )
        
        if not os.path.exists(documentai_creds_path):
            raise FileNotFoundError(
                f"Document AI credentials file not found: {documentai_creds_path}. "
                "Please ensure DOCUMENT_AI_CREDENTIALS points to a valid service account JSON file."
            )
        
        # Load credentials from Document AI specific file
        credentials = service_account.Credentials.from_service_account_file(documentai_creds_path)
        logger.info(f"Using Document AI credentials from: {documentai_creds_path}")
        
        # Initialize the client with proper endpoint
        opts = ClientOptions(api_endpoint=f"{self.location}-documentai.googleapis.com")
        self.client = documentai.DocumentProcessorServiceClient(credentials=credentials, client_options=opts)
        
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
        
        # Get from DOCUMENT_AI_CREDENTIALS (required)
        creds_path = os.environ.get('DOCUMENT_AI_CREDENTIALS')
        if not creds_path:
            raise ValueError(
                "DOCUMENT_AI_CREDENTIALS environment variable is required to determine project ID. "
                "Either set DOCUMENT_AI_PROJECT_ID or ensure DOCUMENT_AI_CREDENTIALS is set."
            )
        
        if os.path.exists(creds_path):
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
        Processes PDFs in batches of 15 pages to stay within Document AI limits.
        
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
            # Get total page count
            with open(pdf_path, "rb") as pdf_file:
                pdf_reader = PyPDF2.PdfReader(pdf_file)
                total_pages = len(pdf_reader.pages)
            
            logger.info(f"Processing PDF with Document AI OCR: {pdf_path} ({total_pages} pages)")
            
            # Document AI has a limit of 15 pages per request
            # Process in batches of 15 pages
            batch_size = 15
            all_lines = []
            temp_files = []
            
            try:
                for batch_start in range(0, total_pages, batch_size):
                    batch_end = min(batch_start + batch_size, total_pages)
                    batch_pages = batch_end - batch_start
                    
                    logger.info(f"Processing pages {batch_start + 1}-{batch_end} of {total_pages}")
                    
                    # Create a temporary PDF with just this batch of pages
                    temp_pdf = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
                    temp_files.append(temp_pdf.name)
                    
                    # Extract pages for this batch
                    with open(pdf_path, "rb") as source_file:
                        source_reader = PyPDF2.PdfReader(source_file)
                        writer = PyPDF2.PdfWriter()
                        
                        for page_num in range(batch_start, batch_end):
                            writer.add_page(source_reader.pages[page_num])
                        
                        writer.write(temp_pdf)
                    temp_pdf.close()
                    
                    # Process this batch with Document AI
                    with open(temp_pdf.name, "rb") as batch_file:
                        batch_content = batch_file.read()
                    
                    request = documentai.ProcessRequest(
                        name=self.processor_name,
                        raw_document=documentai.RawDocument(
                            content=batch_content,
                            mime_type="application/pdf"
                        ),
                        skip_human_review=True
                    )
                    
                    # Process the batch
                    result = self.client.process_document(request=request)
                    document = result.document
                    
                    # Extract text lines from this batch
                    # Document AI breaks table rows into separate lines, but pdfplumber keeps them together
                    # We need to reconstruct table rows by grouping horizontally aligned text elements
                    batch_lines = []
                    
                    if document.text and document.pages:
                        # Reconstruct table rows from Document AI's layout information
                        # Group text elements that are on the same visual row (similar Y coordinates)
                        # This works best for table-based invoice formats (Scout Logic, Quest, FastMed, etc.)
                        batch_lines = self._reconstruct_table_rows(document)
                        
                        # Fallback: If reconstruction produced very few lines, use simple text splitting
                        # This handles edge cases where layout-based reconstruction doesn't work well
                        if len(batch_lines) < 5:
                            logger.warning(f"Table reconstruction produced only {len(batch_lines)} lines, falling back to simple text extraction")
                            if document.text:
                                batch_lines = [line.strip() for line in document.text.split('\n') if line.strip()]
                        
                        # Fallback: if reconstruction fails, use full text
                        if not batch_lines:
                            raw_lines = document.text.split('\n')
                            for line in raw_lines:
                                normalized = re.sub(r'\s+', ' ', line.strip())
                                if normalized:
                                    batch_lines.append(normalized)
                    else:
                        # Fallback: extract from structured layout if full text not available
                        for page in document.pages:
                            for line in page.lines:
                                line_text = self._layout_to_text(line.layout, document.text)
                                if line_text and line_text.strip():
                                    batch_lines.append(line_text.strip())
                        
                        # If still no lines, try paragraphs
                        if not batch_lines:
                            for page in document.pages:
                                for paragraph in page.paragraphs:
                                    para_text = self._layout_to_text(paragraph.layout, document.text)
                                    if para_text and para_text.strip():
                                        para_lines = para_text.strip().split('\n')
                                        batch_lines.extend([line.strip() for line in para_lines if line.strip()])
                    
                    all_lines.extend(batch_lines)
                    logger.info(f"Extracted {len(batch_lines)} lines from pages {batch_start + 1}-{batch_end}")
                    
                    # Log sample of first few lines for debugging (use INFO level so it shows in logs)
                    if batch_lines and batch_start == 0:
                        sample_lines = batch_lines[:20]
                        logger.info(f"Sample lines from first batch (first 20):")
                        for i, line in enumerate(sample_lines, 1):
                            logger.info(f"  [{i:3d}] {repr(line[:100])}")
                
                logger.info(f"Document AI OCR extracted {len(all_lines)} total text lines from {total_pages} pages")
                
                # Log samples to help debug parsing issues
                if all_lines:
                    logger.info(f"First 10 extracted lines:")
                    for i, line in enumerate(all_lines[:10], 1):
                        logger.info(f"  [{i:3d}] {repr(line[:100])}")
                    
                    # Check for date patterns that parser expects
                    date_pattern = re.compile(r'^(\d{2}/\d{2}/\d{4})\s+(.*)')
                    date_matches = [line for line in all_lines if date_pattern.match(line)]
                    logger.info(f"Lines matching date pattern (MM/DD/YYYY at start): {len(date_matches)}")
                    if date_matches:
                        logger.info(f"Sample date lines (first 5):")
                        for i, line in enumerate(date_matches[:5], 1):
                            logger.info(f"  [{i:3d}] {repr(line[:100])}")
                    else:
                        logger.warning("⚠️  NO lines match date pattern! This explains why parser finds 0 items.")
                        # Check if dates exist but not at start
                        date_anywhere = re.compile(r'\d{2}/\d{2}/\d{4}')
                        lines_with_dates = [line for line in all_lines if date_anywhere.search(line)]
                        logger.info(f"Lines containing dates anywhere: {len(lines_with_dates)}")
                        if lines_with_dates:
                            logger.info(f"Sample (first 3):")
                            for i, line in enumerate(lines_with_dates[:3], 1):
                                logger.info(f"  [{i:3d}] {repr(line[:100])}")
                
                return all_lines
                
            finally:
                # Clean up temporary files
                for temp_file in temp_files:
                    try:
                        if os.path.exists(temp_file):
                            os.remove(temp_file)
                    except Exception as cleanup_error:
                        logger.warning(f"Could not clean up temp file {temp_file}: {cleanup_error}")
            
        except Exception as e:
            logger.error(f"Error during Document AI OCR extraction: {str(e)}", exc_info=True)
            raise ValueError(f"Document AI OCR extraction failed: {str(e)}")
    
    def _reconstruct_table_rows(self, document: documentai.Document) -> List[str]:
        """
        Reconstruct table rows from Document AI layout by grouping horizontally aligned text.
        Document AI breaks table rows into separate lines, but pdfplumber keeps them together.
        This method groups text elements on the same visual row to match pdfplumber's format.
        
        This works for providers with table-based layouts (Scout Logic, Quest, FastMed, InCheck, etc.)
        where related data (date, name, SSN, amount) should be on the same line.
        
        Args:
            document: Document AI document object
            
        Returns:
            List of reconstructed text lines
        """
        reconstructed_lines = []
        
        for page in document.pages:
            # Collect all text elements with their bounding boxes
            text_elements = []
            
            # Get all lines from the page
            for line in page.lines:
                if line.layout and line.layout.bounding_poly:
                    text = self._layout_to_text(line.layout, document.text)
                    if text and text.strip():
                        # Get Y coordinate (top of bounding box) for grouping
                        vertices = line.layout.bounding_poly.vertices
                        if vertices and len(vertices) > 0:
                            # Get valid Y coordinates (filter out None/0)
                            y_coords = [v.y for v in vertices if v.y is not None and v.y > 0]
                            x_coords = [v.x for v in vertices if v.x is not None and v.x >= 0]
                            
                            if y_coords and x_coords:
                                # Use average Y coordinate for grouping, min X for sorting
                                y_coord = sum(y_coords) / len(y_coords)
                                x_coord = min(x_coords)
                                text_elements.append({
                                    'text': text.strip(),
                                    'x': x_coord,
                                    'y': y_coord
                                })
            
            if not text_elements:
                continue
            
            # Sort by Y coordinate (top to bottom), then by X coordinate (left to right)
            text_elements.sort(key=lambda e: (e['y'], e['x']))
            
            # Group elements that are on the same row (similar Y coordinates)
            # Tolerance: elements within 10 pixels vertically are considered same row
            # This tolerance works for most invoice table layouts
            tolerance = 10.0
            current_row = []
            current_y = None
            
            for element in text_elements:
                if current_y is None or abs(element['y'] - current_y) <= tolerance:
                    # Same row - add to current row
                    current_row.append(element)
                    if current_y is None:
                        current_y = element['y']
                    else:
                        # Update to average Y of row for better grouping
                        current_y = sum(e['y'] for e in current_row) / len(current_row)
                else:
                    # New row - process previous row and start new one
                    if current_row:
                        # Sort row elements by X coordinate (left to right)
                        current_row.sort(key=lambda e: e['x'])
                        # Join with multiple spaces to match pdfplumber format
                        # Use 12 spaces (typical spacing in pdfplumber output for table columns)
                        row_text = '            '.join(e['text'] for e in current_row)
                        reconstructed_lines.append(row_text)
                    current_row = [element]
                    current_y = element['y']
            
            # Don't forget the last row
            if current_row:
                current_row.sort(key=lambda e: e['x'])
                row_text = '            '.join(e['text'] for e in current_row)
                reconstructed_lines.append(row_text)
        
        # If reconstruction produced suspiciously few or many lines, log a warning
        # but still return the result (parsers will filter what they need)
        if len(reconstructed_lines) < 10:
            logger.warning(f"Table reconstruction produced only {len(reconstructed_lines)} lines - may need adjustment")
        
        return reconstructed_lines
    
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

