import os

class DevelopmentConfig:
    # Basic Flask Config
    DEBUG = True
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'daniar-secret-key-2024-flask-app-development'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///daniar_app.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Gmail Configuration - COBA DENGAN KONFIGURASI BERBEDA
    MAIL_SERVER = 'smtp.gmail.com'
    MAIL_PORT = 465  # ← COBA PORT 465
    MAIL_USE_TLS = False
    MAIL_USE_SSL = True  # ← PAKAI SSL
    MAIL_USERNAME = 'daniarfurnitureart@gmail.com'
    MAIL_PASSWORD = 'jerhrsumnqdmmhmk'  # ← PAKAI INI (tanpa spasi)
    MAIL_DEFAULT_SENDER = 'daniarfurnitureart@gmail.com'
    
    # Company Info
    COMPANY_NAME = "PT. Daniar Furniture Art"
    COMPANY_EMAIL = "daniarfurnitureart@gmail.com"
    COMPANY_PHONE = "+62 857-7765-3187"
    COMPANY_ADDRESS = "Jln.Mesjid Kp.Kaum No.20, RT.01/RW.11, Ciparigi, Kota Bogor"