from flask import Blueprint, redirect, url_for, session, flash, current_app
from src.extensions import oauth
from src.services.user_service import UserService

auth_bp = Blueprint('auth', __name__)
user_service = UserService()

@auth_bp.route('/login')
def login():
    redirect_uri = url_for('auth.auth_callback', _external=True)
    return oauth.google.authorize_redirect(redirect_uri)

@auth_bp.route('/auth/callback')
def auth_callback():
    try:
        token = oauth.google.authorize_access_token()
        user_info = token.get('userinfo')
        
        if not user_info:
            flash("Failed to get user info.", "danger")
            return redirect(url_for('main.index'))

        # Create or update user using service
        user = user_service.create_or_update_user(
            email=user_info['email'],
            name=user_info['name'],
            profile_pic=user_info['picture']
        )

        # Save to Session
        session['user'] = {
            'email': user.email,
            'name': user.name,
            'picture': user.profile_pic
        }
        
        return redirect(url_for('main.dashboard'))
    
    except Exception as e:
        current_app.logger.error(f"Auth Error: {e}")
        flash("Authentication failed.", "danger")
        return redirect(url_for('main.index'))

@auth_bp.route('/logout')
def logout():
    session.pop('user', None)
    flash("Logged out successfully.", "info")
    return redirect(url_for('main.index'))

