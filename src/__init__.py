import os
from flask import Flask
from src.config import Config
from src.extensions import oauth

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # 1. Initialize FireO
    if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
        print("WARNING: GOOGLE_APPLICATION_CREDENTIALS not set.")

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

    return app

