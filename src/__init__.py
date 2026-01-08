import os
import traceback
from flask import Flask, jsonify, render_template, request
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix
from src.config import Config
from src.extensions import oauth
from src.logger import get_logger

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Enable CORS for all routes
    CORS(app, resources={r"/*": {"origins": "*"}})

    # Initialize logger singleton
    logger = get_logger()
    logger.info("Flask application initialized")

    # 1. Initialize FireO
    if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
        logger.warning("WARNING: GOOGLE_APPLICATION_CREDENTIALS not set.")

    # 2. Initialize Extensions
    oauth.init_app(app)
    oauth.register(
        name='google',
        client_id=app.config['GOOGLE_CLIENT_ID'],
        client_secret=app.config['GOOGLE_CLIENT_SECRET'],
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={'scope': 'openid email profile'}
    )

    # 3. Register Blueprints
    from src.routes.main import main_bp
    from src.routes.auth import auth_bp
    
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)

    # 4. Request logging (for debugging)
    @app.before_request
    def log_request_info():
        """Log request information for debugging."""
        logger.info(f"Request: {request.method} {request.path}")
        # Don't access request.form here for multipart requests - it might interfere with file parsing
        # Only log form data for non-file upload requests
        if request.path != '/upload' and request.form:
            logger.debug(f"Form data: {dict(request.form)}")

    # 5. Global Error Handlers
    @app.errorhandler(500)
    def internal_error(error):
        """Handle 500 Internal Server Errors."""
        error_traceback = traceback.format_exc()
        error_message = str(error)
        
        # Log error with traceback
        logger.error(f"500 Error: {error_message}")
        logger.exception("Full traceback:")
        
        # If it's an AJAX request, return JSON
        if request.is_json or request.path.startswith('/upload'):
            return jsonify({
                'success': False,
                'message': 'An internal server error occurred. Please try again later.'
            }), 500
        
        # Otherwise, return HTML error page
        return render_template('error.html', error_code=500, error_message='Internal Server Error'), 500
    
    @app.errorhandler(404)
    def not_found(error):
        """Handle 404 Not Found errors."""
        logger.warning(f"404 Error: {request.path}")
        if request.is_json:
            return jsonify({'success': False, 'message': 'Resource not found'}), 404
        return render_template('error.html', error_code=404, error_message='Page Not Found'), 404
    
    @app.errorhandler(413)
    def request_entity_too_large(error):
        """Handle 413 Request Entity Too Large errors."""
        logger.error(f"413 Error: File too large. Content-Length: {request.content_length}")
        if request.path.startswith('/upload'):
            return jsonify({
                'success': False,
                'message': 'File is too large. Maximum size is 50MB.'
            }), 413
        return render_template('error.html', error_code=413, error_message='File Too Large'), 413

    # 6. Apply ProxyFix (for reverse proxy support)
    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=0,   # usually you don't trust X-Forwarded-For unless needed
        x_proto=1, # trust X-Forwarded-Proto
        x_host=1,  # trust X-Forwarded-Host
        x_port=0,  # usually not needed
        x_prefix=0 # usually not needed
    )

    return app


