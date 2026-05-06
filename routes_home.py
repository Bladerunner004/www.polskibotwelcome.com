import os
from flask import Blueprint, render_template, session, make_response
from dotenv import load_dotenv

# Załadowanie zmiennych środowiskowych
load_dotenv()

home_bp = Blueprint('home', __name__)

@home_bp.route('/')
def index():
    user_data = session.get('user')
    from base import get_login_url
    login_url = get_login_url()

    
    # --- LOGIKA AWATARA ---
    user_avatar = "https://cdn.discordapp.com/embed/avatars/0.png"
    if user_data:
        uid = user_data.get('id')
        av_hash = user_data.get('avatar')
        if uid and av_hash:
            ext = 'gif' if av_hash.startswith('a_') else 'png'
            user_avatar = f"https://cdn.discordapp.com/avatars/{uid}/{av_hash}.{ext}"
    
    # --- STATYSTYKI BOTA ---
    bot_stats = {
        'servers': '1 248',
        'commands': '25',
        'uptime': '99.9%'
    }

    rendered = render_template(
        'home.html', 
        user=user_data,
        user_avatar=user_avatar, 
        login_url=login_url,
        stats=bot_stats
    )
    
    response = make_response(rendered)
    response.headers['Content-Type'] = 'text/html; charset=utf-8'
    return response

@home_bp.route('/privacy')
def privacy():
    return render_template('privacy.html')

@home_bp.route('/tos')
def tos():
    return render_template('tos.html')