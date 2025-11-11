from flask import Flask
from flask_sqlalchemy import SQLAlchemy
# from flask_migrate import Migrate #
# from flask_moment import Moment #
from flask_login import LoginManager
from flask_mail import Mail 
import os
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import helper functions
from .helpers import format_currency, kategori_besar, filter_cashflow, hitung_penyusutan

db = SQLAlchemy()
# migrate = Migrate() #
# moment = Moment() #
login_manager = LoginManager()
mail = Mail()

# User loader di level module untuk menghindari circular import
@login_manager.user_loader
def load_user(user_id):
    from .models import User
    return User.query.get(int(user_id))

def create_app():
    app = Flask(__name__)
    
    # Configuration
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL') or 'sqlite:///daniar.db'
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or 'secret-key-yang-lebih-aman'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    # Email Configuration
    app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
    app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', 587))
    app.config['MAIL_USE_TLS'] = os.environ.get('MAIL_USE_TLS', True)
    app.config['MAIL_USE_SSL'] = os.environ.get('MAIL_USE_SSL', False)
    app.config['MAIL_USERNAME'] = os.environ.get('GMAIL_USERNAME', 'daniarfurnitureart@gmail.com')
    app.config['MAIL_PASSWORD'] = os.environ.get('GMAIL_APP_PASSWORD', 'jerhrsumnqdmmhmk')
    app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_DEFAULT_SENDER', 'daniarfurnitureart@gmail.com')
    
    # Company Info
    app.config['COMPANY_NAME'] = os.environ.get('COMPANY_NAME', 'PT. Daniar Furniture Art')
    app.config['COMPANY_EMAIL'] = os.environ.get('COMPANY_EMAIL', 'daniarfurnitureart@gmail.com')
    app.config['COMPANY_PHONE'] = os.environ.get('COMPANY_PHONE', '+6285777653187')
    app.config['COMPANY_ADDRESS'] = os.environ.get('COMPANY_ADDRESS', 'Jln.Mesjid Kp.Kaum No.20, RT.01/RW.11, Ciparigi, Kota Bogor')

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
   # moment.init_app(app) #
    login_manager.init_app(app)
    mail.init_app(app)
    
    # Login manager configuration
    login_manager.login_view = 'main.login'
    login_manager.login_message_category = 'info'
    login_manager.session_protection = "basic"

    # Register blueprint
    from .main.routes import main_bp
    app.register_blueprint(main_bp)

    # Register Jinja filters
    app.jinja_env.filters['currency'] = format_currency
    app.jinja_env.filters['kategori_besar'] = kategori_besar
    
    # Template filter untuk format now
    @app.template_filter('now')
    def now_filter(format_string='%d/%m/%Y %H:%M'):
        return datetime.now().strftime(format_string)

    # Template filter untuk format Rupiah
    @app.template_filter('currency')
    def currency_format(value):
        """Format currency untuk template"""
        if value is None:
            return "Rp 0"
        try:
            return f"Rp {int(value):,}".replace(',', '.')
        except (ValueError, TypeError):
            return "Rp 0"

    @app.template_filter('format_rupiah')
    def format_rupiah(value):
        """Format number to Rupiah currency"""
        if value is None:
            return "Rp 0"
        try:
            return f"Rp {int(value):,}".replace(',', '.')
        except (ValueError, TypeError):
            return "Rp 0"

    # Template filter untuk terbilang (angka ke kata)
    @app.template_filter('terbilang')
    def terbilang_filter(n):
        """Convert number to Indonesian words"""
        def terbilang(n):
            if n < 0:
                return "minus " + terbilang(-n)
            
            bilangan = ["", "satu", "dua", "tiga", "empat", "lima", "enam", "tujuh", "delapan", "sembilan", "sepuluh", "sebelas"]
            
            if n < 12:
                return bilangan[n]
            elif n < 20:
                return terbilang(n - 10) + " belas"
            elif n < 100:
                return terbilang(n // 10) + " puluh" + (" " + terbilang(n % 10) if n % 10 != 0 else "")
            elif n < 200:
                return "seratus" + (" " + terbilang(n - 100) if n - 100 != 0 else "")
            elif n < 1000:
                return terbilang(n // 100) + " ratus" + (" " + terbilang(n % 100) if n % 100 != 0 else "")
            elif n < 2000:
                return "seribu" + (" " + terbilang(n - 1000) if n - 1000 != 0 else "")
            elif n < 1000000:
                return terbilang(n // 1000) + " ribu" + (" " + terbilang(n % 1000) if n % 1000 != 0 else "")
            elif n < 1000000000:
                return terbilang(n // 1000000) + " juta" + (" " + terbilang(n % 1000000) if n % 1000000 != 0 else "")
            else:
                return "angka terlalu besar"
        
        try:
            # Handle decimal numbers
            if isinstance(n, float):
                integer_part = int(n)
                decimal_part = round((n - integer_part) * 100)
                result = terbilang(integer_part)
                if decimal_part > 0:
                    result += " koma " + terbilang(decimal_part)
                return result
            else:
                return terbilang(int(n))
        except:
            return ""

    # Template filters untuk laporan karyawan
    @app.template_filter('chart_color')
    def chart_color_filter(index):
        colors = ['#4e73df', '#1cc88a', '#36b9cc', '#f6c23e', '#e74a3b']
        return colors[index % len(colors)]

    @app.template_filter('status_color')
    def status_color_filter(status):
        color_map = {
            'TETAP': '#1cc88a',
            'KONTRAK': '#f6c23e',
            'PERCOBAAN': '#36b9cc',
            'HONORER': '#e74a3b'
        }
        return color_map.get(status, '#858796')

    @app.template_filter('status_badge_color')
    def status_badge_color_filter(status):
        color_map = {
            'TETAP': 'success',
            'KONTRAK': 'warning',
            'PERCOBAAN': 'info',
            'HONORER': 'danger'
        }
        return color_map.get(status, 'secondary')

    # Context processors
    @app.context_processor
    def inject_now():
        return {'now': datetime.now}

    @app.context_processor
    def inject_current_date():
        return {'current_date': datetime.now().date()}

    @app.context_processor
    def inject_company_info():
        """Inject company information into all templates"""
        return {
            'company_name': app.config['COMPANY_NAME'],
            'company_email': app.config['COMPANY_EMAIL'],
            'company_phone': app.config['COMPANY_PHONE'],
            'company_address': app.config['COMPANY_ADDRESS']
        }

    return app