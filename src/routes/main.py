from flask import Blueprint, render_template, session, redirect, url_for
from src.decorators import login_required

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def index():
    if 'user' in session:
        return redirect(url_for('main.dashboard'))
    return render_template('index.html')

@main_bp.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html', user=session['user'])

