import os
from flask import render_template, current_app
from flask_mail import Message
from threading import Thread
from daniar_app import mail

def send_async_email(app, msg):
    """Mengirim email secara asynchronous"""
    with app.app_context():
        try:
            mail.send(msg)
            current_app.logger.info(f"Email berhasil dikirim ke {msg.recipients}")
        except Exception as e:
            current_app.logger.error(f"Error mengirim email: {str(e)}")

def send_email(to, subject, template, **kwargs):
    """Fungsi utama untuk mengirim email"""
    app = current_app._get_current_object()
    
    # Buat pesan email
    msg = Message(
        subject=subject,
        sender=current_app.config['MAIL_DEFAULT_SENDER'],
        recipients=[to]
    )
    
    # Render template HTML dan text
    msg.html = render_template(f'emails/{template}.html', **kwargs)
    msg.body = render_template(f'emails/{template}.txt', **kwargs)
    
    # Kirim email secara asynchronous
    thr = Thread(target=send_async_email, args=[app, msg])
    thr.start()
    return thr

def send_faktur_email(faktur, email_tujuan):
    """Mengirim faktur via email"""
    subject = f"Faktur {faktur.nomor_faktur} - PT. Daniar Furniture Art"
    
    # Data untuk template
    email_data = {
        'faktur': faktur,
        'company_name': current_app.config['COMPANY_NAME'],
        'company_email': current_app.config['COMPANY_EMAIL'],
        'company_phone': current_app.config['COMPANY_PHONE'],
        'company_address': current_app.config['COMPANY_ADDRESS']
    }
    
    return send_email(email_tujuan, subject, 'faktur', **email_data)