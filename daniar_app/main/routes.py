from flask import (
    Blueprint, render_template, request, redirect, url_for, 
    flash, session, send_file, current_app
)
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime, date
from sqlalchemy import extract, func, and_, or_
import urllib.parse
from dotenv import load_dotenv
import re 
import pandas as pd
import io
import os
import uuid
import logging

# Import dari package root
from daniar_app import db, login_manager
from daniar_app.models import (
    User, Cashflow, AsetTetap, Karyawan, Faktur, 
    KasbonState, RAB, ItemRAB, ItemFaktur, SlipGaji
)
from daniar_app.helpers import (
    format_currency, kategori_besar, filter_cashflow, 
    hitung_penyusutan, jadwal_penyusutan
)

# Untuk export Excel/PDF
import json
import csv

# Untuk generate PDF
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter, A4

# Untuk email (jika sudah siap)
from flask_mail import Message

# Untuk upload file
from werkzeug.utils import secure_filename


main_bp = Blueprint('main', __name__)

# Setup logging
logger = logging.getLogger(__name__)


# ===== HELPER FUNCTIONS =====
def ensure_upload_folders():
    """Pastikan semua folder upload ada"""
    folders = [
        'static/uploads',
        'static/uploads/karyawan',
        'static/uploads/slip_gaji'
    ]
    
    for folder in folders:
        if not os.path.exists(folder):
            os.makedirs(folder, exist_ok=True)
            logger.info(f"Created folder: {folder}")

# Panggil saat aplikasi start
ensure_upload_folders()

def allowed_file(filename):
    """Check if file extension is allowed"""
    allowed_extensions = {'png', 'jpg', 'jpeg', 'gif'}
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in allowed_extensions

def save_uploaded_file(file, subfolder='karyawan'):
    """Save uploaded file and return file path"""
    if file and file.filename and allowed_file(file.filename):
        # Generate unique filename
        file_extension = file.filename.rsplit('.', 1)[1].lower()
        unique_filename = f"{uuid.uuid4().hex}.{file_extension}"
        
        # Ensure upload folder exists
        upload_folder = f'static/uploads/{subfolder}'
        if not os.path.exists(upload_folder):
            os.makedirs(upload_folder, exist_ok=True)
        
        # Save file
        file_path = os.path.join(upload_folder, unique_filename)
        file.save(file_path)
        
        return file_path
    return None

def delete_old_file(file_path):
    """Delete old file if exists"""
    if file_path and os.path.exists(file_path):
        try:
            os.remove(file_path)
            logger.info(f"Deleted old file: {file_path}")
        except Exception as e:
            logger.error(f"Error deleting file {file_path}: {e}")


# -------------------- LOGIN --------------------
@main_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        remember = True if request.form.get('remember') else False
        
        # SIMPLE AUTH - no database
        if username == 'admin' and password == 'password123':
            session['user_id'] = 1
            session['username'] = 'admin'
            session['role'] = 'admin'
            session.permanent = True  # Important for production
            flash('Login berhasil!', 'success')
            print(f"DEBUG: User {username} logged in, session: {dict(session)}")  # Debug
            return redirect(url_for('main.dashboard'))
        elif username == 'user' and password == 'user123':
            session['user_id'] = 2
            session['username'] = 'user' 
            session['role'] = 'user'
            session.permanent = True  # Important for production
            flash('Login berhasil!', 'success')
            print(f"DEBUG: User {username} logged in, session: {dict(session)}")  # Debug
            return redirect(url_for('main.dashboard'))
        else:
            flash('Username atau password salah!', 'danger')
    
    return render_template('login.html')

@main_bp.route('/logout')
@login_required
def logout():
    logout_user()
    session.pop('logged_in', None)
    session.pop('username', None)
    flash('Anda telah berhasil logout.', 'success')
    return redirect(url_for('main.login'))


# -------------------- DASHBOARD --------------------
@main_bp.route("/")
@main_bp.route("/dashboard")
@login_required
def dashboard():
    """
    Menampilkan dashboard dengan data keuangan yang dinamis.
    """
    now = datetime.now()

    # --- DEFINE KATEGORI BARU SESUAI CASHFLOW ---
    
    # MODAL AWAL - KATEGORI BARU
    modal_jenis = [
        'SETORAN MODAL AWAL', 'TAMBAHAN MODAL', 'INVESTASI PEMILIK'
    ]
    
    # PEMASUKAN OPERASIONAL - DIPISAH DARI MODAL
    pemasukan_jenis = [
        'PENJUALAN TUNAI', 'PENERIMAAN PIUTANG', 'PENDAPATAN BUNGA', 
        'PENGEMBALIAN PAJAK', 'PENERIMAAN TUNAI LAINNYA', 'BAYAR KASBON'
    ]
    
    # PINJAMAN/FUNDING - DIPISAH DARI MODAL
    funding_jenis = [
        'PINJAMAN BANK', 'CASH INJECTION', 'DANA PINJAMAN', 'FUNDING INVESTOR'
    ]
    
    # HPP - TANPA "LAINNYA"
    hpp_jenis = [
        'BIAYA PRODUK / LAYANAN LANGSUNG', 'PAJAK PENGGAJIAN - LANGSUNG',
        'GAJI - TKL', 'PERSEDIAAN'
    ]
    
    # OPERASIONAL - TANPA "LAINNYA"  
    operasional_jenis = [
        'GAJI KARYAWAN', 'IKLAN', 'BIAYA BANK', 'PELATIHAN', 'ASURANSI',
        'INTERNET', 'LISENSI / IZIN', 'MAKANAN / HIBURAN', 'PERALATAN KANTOR',
        'PAJAK GAJI', 'ONGKOS KIRIM', 'PENCETAKAN', 'KONSULTAN', 'OKUPANSI',
        'BIAYA SEWA', 'SUBCONTRACTOR', 'TELEPON', 'TRANSPORTASI', 'PERJALANAN DINAS',
        'BIAYA LISTRIK', 'PENGEMBANGAN WEB', 'DOMAIN WEB DAN HOSTING', 'BIAYA AIR',
        'BIAYA SUBSCRIPTION', 'PAJAK PEMBELIAN'
    ]
    
    # PENGELUARAN LAIN-LAIN - HANYA DI SINI ADA "LAINNYA"
    lain_jenis = [
        'PENGELUARAN TUNAI UNTUK PEMILIK', 'KASBON', 'BEBAN BUNGA',
        'BEBAN PAJAK PENGHASILAN', 'BIAYA ADMIN', 'LAINNYA', 'KEWAJIBAN'
    ]

    # --- PERIODE BULAN INI ---
    start_of_month = datetime(now.year, now.month, 1)
    if now.month == 12:
        end_of_month = datetime(now.year + 1, 1, 1)
    else:
        end_of_month = datetime(now.year, now.month + 1, 1)

    # --- AMBIL SEMUA DATA CASHFLOW BULAN INI ---
    cashflows_bulan_ini = Cashflow.query.filter(
        Cashflow.tanggal >= start_of_month,
        Cashflow.tanggal < end_of_month
    ).all()

    print("="*50)
    print("DEBUG - SEMUA DATA CASHFLOW BULAN INI")
    print(f"Periode: {start_of_month.date()} sampai {end_of_month.date()}")
    print(f"Jumlah transaksi: {len(cashflows_bulan_ini)}")
    
    # --- HITUNG MANUAL DARI DATA YANG SUDAH DIFILTER ---
    modal_bulan = 0
    pemasukan_operasional_bulan = 0  # Nama variable yang konsisten
    funding_bulan = 0
    hpp_bulan = 0
    operasional_bulan = 0
    lain_bulan = 0
    
    for cf in cashflows_bulan_ini:
        print(f"  - {cf.tanggal} | {cf.jenis} | Rp {cf.harga:,.0f}")
        
        if cf.jenis in modal_jenis:
            modal_bulan += cf.harga
            print(f"    → MODAL")
        elif cf.jenis in pemasukan_jenis:
            pemasukan_operasional_bulan += cf.harga
            print(f"    → PEMASUKAN OPERASIONAL")
        elif cf.jenis in funding_jenis:
            funding_bulan += cf.harga
            print(f"    → FUNDING")
        elif cf.jenis in hpp_jenis:
            hpp_bulan += cf.harga
            print(f"    → HPP")
        elif cf.jenis in operasional_jenis:
            operasional_bulan += cf.harga
            print(f"    → OPERASIONAL")
        elif cf.jenis in lain_jenis:
            lain_bulan += cf.harga
            print(f"    → LAIN-LAIN")
        else:
            # Untuk kompatibilitas data lama
            if cf.jenis in ['PINJAMAN / CASH INJECTION', 'FUNDING']:
                funding_bulan += cf.harga
                print(f"    → FUNDING (Kategori Lama)")
            else:
                # Jika tidak masuk kategori manapun, anggap sebagai pengeluaran lain
                print(f"    ⚠️  JENIS TIDAK DIKENAL: {cf.jenis}")
                lain_bulan += cf.harga

    # --- HITUNG TOTAL PENGELUARAN ---
    total_pengeluaran_bulan = hpp_bulan + operasional_bulan + lain_bulan

    # --- HITUNG TOTAL PEMASUKAN (TERMASUK MODAL & FUNDING) ---
    total_pemasukan_bulan = modal_bulan + pemasukan_operasional_bulan + funding_bulan

    # --- HITUNG SALDO BULAN INI ---
    saldo_bulan = total_pemasukan_bulan - total_pengeluaran_bulan

    # --- DEBUG HASIL PERHITUNGAN ---
    print("="*50)
    print("HASIL PERHITUNGAN MANUAL:")
    print(f"Modal: Rp {modal_bulan:,.0f}")
    print(f"Pemasukan Operasional: Rp {pemasukan_operasional_bulan:,.0f}")
    print(f"Funding: Rp {funding_bulan:,.0f}")
    print(f"Total Pemasukan: Rp {total_pemasukan_bulan:,.0f}")
    print(f"HPP: Rp {hpp_bulan:,.0f}")
    print(f"Operasional: Rp {operasional_bulan:,.0f}")
    print(f"Lain-lain: Rp {lain_bulan:,.0f}")
    print(f"Total Pengeluaran: Rp {total_pengeluaran_bulan:,.0f}")
    print(f"Saldo Bulan Ini: Rp {saldo_bulan:,.0f}")

    # --- HITUNG TOTAL KAS (SELURUH WAKTU) ---
    semua_cashflows = Cashflow.query.all()
    
    total_modal = 0
    total_pemasukan_operasional = 0
    total_funding = 0
    total_pengeluaran_semua = 0
    
    for cf in semua_cashflows:
        if cf.jenis in modal_jenis:
            total_modal += cf.harga
        elif cf.jenis in pemasukan_jenis:
            total_pemasukan_operasional += cf.harga
        elif cf.jenis in funding_jenis or cf.jenis in ['PINJAMAN / CASH INJECTION', 'FUNDING']:
            total_funding += cf.harga
        elif cf.jenis in hpp_jenis + operasional_jenis + lain_jenis:
            total_pengeluaran_semua += cf.harga
    
    total_kas = (total_modal + total_pemasukan_operasional + total_funding) - total_pengeluaran_semua

    # --- STATISTIK LAINNYA ---
    total_nilai_aset_tetap = 0
    try:
        aset_tetap_list = AsetTetap.query.all()
        for aset in aset_tetap_list:
            try:
                _, nilai_buku = hitung_penyusutan(aset)
                total_nilai_aset_tetap += nilai_buku
            except Exception as e:
                print(f"Error hitung penyusutan aset {aset.id}: {e}")
                continue
    except Exception as e:
        print(f"Error query aset: {e}")
    
    total_karyawan = Karyawan.query.count()
    total_faktur = Faktur.query.count()
    
    kasbon_state = KasbonState.query.first()
    total_utang_kasbon = kasbon_state.total_utang if kasbon_state else 0.0

    # --- DATA UNTUK CHART ---
    chart_labels = ['Modal', 'Pemasukan', 'Funding', 'HPP', 'Operasional', 'Lain-lain']
    chart_data = [
        float(modal_bulan),
        float(pemasukan_operasional_bulan),
        float(funding_bulan),
        float(hpp_bulan), 
        float(operasional_bulan),
        float(lain_bulan)
    ]

    # --- DATA TREND 6 BULAN TERAKHIR ---
    bulan_terakhir = []
    pemasukan_trend = []
    pengeluaran_trend = []
    
    for i in range(5, -1, -1):
        bulan = now.month - i
        tahun = now.year
        if bulan <= 0:
            bulan += 12
            tahun -= 1
        
        start_bulan = datetime(tahun, bulan, 1)
        if bulan == 12:
            end_bulan = datetime(tahun + 1, 1, 1)
        else:
            end_bulan = datetime(tahun, bulan + 1, 1)
        
        # Hitung manual untuk trend
        cashflows_trend = Cashflow.query.filter(
            Cashflow.tanggal >= start_bulan,
            Cashflow.tanggal < end_bulan
        ).all()
        
        modal_trend_bulan = 0
        pemasukan_trend_bulan = 0
        funding_trend_bulan = 0
        pengeluaran_trend_bulan = 0
        
        for cf in cashflows_trend:
            if cf.jenis in modal_jenis:
                modal_trend_bulan += cf.harga
            elif cf.jenis in pemasukan_jenis:
                pemasukan_trend_bulan += cf.harga
            elif cf.jenis in funding_jenis or cf.jenis in ['PINJAMAN / CASH INJECTION', 'FUNDING']:
                funding_trend_bulan += cf.harga
            elif cf.jenis in hpp_jenis + operasional_jenis + lain_jenis:
                pengeluaran_trend_bulan += cf.harga
        
        total_pemasukan_trend = modal_trend_bulan + pemasukan_trend_bulan + funding_trend_bulan
        
        nama_bulan = start_bulan.strftime('%b %Y')
        bulan_terakhir.append(nama_bulan)
        pemasukan_trend.append(float(total_pemasukan_trend))
        pengeluaran_trend.append(float(pengeluaran_trend_bulan))

    # --- AKTIVITAS TERKINI ---
    recent_cashflows = Cashflow.query.order_by(Cashflow.tanggal.desc(), Cashflow.id.desc()).limit(5).all()

    # --- FINAL DEBUG ---
    print("="*50)
    print("FINAL DASHBOARD DATA:")
    print(f"Total Kas: Rp {total_kas:,.0f}")
    print(f"Modal Bulan Ini: Rp {modal_bulan:,.0f}")
    print(f"Pemasukan Operasional Bulan Ini: Rp {pemasukan_operasional_bulan:,.0f}")
    print(f"Funding Bulan Ini: Rp {funding_bulan:,.0f}")
    print(f"Total Pemasukan Bulan Ini: Rp {total_pemasukan_bulan:,.0f}")
    print(f"Pengeluaran Bulan Ini: Rp {total_pengeluaran_bulan:,.0f}")
    print(f"Detail Pengeluaran:")
    print(f"  - HPP: Rp {hpp_bulan:,.0f}")
    print(f"  - Operasional: Rp {operasional_bulan:,.0f}")
    print(f"  - Lain-lain: Rp {lain_bulan:,.0f}")
    print("="*50)

    return render_template(
        "dashboard.html",
        total_kas=total_kas,
        total_pemasukan_bulan=total_pemasukan_bulan,
        total_pengeluaran_bulan=total_pengeluaran_bulan,
        total_nilai_aset_tetap=total_nilai_aset_tetap,
        total_karyawan=total_karyawan,
        total_faktur=total_faktur,
        total_utang_kasbon=total_utang_kasbon,
        recent_cashflows=recent_cashflows,
        # Data breakdown untuk detail - PASTIKAN SEMUA VARIABLE INI DIKIRIM
        modal_bulan=modal_bulan,
        pemasukan_operasional_bulan=pemasukan_operasional_bulan,  # Variable yang benar
        funding_bulan=funding_bulan,
        hpp_bulan=hpp_bulan,
        operasional_bulan=operasional_bulan,
        lain_bulan=lain_bulan,
        # Data untuk chart detail
        chart_labels=chart_labels,
        chart_data=chart_data,
        # Data untuk trend chart
        bulan_terakhir=bulan_terakhir,
        pemasukan_trend=pemasukan_trend,
        pengeluaran_trend=pengeluaran_trend
    )

# -------------------- CASHFLOW --------------------
@main_bp.route('/cashflow', methods=['GET','POST'])
@login_required
def cashflow():
    if request.method == 'POST':
        try:
            # Ambil data dari form
            tanggal_str = request.form.get('tanggal')
            nama_barang = request.form.get('nama_barang')
            jenis = request.form.get('jenis')
            jumlah = request.form.get('jumlah', '')
            satuan = request.form.get('satuan', '')
            harga_str = request.form.get('harga')
            keterangan = request.form.get('keterangan', '')
            catatan_tambahan = request.form.get('catatan_tambahan', '')

            # Validasi
            if not all([tanggal_str, nama_barang, jenis, harga_str]):
                flash("Harap isi semua field yang wajib diisi (Tanggal, Nama, Jenis, Harga).", "warning")
                return redirect(url_for('main.cashflow'))

            new_cashflow = Cashflow(
                tanggal=datetime.strptime(tanggal_str, '%Y-%m-%d'),
                nama_barang=nama_barang,
                jenis=jenis,
                jumlah=jumlah,
                satuan=satuan,
                harga=float(harga_str),
                keterangan=keterangan,
                catatan_tambahan=catatan_tambahan
            )
            db.session.add(new_cashflow)

            # LOGIKA KASBON
            kasbon_state = KasbonState.query.first()
            if not kasbon_state:
                kasbon_state = KasbonState(total_utang=0.0)
                db.session.add(kasbon_state)

            if jenis == "KASBON":
                # Tambah utang kasbon
                kasbon_state.total_utang += new_cashflow.harga
                flash(f"Kasbon sebesar {format_currency(new_cashflow.harga)} telah dicatat. Total utang kasbon: {format_currency(kasbon_state.total_utang)}", "info")
            
            elif jenis == "BAYAR KASBON":
                # Bayar utang kasbon
                if new_cashflow.harga > kasbon_state.total_utang:
                    flash(f"Pembayaran kasbon melebihi total utang! Total utang saat ini: {format_currency(kasbon_state.total_utang)}", "warning")
                    db.session.rollback()
                    return redirect(url_for('main.cashflow'))
                else:
                    kasbon_state.total_utang -= new_cashflow.harga
                    flash(f"Kasbon telah dibayar sebesar {format_currency(new_cashflow.harga)}. Sisa utang: {format_currency(kasbon_state.total_utang)}", "success")

            db.session.commit()
            flash("Data cashflow berhasil ditambahkan", "success")

        except Exception as e:
            db.session.rollback()
            flash(f"Gagal menambahkan data: {str(e)}", "danger")

        return redirect(url_for('main.cashflow'))

    # BAGIAN GET
    selected_month = request.args.get('month', type=int)
    selected_year = request.args.get('year', type=int)

    query = Cashflow.query
    if selected_month:
        query = query.filter(extract('month', Cashflow.tanggal) == selected_month)
    if selected_year:
        query = query.filter(extract('year', Cashflow.tanggal) == selected_year)

    data = query.order_by(Cashflow.tanggal.asc(), Cashflow.id.asc()).all()

    # Siapkan data untuk template
    years_from_db = db.session.query(extract('year', Cashflow.tanggal)).distinct().all()
    years_in_db = {int(year[0]) for year in years_from_db if year[0]}
    current_year = datetime.now().year
    all_years = years_in_db.union({current_year - 2, current_year - 1, current_year, current_year + 1, current_year + 2})
    years = sorted(list(all_years))

    months = [
        (1, 'Januari'), (2, 'Februari'), (3, 'Maret'), (4, 'April'),
        (5, 'Mei'), (6, 'Juni'), (7, 'Juli'), (8, 'Agustus'),
        (9, 'September'), (10, 'Oktober'), (11, 'November'), (12, 'Desember')
    ]

    # --- DEFINE KATEGORI YANG SAMA DENGAN DASHBOARD ---
    
    # MODAL AWAL - KATEGORI BARU
    modal_jenis = [
        'SETORAN MODAL AWAL', 'TAMBAHAN MODAL', 'INVESTASI PEMILIK'
    ]
    
    # PEMASUKAN - DIPISAH DARI MODAL
    pemasukan_jenis = [
        'PENJUALAN TUNAI', 'PENERIMAAN PIUTANG', 'PENDAPATAN BUNGA', 
        'PENGEMBALIAN PAJAK', 'PENERIMAAN TUNAI LAINNYA', 'BAYAR KASBON'
    ]
    
    # PINJAMAN/FUNDING - DIPISAH DARI MODAL
    funding_jenis = [
        'PINJAMAN BANK', 'CASH INJECTION', 'DANA PINJAMAN', 'FUNDING INVESTOR'
    ]
    
    # HPP - TANPA "LAINNYA"
    hpp_jenis = [
        'BIAYA PRODUK / LAYANAN LANGSUNG', 'PAJAK PENGGAJIAN - LANGSUNG',
        'GAJI - TKL', 'PERSEDIAAN'
    ]
    
    # OPERASIONAL - TANPA "LAINNYA"  
    operasional_jenis = [
        'GAJI KARYAWAN', 'IKLAN', 'BIAYA BANK', 'PELATIHAN', 'ASURANSI',
        'INTERNET', 'LISENSI / IZIN', 'MAKANAN / HIBURAN', 'PERALATAN KANTOR',
        'PAJAK GAJI', 'ONGKOS KIRIM', 'PENCETAKAN', 'KONSULTAN', 'OKUPANSI',
        'BIAYA SEWA', 'SUBCONTRACTOR', 'TELEPON', 'TRANSPORTASI', 'PERJALANAN DINAS',
        'BIAYA LISTRIK', 'PENGEMBANGAN WEB', 'DOMAIN WEB DAN HOSTING', 'BIAYA AIR',
        'BIAYA SUBSCRIPTION', 'PAJAK PEMBELIAN'
    ]
    
    # PENGELUARAN LAIN-LAIN - HANYA DI SINI ADA "LAINNYA"
    lain_jenis = [
        'PENGELUARAN TUNAI UNTUK PEMILIK', 'KASBON', 'BEBAN BUNGA',
        'BEBAN PAJAK PENGHASILAN', 'BIAYA ADMIN', 'LAINNYA', 'KEWAJIBAN'
    ]

    # Hitung ringkasan dengan kategori yang terpisah
    modal = sum(c.harga for c in data if c.jenis in modal_jenis)
    pemasukan = sum(c.harga for c in data if c.jenis in pemasukan_jenis)
    funding = sum(c.harga for c in data if c.jenis in funding_jenis)
    
    # Untuk kompatibilitas dengan data lama
    funding += sum(c.harga for c in data if c.jenis in ['PINJAMAN / CASH INJECTION', 'FUNDING'])
    
    hpp = sum(c.harga for c in data if c.jenis in hpp_jenis)
    operasional = sum(c.harga for c in data if c.jenis in operasional_jenis)
    lain_lain = sum(c.harga for c in data if c.jenis in lain_jenis)
    
    # Total pemasukan (termasuk modal dan funding)
    total_pemasukan = pemasukan + modal + funding
    
    # Total pengeluaran
    total_pengeluaran = hpp + operasional + lain_lain
    
    # Saldo akhir
    saldo = total_pemasukan - total_pengeluaran

    # Ambil status kasbon
    kasbon_state = KasbonState.query.first()

    return render_template(
        "cashflow.html",
        data=data,
        pemasukan=pemasukan,
        hpp=hpp,
        operasional=operasional,
        lain_lain=lain_lain,
        saldo=saldo,
        months=months,
        years=years,
        selected_month=selected_month,
        selected_year=selected_year,
        kasbon_state=kasbon_state,
        modal=modal,
        funding=funding  # TAMBAHKAN FUNDING
    )

# ============================
# EDIT CASHFLOW
# ============================
@main_bp.route('/edit_cashflow/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_cashflow(id):
    cashflow = Cashflow.query.get_or_404(id)
    
    if request.method == 'POST':
        try:
            # Simpan nilai lama untuk logika kasbon
            old_jenis = cashflow.jenis
            old_harga = cashflow.harga
            
            # Update data
            cashflow.tanggal = datetime.strptime(request.form['tanggal'], '%Y-%m-%d')
            cashflow.nama_barang = request.form['nama_barang']
            cashflow.jenis = request.form['jenis']
            cashflow.jumlah = request.form.get('jumlah', '')
            cashflow.satuan = request.form.get('satuan', '')
            cashflow.harga = float(request.form['harga'])
            cashflow.keterangan = request.form.get('keterangan', '')
            cashflow.catatan_tambahan = request.form.get('catatan_tambahan', '')
            
            # LOGIKA KASBON UNTUK EDIT
            kasbon_state = KasbonState.query.first()
            if not kasbon_state:
                kasbon_state = KasbonState(total_utang=0.0)
                db.session.add(kasbon_state)
            
            # Jika ada perubahan pada jenis atau harga yang berkaitan dengan kasbon
            if old_jenis in ['KASBON', 'BAYAR KASBON'] or cashflow.jenis in ['KASBON', 'BAYAR KASBON']:
                # Reverse efek dari data lama
                if old_jenis == 'KASBON':
                    kasbon_state.total_utang -= old_harga
                elif old_jenis == 'BAYAR KASBON':
                    kasbon_state.total_utang += old_harga
                
                # Terapkan efek dari data baru
                if cashflow.jenis == 'KASBON':
                    kasbon_state.total_utang += cashflow.harga
                    flash(f"Kasbon diperbarui. Total utang kasbon: {format_currency(kasbon_state.total_utang)}", "info")
                elif cashflow.jenis == 'BAYAR KASBON':
                    if cashflow.harga > kasbon_state.total_utang:
                        flash(f"Pembayaran kasbon melebihi total utang! Total utang saat ini: {format_currency(kasbon_state.total_utang)}", "warning")
                        db.session.rollback()
                        return redirect(url_for('main.edit_cashflow', id=id))
                    else:
                        kasbon_state.total_utang -= cashflow.harga
                        flash(f"Pembayaran kasbon diperbarui. Sisa utang: {format_currency(kasbon_state.total_utang)}", "success")
            
            db.session.commit()
            flash('Data cashflow berhasil diperbarui!', 'success')
            return redirect(url_for('main.cashflow'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Gagal memperbarui data: {str(e)}', 'danger')
    
    return render_template('edit_cashflow.html', data=cashflow)

# ============================
# HAPUS CASHFLOW
# ============================
@main_bp.route('/hapus_cashflow/<int:id>')
@login_required
def hapus_cashflow(id):
    data = Cashflow.query.get_or_404(id)
    try:
        db.session.delete(data)
        db.session.commit()
        flash('Data cashflow berhasil dihapus', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Gagal menghapus data: {str(e)}', 'danger')
    return redirect(url_for('main.cashflow'))

# ===== EXPORT EXCEL =====
@main_bp.route('/export_cashflow_excel')
@login_required
def export_cashflow_excel():
    data = Cashflow.query.order_by(Cashflow.tanggal.desc()).all()

    # Buat dataframe dari data
    df = pd.DataFrame([{
        'Tanggal': c.tanggal.strftime('%d-%m-%Y'),
        'Nama Barang / Jasa': c.nama_barang,
        'Kategori': kategori_besar(c.jenis),
        'Keterangan': c.jumlah,
        'Satuan': c.satuan,
        'Nilai Total': c.harga,
        'Catatan': c.keterangan
    } for c in data])

    # Buat file Excel di memory
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Cashflow')
    output.seek(0)

    return send_file(output, download_name="cashflow.xlsx", as_attachment=True)

# ============================
# PRINT CASHFLOW
# ============================
@main_bp.route('/print_cashflow')
@login_required
def print_cashflow():
    """Mencetak laporan cashflow"""
    try:
        # Ambil parameter filter
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        kategori_besar = request.args.get('kategori_besar', '')
        
        # Query data cashflow
        query = Cashflow.query
        
        if start_date:
            start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
            query = query.filter(Cashflow.tanggal >= start_date)
        
        if end_date:
            end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
            query = query.filter(Cashflow.tanggal <= end_date)
        
        if kategori_besar:
            query = query.filter(Cashflow.kategori_besar == kategori_besar)
        
        data = query.order_by(Cashflow.tanggal.desc()).all()
        
        # Hitung total untuk setiap kategori
        pemasukan = sum(item.harga for item in data if item.jenis in [
            'PENJUALAN TUNAI', 'PENERIMAAN PIUTANG', 'PINJAMAN / CASH INJECTION',
            'PENDAPATAN BUNGA', 'PENGEMBALIAN PAJAK', 'PENERIMAAN TUNAI LAINNYA',
            'FUNDING', 'BAYAR KASBON'
        ])
        
        hpp = sum(item.harga for item in data if item.jenis in [
            'BIAYA PRODUK / LAYANAN LANGSUNG', 'PAJAK PENGGAJIAN - LANGSUNG',
            'GAJI - TKL', 'PERSEDIAAN', 'LAINNYA'
        ])
        
        operasional = sum(item.harga for item in data if item.jenis in [
            'GAJI KARYAWAN', 'IKLAN', 'BIAYA BANK', 'PELATIHAN', 'ASURANSI',
            'INTERNET', 'LISENSI / IZIN', 'MAKANAN / HIBURAN', 'PERALATAN KANTOR',
            'PAJAK GAJI', 'ONGKOS KIRIM', 'PENCETAKAN', 'KONSULTAN', 'OKUPANSI',
            'BIAYA SEWA', 'SUBCONTRACTOR', 'TELEPON', 'TRANSPORTASI', 'PERJALANAN DINAS',
            'BIAYA LISTRIK', 'PENGEMBANGAN WEB', 'DOMAIN WEB DAN HOSTING', 'BIAYA AIR',
            'BIAYA SUBSCRIPTION', 'PAJAK PEMBELIAN', 'LAINNYA'
        ])
        
        lain_lain = sum(item.harga for item in data if item.jenis in [
            'PENGELUARAN TUNAI UNTUK PEMILIK', 'KASBON', 'BEBAN BUNGA',
            'BEBAN PAJAK PENGHASILAN', 'BIAYA ADMIN', 'LAINNYA', 'KEWAJIBAN'
        ])
        
        # Hitung saldo akhir
        saldo = pemasukan - (hpp + operasional + lain_lain)
        
        # Fungsi helper untuk format currency
        def format_currency(value):
            if value is None:
                value = 0
            return f"Rp {int(value):,}".replace(',', '.')
        
        def current_datetime():
            return datetime.now()
        
        return render_template('print_cashflow.html', 
                             data=data,
                             kategori_besar=kategori_besar,
                             pemasukan=pemasukan or 0,
                             hpp=hpp or 0,
                             operasional=operasional or 0,
                             lain_lain=lain_lain or 0,
                             saldo=saldo or 0,
                             start_date=start_date,
                             end_date=end_date,
                             format_currency=format_currency,
                             now=current_datetime)
                             
    except Exception as e:
        flash(f'Error generating report: {str(e)}', 'error')
        return redirect(url_for('main.cashflow'))

# -------------------- ASET TETAP --------------------
@main_bp.route('/aset_tetap', methods=['GET'])
@login_required
def aset_tetap():
    aset_list = AsetTetap.query.order_by(AsetTetap.tanggal_perolehan.desc()).all()
    data_aset = []

    for aset in aset_list:
        penyusutan_tahunan, nilai_buku = hitung_penyusutan(aset)
        schedule = jadwal_penyusutan(aset)
        data_aset.append({
            "aset": aset,
            "penyusutan_tahunan": penyusutan_tahunan,
            "nilai_buku": nilai_buku,
            "penyusutan_schedule": schedule
        })

    return render_template("aset_tetap.html", data_aset=data_aset)

# --- Tambah Aset Tetap ---
@main_bp.route('/tambah_aset_tetap', methods=['POST'])
@login_required
def tambah_aset_tetap():
    try:
        nama_aset = request.form.get('nama_aset')
        manufaktur = request.form.get('manufaktur')
        tanggal_perolehan_str = request.form.get('tanggal_perolehan')
        harga_perolehan = float(request.form.get('harga_perolehan', 0))
        umur_ekonomis = int(request.form.get('umur_ekonomis', 0))
        nilai_sisa = float(request.form.get('nilai_sisa', 0))

        if not all([nama_aset, tanggal_perolehan_str, harga_perolehan > 0, umur_ekonomis > 0]):
            flash('Harap isi semua field yang wajib diisi.', 'warning')
            return redirect(url_for('main.aset_tetap'))

        new_aset = AsetTetap(
            nama_aset=nama_aset,
            manufaktur=manufaktur,
            tanggal_perolehan=datetime.strptime(tanggal_perolehan_str, '%Y-%m-%d').date(),
            harga_perolehan=harga_perolehan,
            umur_ekonomis=umur_ekonomis,
            nilai_sisa=nilai_sisa
        )
        db.session.add(new_aset)
        db.session.commit()
        flash('Aset tetap berhasil ditambahkan!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Gagal menambahkan aset: {str(e)}', 'danger')

    return redirect(url_for('main.aset_tetap'))

# --- Edit Aset Tetap ---
@main_bp.route('/edit_aset_tetap/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_aset_tetap(id):
    aset = AsetTetap.query.get_or_404(id)

    if request.method == 'POST':
        try:
            aset.nama_aset = request.form.get('nama_aset')
            aset.manufaktur = request.form.get('manufaktur')
            aset.tanggal_perolehan = datetime.strptime(request.form.get('tanggal_perolehan'), '%Y-%m-%d').date()
            aset.harga_perolehan = float(request.form.get('harga_perolehan'))
            aset.umur_ekonomis = int(request.form.get('umur_ekonomis'))
            aset.nilai_sisa = float(request.form.get('nilai_sisa', 0))

            db.session.commit()
            flash('Aset tetap berhasil diperbarui!', 'success')
            return redirect(url_for('main.aset_tetap'))
        except Exception as e:
            db.session.rollback()
            flash(f'Gagal memperbarui aset: {str(e)}', 'danger')

    return render_template('edit_aset_tetap.html', aset=aset)

# --- Hapus Aset Tetap ---
@main_bp.route('/hapus_aset_tetap/<int:id>', methods=['POST'])
@login_required
def hapus_aset_tetap(id):
    aset = AsetTetap.query.get_or_404(id)
    try:
        db.session.delete(aset)
        db.session.commit()
        flash('Aset tetap berhasil dihapus!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Gagal menghapus aset: {str(e)}', 'danger')
    return redirect(url_for('main.aset_tetap'))

# -------------------- NERACA --------------------
@main_bp.route('/neraca')
@login_required
def neraca():
    """
    Menampilkan laporan neraca berdasarkan filter bulan dan tahun.
    """
    # --- DEFINE KATEGORI YANG SAMA DENGAN CASHFLOW & DASHBOARD ---
    
    # MODAL AWAL
    modal_jenis = [
        'SETORAN MODAL AWAL', 'TAMBAHAN MODAL', 'INVESTASI PEMILIK'
    ]
    
    # PEMASUKAN OPERASIONAL
    pemasukan_jenis = [
        'PENJUALAN TUNAI', 'PENERIMAAN PIUTANG', 'PENDAPATAN BUNGA', 
        'PENGEMBALIAN PAJAK', 'PENERIMAAN TUNAI LAINNYA', 'BAYAR KASBON'
    ]
    
    # PINJAMAN/FUNDING
    funding_jenis = [
        'PINJAMAN BANK', 'CASH INJECTION', 'DANA PINJAMAN', 'FUNDING INVESTOR'
    ]
    
    # HPP
    hpp_jenis = [
        'BIAYA PRODUK / LAYANAN LANGSUNG', 'PAJAK PENGGAJIAN - LANGSUNG',
        'GAJI - TKL', 'PERSEDIAAN'
    ]
    
    # OPERASIONAL
    operasional_jenis = [
        'GAJI KARYAWAN', 'IKLAN', 'BIAYA BANK', 'PELATIHAN', 'ASURANSI',
        'INTERNET', 'LISENSI / IZIN', 'MAKANAN / HIBURAN', 'PERALATAN KANTOR',
        'PAJAK GAJI', 'ONGKOS KIRIM', 'PENCETAKAN', 'KONSULTAN', 'OKUPANSI',
        'BIAYA SEWA', 'SUBCONTRACTOR', 'TELEPON', 'TRANSPORTASI', 'PERJALANAN DINAS',
        'BIAYA LISTRIK', 'PENGEMBANGAN WEB', 'DOMAIN WEB DAN HOSTING', 'BIAYA AIR',
        'BIAYA SUBSCRIPTION', 'PAJAK PEMBELIAN'
    ]
    
    # PENGELUARAN LAIN-LAIN
    lain_jenis = [
        'PENGELUARAN TUNAI UNTUK PEMILIK', 'KASBON', 'BEBAN BUNGA',
        'BEBAN PAJAK PENGHASILAN', 'BIAYA ADMIN', 'LAINNYA', 'KEWAJIBAN'
    ]

    # --- 1. Ambil Filter dan Tentukan Periode ---
    selected_month = request.args.get('month', type=int)
    selected_year = request.args.get('year', type=int)

    if selected_month and selected_year:
        from calendar import monthrange
        last_day_of_month = monthrange(selected_year, selected_month)[1]
        periode_akhir = datetime(selected_year, selected_month, last_day_of_month, 23, 59, 59)
    else:
        periode_akhir = datetime.now()

    # --- 2. Hitung Total ASET ---
    
    # Aset Lancar (Kas) - Hitung dari cashflow
    cashflows_sampai_periode = Cashflow.query.filter(
        Cashflow.tanggal <= periode_akhir
    ).all()

    # Hitung total pemasukan (Modal + Pemasukan Operasional + Funding)
    total_modal = 0
    total_pemasukan_operasional = 0
    total_funding = 0
    total_pengeluaran = 0
    
    for cf in cashflows_sampai_periode:
        if cf.jenis in modal_jenis:
            total_modal += cf.harga
        elif cf.jenis in pemasukan_jenis:
            total_pemasukan_operasional += cf.harga
        elif cf.jenis in funding_jenis or cf.jenis in ['PINJAMAN / CASH INJECTION', 'FUNDING']:
            total_funding += cf.harga
        elif cf.jenis in hpp_jenis + operasional_jenis + lain_jenis:
            total_pengeluaran += cf.harga

    # Total Kas = (Modal + Pemasukan Operasional + Funding) - Pengeluaran
    total_kas = (total_modal + total_pemasukan_operasional + total_funding) - total_pengeluaran

    # Aset Tetap (Nilai Buku)
    aset_tetap_list = AsetTetap.query.all()
    total_nilai_aset_tetap = 0
    for aset in aset_tetap_list:
        try:
            _, nilai_buku = hitung_penyusutan(aset)
            total_nilai_aset_tetap += nilai_buku
        except Exception as e:
            print(f"Error hitung penyusutan aset {aset.id}: {e}")
            continue

    # Piutang (jika ada)
    piutang_total = 0  # Bisa dikembangkan jika ada sistem piutang

    total_aset = total_kas + total_nilai_aset_tetap + piutang_total

    # --- 3. Hitung Total EKUITAS ---
    
    # Modal Awal (total dari kategori modal)
    modal_awal = total_modal
    
    # Prive (penarikan oleh pemilik)
    prive = sum(cf.harga for cf in cashflows_sampai_periode 
                if cf.jenis == 'PENGELUARAN TUNAI UNTUK PEMILIK')

    # Laba/Rugi Berjalan (Pemasukan Operasional - Pengeluaran Operasional)
    pengeluaran_operasional = sum(cf.harga for cf in cashflows_sampai_periode 
                                 if cf.jenis in hpp_jenis + operasional_jenis + lain_jenis)
    
    laba_rugi_berjalan = total_pemasukan_operasional - pengeluaran_operasional

    # Total Ekuitas = Modal Awal + Laba/Rugi Berjalan - Prive
    total_ekuitas = modal_awal + laba_rugi_berjalan - prive

    # --- 4. Hitung KEWAJIBAN (jika ada funding/pinjaman) ---
    total_funding_aktif = total_funding  # Funding dianggap sebagai kewajiban
    
    # Utang Kasbon
    kasbon_state = KasbonState.query.first()
    total_utang_kasbon = kasbon_state.total_utang if kasbon_state else 0

    total_kewajiban = total_funding_aktif + total_utang_kasbon

    # --- 5. Siapkan Data untuk Template ---
    neraca_data = {
        'aset': {
            'Aset Lancar': {
                'Kas': total_kas,
                'Piutang': piutang_total
            },
            'Aset Tetap': {
                f'Aset Tetap ({len(aset_tetap_list)} unit)': total_nilai_aset_tetap
            },
            'Total Aset': total_aset
        },
        'kewajiban_dan_ekuitas': {
            'Kewajiban': {
                'Pinjaman/Funding': total_funding_aktif,
                'Utang Kasbon': total_utang_kasbon
            },
            'Ekuitas': {
                'Modal': modal_awal,
                'Laba/Rugi Berjalan': laba_rugi_berjalan,
                'Prive': -prive,  # Prive selalu negatif di ekuitas
            },
            'Total Ekuitas': total_ekuitas,
            'Total Kewajiban & Ekuitas': total_kewajiban + total_ekuitas
        }
    }

    # Hapus kewajiban jika tidak ada nilai
    if total_kewajiban == 0:
        del neraca_data['kewajiban_dan_ekuitas']['Kewajiban']

    # --- 6. Siapkan Data Tambahan untuk Template ---
    hari_ini = periode_akhir.strftime('%d %B %Y')
    
    months = [(i, name) for i, name in enumerate(
        ["Januari", "Februari", "Maret", "April", "Mei", "Juni", 
         "Juli", "Agustus", "September", "Oktober", "November", "Desember"], 1
    )]

    years_from_db = db.session.query(extract('year', Cashflow.tanggal)).distinct().all()
    years_in_db = {int(year[0]) for year in years_from_db if year[0]}
    current_year = datetime.now().year
    year_range = {current_year - 2, current_year - 1, current_year, current_year + 1, current_year + 2}
    years = sorted(list(years_in_db.union(year_range)))

    # --- 7. Debug Information ---
    print("="*50)
    print("DEBUG NERACA:")
    print(f"Periode: {hari_ini}")
    print(f"Total Kas: {total_kas:,.0f}")
    print(f"Modal: {modal_awal:,.0f}")
    print(f"Pemasukan Operasional: {total_pemasukan_operasional:,.0f}")
    print(f"Funding: {total_funding:,.0f}")
    print(f"Pengeluaran: {pengeluaran_operasional:,.0f}")
    print(f"Laba/Rugi: {laba_rugi_berjalan:,.0f}")
    print(f"Prive: {prive:,.0f}")
    print(f"Total Ekuitas: {total_ekuitas:,.0f}")
    print(f"Total Kewajiban: {total_kewajiban:,.0f}")
    print(f"Total Aset: {total_aset:,.0f}")
    print(f"Total Kewajiban + Ekuitas: {total_kewajiban + total_ekuitas:,.0f}")
    print("="*50)

    # --- 8. Render Template ---
    return render_template(
        "neraca.html",
        neraca_data=neraca_data,
        hari_ini=hari_ini,
        months=months,
        years=years,
        selected_month=selected_month,
        selected_year=selected_year
    )

# -------------------- LAPORAN LABA RUGI --------------------
@main_bp.route('/laporan')
@login_required
def laporan():
    """
    Menampilkan Laporan Laba Rugi yang dinamis.
    """
    # Ambil filter dari query string
    selected_month = request.args.get('month', type=int)
    selected_year = request.args.get('year', type=int)

    # --- DEFINE KATEGORI BARU SESUAI CASHFLOW (SAMA DENGAN DASHBOARD) ---
    # PEMASUKAN
    pemasukan_jenis = [
        'PENJUALAN TUNAI', 'PENERIMAAN PIUTANG', 'PINJAMAN / CASH INJECTION',
        'PENDAPATAN BUNGA', 'PENGEMBALIAN PAJAK', 'PENERIMAAN TUNAI LAINNYA',
        'FUNDING', 'BAYAR KASBON', 'LAINNYA'
    ]
    
    # HPP (Harga Pokok Penjualan)
    hpp_jenis = [
        'BIAYA PRODUK / LAYANAN LANGSUNG', 'PAJAK PENGGAJIAN - LANGSUNG',
        'GAJI - TKL', 'PERSEDIAAN', 'LAINNYA'
    ]
    
    # BEBAN OPERASIONAL
    beban_operasional_jenis = [
        'GAJI KARYAWAN', 'IKLAN', 'BIAYA BANK', 'PELATIHAN', 'ASURANSI',
        'INTERNET', 'LISENSI / IZIN', 'MAKANAN / HIBURAN', 'PERALATAN KANTOR',
        'PAJAK GAJI', 'ONGKOS KIRIM', 'PENCETAKAN', 'KONSULTAN', 'OKUPANSI',
        'BIAYA SEWA', 'SUBCONTRACTOR', 'TELEPON', 'TRANSPORTASI', 'PERJALANAN DINAS',
        'BIAYA LISTRIK', 'PENGEMBALIAN WEB', 'DOMAIN WEB DAN HOSTING', 'BIAYA AIR',
        'BIAYA SUBSCRIPTION', 'PAJAK PEMBELIAN', 'LAINNYA'
    ]
    
    # BEBAN LAIN-LAIN
    beban_lain_jenis = [
        'PENGELUARAN TUNAI UNTUK PEMILIK', 'KASBON', 'BEBAN BUNGA',
        'BEBAN PAJAK PENGHASILAN', 'BIAYA ADMIN', 'LAINNYA', 'KEWAJIBAN'
    ]

    # Tentukan periode akhir
    if selected_month and selected_year:
        from calendar import monthrange
        last_day_of_month = monthrange(selected_year, selected_month)[1]
        periode_akhir = datetime(selected_year, selected_month, last_day_of_month, 23, 59, 59)
        periode_awal = datetime(selected_year, selected_month, 1)
    else:
        # Jika tidak ada filter, tampilkan data sampai hari ini
        periode_akhir = datetime.now()
        periode_awal = datetime(periode_akhir.year, periode_akhir.month, 1)

    # --- DEBUG: Lihat data yang difilter ---
    print("="*50)
    print("LAPORAN DATA - FILTER")
    print(f"Periode: {periode_awal} sampai {periode_akhir}")
    print(f"Selected Month: {selected_month}, Selected Year: {selected_year}")

    # --- 1. Hitung PENDAPATAN (PEMASUKAN) ---
    total_pemasukan = db.session.query(db.func.sum(Cashflow.harga)).filter(
        Cashflow.jenis.in_(pemasukan_jenis),
        Cashflow.tanggal <= periode_akhir
    ).scalar() or 0

    # Pemasukan periode berjalan (jika filter bulan)
    if selected_month and selected_year:
        pemasukan_periode = db.session.query(db.func.sum(Cashflow.harga)).filter(
            Cashflow.jenis.in_(pemasukan_jenis),
            Cashflow.tanggal >= periode_awal,
            Cashflow.tanggal <= periode_akhir
        ).scalar() or 0
    else:
        pemasukan_periode = total_pemasukan

    # --- 2. Hitung HARGA POKOK PENJUALAN (HPP) ---
    total_hpp = db.session.query(db.func.sum(Cashflow.harga)).filter(
        Cashflow.jenis.in_(hpp_jenis),
        Cashflow.tanggal <= periode_akhir
    ).scalar() or 0

    # HPP periode berjalan
    if selected_month and selected_year:
        hpp_periode = db.session.query(db.func.sum(Cashflow.harga)).filter(
            Cashflow.jenis.in_(hpp_jenis),
            Cashflow.tanggal >= periode_awal,
            Cashflow.tanggal <= periode_akhir
        ).scalar() or 0
    else:
        hpp_periode = total_hpp

    laba_kotor = total_pemasukan - total_hpp
    laba_kotor_periode = pemasukan_periode - hpp_periode

    # --- 3. Hitung BEBAN OPERASIONAL ---
    total_beban_operasional = db.session.query(db.func.sum(Cashflow.harga)).filter(
        Cashflow.jenis.in_(beban_operasional_jenis),
        Cashflow.tanggal <= periode_akhir
    ).scalar() or 0

    # Beban operasional periode berjalan
    if selected_month and selected_year:
        beban_operasional_periode = db.session.query(db.func.sum(Cashflow.harga)).filter(
            Cashflow.jenis.in_(beban_operasional_jenis),
            Cashflow.tanggal >= periode_awal,
            Cashflow.tanggal <= periode_akhir
        ).scalar() or 0
    else:
        beban_operasional_periode = total_beban_operasional

    # --- 4. Hitung BEBAN LAIN-LAIN ---
    total_beban_lain = db.session.query(db.func.sum(Cashflow.harga)).filter(
        Cashflow.jenis.in_(beban_lain_jenis),
        Cashflow.tanggal <= periode_akhir
    ).scalar() or 0

    # Beban lain periode berjalan
    if selected_month and selected_year:
        beban_lain_periode = db.session.query(db.func.sum(Cashflow.harga)).filter(
            Cashflow.jenis.in_(beban_lain_jenis),
            Cashflow.tanggal >= periode_awal,
            Cashflow.tanggal <= periode_akhir
        ).scalar() or 0
    else:
        beban_lain_periode = total_beban_lain

    # --- 5. Hitung LABA BERSIH ---
    laba_bersih = laba_kotor - (total_beban_operasional + total_beban_lain)
    laba_bersih_periode = laba_kotor_periode - (beban_operasional_periode + beban_lain_periode)

    # --- 6. Hitung DETAIL PER KATEGORI untuk breakdown ---
    # Detail pemasukan per jenis
    detail_pemasukan = []
    for jenis in pemasukan_jenis:
        jumlah = db.session.query(db.func.sum(Cashflow.harga)).filter(
            Cashflow.jenis == jenis,
            Cashflow.tanggal <= periode_akhir
        ).scalar() or 0
        if jumlah > 0:
            detail_pemasukan.append({
                'jenis': jenis,
                'jumlah': jumlah
            })

    # Detail HPP per jenis
    detail_hpp = []
    for jenis in hpp_jenis:
        jumlah = db.session.query(db.func.sum(Cashflow.harga)).filter(
            Cashflow.jenis == jenis,
            Cashflow.tanggal <= periode_akhir
        ).scalar() or 0
        if jumlah > 0:
            detail_hpp.append({
                'jenis': jenis,
                'jumlah': jumlah
            })

    # Detail beban operasional per jenis
    detail_beban_operasional = []
    for jenis in beban_operasional_jenis:
        jumlah = db.session.query(db.func.sum(Cashflow.harga)).filter(
            Cashflow.jenis == jenis,
            Cashflow.tanggal <= periode_akhir
        ).scalar() or 0
        if jumlah > 0:
            detail_beban_operasional.append({
                'jenis': jenis,
                'jumlah': jumlah
            })

    # Detail beban lain per jenis
    detail_beban_lain = []
    for jenis in beban_lain_jenis:
        jumlah = db.session.query(db.func.sum(Cashflow.harga)).filter(
            Cashflow.jenis == jenis,
            Cashflow.tanggal <= periode_akhir
        ).scalar() or 0
        if jumlah > 0:
            detail_beban_lain.append({
                'jenis': jenis,
                'jumlah': jumlah
            })

    # --- 7. Hitung MARGIN ---
    margin_kotor = (laba_kotor / total_pemasukan * 100) if total_pemasukan > 0 else 0
    margin_bersih = (laba_bersih / total_pemasukan * 100) if total_pemasukan > 0 else 0

    # --- 8. Siapkan Data Tambahan untuk Template ---
    if selected_month and selected_year:
        hari_ini = periode_akhir.strftime('%d %B %Y')
        judul_periode = f"Periode {periode_awal.strftime('%d %B %Y')} - {periode_akhir.strftime('%d %B %Y')}"
    else:
        hari_ini = "Sampai " + periode_akhir.strftime('%d %B %Y')
        judul_periode = f"Kumulatif Sampai {periode_akhir.strftime('%d %B %Y')}"
    
    waktu_cetak = datetime.now().strftime('%d-%m-%Y %H:%M')
    
    months = [(i, name) for i, name in enumerate(
        ["Januari", "Februari", "Maret", "April", "Mei", "Juni", 
         "Juli", "Agustus", "September", "Oktober", "November", "Desember"], 1
    )]
    
    years_from_db = db.session.query(extract('year', Cashflow.tanggal)).distinct().all()
    years_in_db = {int(year[0]) for year in years_from_db if year[0]}
    current_year = datetime.now().year
    year_range = {current_year - 2, current_year - 1, current_year, current_year + 1, current_year + 2}
    years = sorted(list(years_in_db.union(year_range)))

    # --- DEBUG FINAL ---
    print("="*50)
    print("LAPORAN DATA - FINAL")
    print(f"Total Pemasukan: {total_pemasukan}")
    print(f"Total HPP: {total_hpp}")
    print(f"Laba Kotor: {laba_kotor}")
    print(f"Beban Operasional: {total_beban_operasional}")
    print(f"Beban Lain: {total_beban_lain}")
    print(f"Laba Bersih: {laba_bersih}")
    print(f"Margin Kotor: {margin_kotor:.1f}%")
    print(f"Margin Bersih: {margin_bersih:.1f}%")
    print("="*50)

    return render_template(
        "laporan.html",
        # Data utama
        total_pemasukan=total_pemasukan,
        total_hpp=total_hpp,
        laba_kotor=laba_kotor,
        total_beban_operasional=total_beban_operasional,
        total_beban_lain=total_beban_lain,
        laba_bersih=laba_bersih,
        
        # Data periode berjalan (jika difilter)
        pemasukan_periode=pemasukan_periode,
        hpp_periode=hpp_periode,
        laba_kotor_periode=laba_kotor_periode,
        beban_operasional_periode=beban_operasional_periode,
        beban_lain_periode=beban_lain_periode,
        laba_bersih_periode=laba_bersih_periode,
        
        # Data detail breakdown
        detail_pemasukan=detail_pemasukan,
        detail_hpp=detail_hpp,
        detail_beban_operasional=detail_beban_operasional,
        detail_beban_lain=detail_beban_lain,
        
        # Data margin
        margin_kotor=margin_kotor,
        margin_bersih=margin_bersih,
        
        # Metadata
        hari_ini=hari_ini,
        judul_periode=judul_periode,
        waktu_cetak=waktu_cetak,
        months=months,
        years=years,
        selected_month=selected_month,
        selected_year=selected_year,
        
        # Kategori untuk reference
        pemasukan_jenis=pemasukan_jenis,
        hpp_jenis=hpp_jenis,
        beban_operasional_jenis=beban_operasional_jenis,
        beban_lain_jenis=beban_lain_jenis
    )

# -------------------- FAKTUR ROUTES --------------------
@main_bp.route('/faktur')
@login_required
def faktur():
    """
    Menampilkan daftar semua faktur.
    """
    try:
        faktur_list = Faktur.query.order_by(Faktur.tanggal_faktur.desc()).all()
        return render_template("faktur.html", faktur=faktur_list)
    except Exception as e:
        flash('Error mengambil data faktur: ' + str(e), 'error')
        return render_template("faktur.html", faktur=[])

@main_bp.route('/buat_faktur', methods=['GET', 'POST'])
@login_required
def buat_faktur():
    """
    Membuat faktur baru.
    """
    if request.method == 'POST':
        try:
            # Ambil data dari form
            nomor_faktur = request.form.get('nomor_faktur')
            nama_pelanggan = request.form.get('nama_pelanggan')
            tanggal_faktur = datetime.strptime(request.form.get('tanggal_faktur'), '%Y-%m-%d')
            alamat_pelanggan = request.form.get('alamat_pelanggan', '')
            keterangan = request.form.get('keterangan', '')
            total_harga = float(request.form.get('total_harga', 0))
            
            # Buat faktur baru
            faktur_baru = Faktur(
                nomor_faktur=nomor_faktur,
                nama_pelanggan=nama_pelanggan,
                tanggal_faktur=tanggal_faktur,
                alamat_pelanggan=alamat_pelanggan,
                keterangan=keterangan,
                total_harga=total_harga
            )
            
            db.session.add(faktur_baru)
            db.session.flush()  # Dapatkan ID faktur
            
            # Tambahkan item faktur
            nama_barang_list = request.form.getlist('nama_barang[]')
            jumlah_list = request.form.getlist('jumlah[]')
            harga_list = request.form.getlist('harga[]')
            
            for i in range(len(nama_barang_list)):
                if nama_barang_list[i] and jumlah_list[i] and harga_list[i]:
                    jumlah = float(jumlah_list[i])
                    harga = float(harga_list[i])
                    subtotal = jumlah * harga
                    
                    item = ItemFaktur(
                        faktur_id=faktur_baru.id,
                        nama_barang=nama_barang_list[i],
                        jumlah=jumlah,
                        harga=harga,
                        subtotal=subtotal
                    )
                    db.session.add(item)
            
            db.session.commit()
            flash('Faktur berhasil dibuat!', 'success')
            return redirect(url_for('main.detail_faktur', id=faktur_baru.id))
            
        except Exception as e:
            db.session.rollback()
            flash('Error membuat faktur: ' + str(e), 'error')
            return render_template("buat_faktur.html")
    
    # GET request - tampilkan form
    return render_template("buat_faktur.html")

@main_bp.route('/faktur/<int:id>')
@login_required
def detail_faktur(id):
    """
    Menampilkan detail faktur.
    """
    try:
        faktur = Faktur.query.get_or_404(id)
        return render_template("detail_faktur.html", faktur=faktur)
    except Exception as e:
        flash('Error mengambil data faktur: ' + str(e), 'error')
        return redirect(url_for('main.faktur'))

@main_bp.route('/faktur/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_faktur(id):
    """
    Mengedit faktur.
    """
    faktur = Faktur.query.get_or_404(id)
    
    if request.method == 'POST':
        try:
            # Update data faktur
            faktur.nomor_faktur = request.form.get('nomor_faktur')
            faktur.nama_pelanggan = request.form.get('nama_pelanggan')
            faktur.tanggal_faktur = datetime.strptime(request.form.get('tanggal_faktur'), '%Y-%m-%d')
            faktur.alamat_pelanggan = request.form.get('alamat_pelanggan', '')
            faktur.keterangan = request.form.get('keterangan', '')
            faktur.total_harga = float(request.form.get('total_harga', 0))
            
            # Hapus item lama
            ItemFaktur.query.filter_by(faktur_id=id).delete()
            
            # Tambahkan item baru
            nama_barang_list = request.form.getlist('nama_barang[]')
            jumlah_list = request.form.getlist('jumlah[]')
            harga_list = request.form.getlist('harga[]')
            
            total_harga_baru = 0
            
            for i in range(len(nama_barang_list)):
                if nama_barang_list[i] and jumlah_list[i] and harga_list[i]:
                    jumlah = float(jumlah_list[i])
                    harga = float(harga_list[i])
                    subtotal = jumlah * harga
                    total_harga_baru += subtotal
                    
                    item = ItemFaktur(
                        faktur_id=id,
                        nama_barang=nama_barang_list[i],
                        jumlah=jumlah,
                        harga=harga,
                        subtotal=subtotal
                    )
                    db.session.add(item)
            
            # Update total harga
            faktur.total_harga = total_harga_baru
            
            db.session.commit()
            flash('Faktur berhasil diupdate!', 'success')
            return redirect(url_for('main.detail_faktur', id=id))
            
        except Exception as e:
            db.session.rollback()
            flash('Error mengupdate faktur: ' + str(e), 'error')
    
    return render_template("edit_faktur.html", faktur=faktur)

@main_bp.route('/faktur/<int:id>/hapus', methods=['POST'])
@login_required
def hapus_faktur(id):
    """
    Menghapus faktur.
    """
    try:
        faktur = Faktur.query.get_or_404(id)
        
        # Hapus item faktur terlebih dahulu
        ItemFaktur.query.filter_by(faktur_id=id).delete()
        
        # Hapus faktur
        db.session.delete(faktur)
        db.session.commit()
        
        flash('Faktur berhasil dihapus!', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Error menghapus faktur: ' + str(e), 'error')
    
    return redirect(url_for('main.faktur'))


@main_bp.route('/faktur/<int:id>/print')
@login_required
def print_faktur(id):
    """
    Menampilkan versi print-friendly dari faktur.
    """
    try:
        faktur = Faktur.query.get_or_404(id)
        return render_template("print_faktur.html", faktur=faktur)
    except Exception as e:
        flash('Error mencetak faktur: ' + str(e), 'error')
        return redirect(url_for('main.detail_faktur', id=id))

@main_bp.route('/faktur/<int:id>/kirim_email', methods=['POST'])
@login_required
def kirim_email_faktur(id):
    """
    Mengirim faktur via email.
    """
    try:
        faktur = Faktur.query.get_or_404(id)
        email_tujuan = request.form.get('email_tujuan')
        
        if not email_tujuan:
            flash('Alamat email tujuan harus diisi!', 'error')
            return redirect(url_for('main.print_faktur', id=id))
        
        # Validasi format email
        if '@' not in email_tujuan or '.' not in email_tujuan:
            flash('Format email tidak valid!', 'error')
            return redirect(url_for('main.print_faktur', id=id))
        
        # Cek apakah service email tersedia
        try:
            from daniar_app.services.email_service import send_faktur_email
            send_faktur_email(faktur, email_tujuan)
            flash(f'Faktur berhasil dikirim ke {email_tujuan}!', 'success')
        except ImportError:
            # Fallback jika service email belum siap
            flash(f'Fitur email sedang dalam pengembangan. Email akan dikirim ke: {email_tujuan}', 'info')
        except Exception as e:
            current_app.logger.error(f"Error mengirim email: {str(e)}")
            flash('Error mengirim email. Silakan coba lagi.', 'error')
        
    except Exception as e:
        current_app.logger.error(f"Error mengirim email: {str(e)}")
        flash('Error mengirim email. Silakan coba lagi.', 'error')
    
    return redirect(url_for('main.print_faktur', id=id))

@main_bp.route('/test_email_config')
@login_required
def test_email_config():
    """Test konfigurasi email dengan app password baru"""
    try:
        from flask_mail import Message
        from daniar_app import mail
        from datetime import datetime
        
        msg = Message(
            subject='✅ TEST BERHASIL - PT. Daniar Furniture Art',
            sender=current_app.config['MAIL_DEFAULT_SENDER'],
            recipients=['bagasnazrililham7@gmail.com']
        )
        msg.body = f'''
TEST EMAIL BERHASIL! 🎉

PT. Daniar Furniture Art
Konfigurasi email berhasil diaktifkan.

Dikirim pada: {datetime.now().strftime("%d %B %Y %H:%M:%S")}

Sistem manajemen keuangan siap digunakan.
'''
        msg.html = f'''
<h2 style="color: #27ae60;">✅ TEST EMAIL BERHASIL!</h2>
<h3>PT. Daniar Furniture Art</h3>
<p>Konfigurasi email berhasil diaktifkan.</p>
<p><strong>Dikirim pada:</strong> {datetime.now().strftime("%d %B %Y %H:%M:%S")}</p>
<hr>
<p style="color: #666;">
    Sistem manajemen keuangan PT. Daniar Furniture Art
</p>
'''
        
        mail.send(msg)
        flash('🎉 Email test BERHASIL dikirim ke bagasnazrililham7@gmail.com!', 'success')
        
    except Exception as e:
        error_msg = f'Error mengirim email: {str(e)}'
        print(f"Email error: {error_msg}")
        flash(error_msg, 'error')
    
    return redirect(url_for('main.dashboard'))


@main_bp.route('/faktur/<int:id>/kirim_whatsapp', methods=['POST'])
@login_required
def kirim_whatsapp_faktur(id):
    """
    Mengirim faktur via WhatsApp.
    """
    try:
        faktur = Faktur.query.get_or_404(id)
        nomor_whatsapp = request.form.get('nomor_whatsapp')
        
        if not nomor_whatsapp:
            flash('Nomor WhatsApp tujuan harus diisi!', 'error')
            return redirect(url_for('main.detail_faktur', id=id))
        
        # Format nomor WhatsApp (hapus karakter non-digit)
        nomor_whatsapp = ''.join(filter(str.isdigit, nomor_whatsapp))
        
        if not nomor_whatsapp:
            flash('Format nomor WhatsApp tidak valid!', 'error')
            return redirect(url_for('main.detail_faktur', id=id))
        
        # Pastikan nomor dimulai dengan 62 (kode Indonesia)
        if nomor_whatsapp.startswith('0'):
            nomor_whatsapp = '62' + nomor_whatsapp[1:]
        elif nomor_whatsapp.startswith('8'):
            nomor_whatsapp = '62' + nomor_whatsapp
        elif nomor_whatsapp.startswith('+62'):
            nomor_whatsapp = nomor_whatsapp[1:]  # Hapus tanda +
        
        # Buat pesan WhatsApp
        pesan = f"""Halo, berikut faktur dari PT. Daniar Furniture Art:

📋 *Faktur:* {faktur.nomor_faktur}
👤 *Pelanggan:* {faktur.nama_pelanggan}
📅 *Tanggal:* {faktur.tanggal_faktur.strftime('%d/%m/%Y')}
💰 *Total:* Rp {faktur.total_harga:,.0f}

*Detail Barang:*
"""
        
        for i, item in enumerate(faktur.items, 1):
            pesan += f"{i}. {item.nama_barang}: {item.jumlah} x Rp {item.harga:,.0f} = Rp {item.subtotal:,.0f}\n"
        
        pesan += f"\n*Total:* Rp {faktur.total_harga:,.0f}"
        pesan += f"\n\nAlamat: {faktur.alamat_pelanggan or '-'}"
        if faktur.keterangan:
            pesan += f"\nKeterangan: {faktur.keterangan}"
        pesan += "\n\nTerima kasih atas kepercayaan Anda!"
        
        # Encode pesan untuk URL
        pesan_encoded = urllib.parse.quote(pesan)
        
        # Buat URL WhatsApp - PERBAIKAN DI SINI
        whatsapp_url = f"https://wa.me/{nomor_whatsapp}?text={pesan_encoded}"
        
        flash('Membuka WhatsApp...', 'info')
        return redirect(whatsapp_url)
        
    except Exception as e:
        flash('Error mengirim WhatsApp: ' + str(e), 'error')
        return redirect(url_for('main.detail_faktur', id=id))
    


@main_bp.route('/faktur/<int:id>/share')
@login_required
def share_faktur(id):
    """
    Halaman untuk memilih metode sharing faktur.
    """
    try:
        faktur = Faktur.query.get_or_404(id)
        return render_template("share_faktur.html", faktur=faktur)
    except Exception as e:
        flash('Error: ' + str(e), 'error')
        return redirect(url_for('main.detail_faktur', id=id))
    


# ----------------------------
# RAB
# ----------------------------

@main_bp.route('/rab')
@login_required
def rab():
    """Halaman daftar RAB"""
    try:
        # Ambil semua RAB dari database
        rab_list = RAB.query.order_by(RAB.tanggal.desc()).all()
        
        return render_template('rab.html', rab=rab_list)
    except Exception as e:
        flash(f'Error loading RAB: {str(e)}', 'error')
        return render_template('rab.html', rab=[])

@main_bp.route('/buat_rab', methods=['GET', 'POST'])
@login_required
def buat_rab():
    """Buat RAB baru"""
    if request.method == 'POST':
        try:
            # Ambil data dari form
            nama_proyek = request.form.get('nama_proyek')
            nama_klien = request.form.get('nama_klien')
            lokasi_proyek = request.form.get('lokasi_proyek')
            deskripsi = request.form.get('deskripsi')
            tanggal = datetime.strptime(request.form.get('tanggal'), '%Y-%m-%d')
            
            # Generate kode RAB
            last_rab = RAB.query.order_by(RAB.id.desc()).first()
            new_id = last_rab.id + 1 if last_rab else 1
            kode_rab = f"RAB-{new_id:04d}"
            
            # Buat RAB baru
            rab_baru = RAB(
                kode_rab=kode_rab,
                nama_proyek=nama_proyek,
                nama_klien=nama_klien,
                lokasi_proyek=lokasi_proyek,
                deskripsi=deskripsi,
                tanggal=tanggal,
                status='DRAFT',
                total_anggaran=0.0
            )
            
            db.session.add(rab_baru)
            db.session.flush()  # Dapat ID sebelum commit
            
            # Process items
            kategori_items = request.form.getlist('kategori_item[]')
            nama_items = request.form.getlist('nama_item[]')
            spesifikasi_items = request.form.getlist('spesifikasi[]')
            quantity_items = request.form.getlist('quantity[]')
            satuan_items = request.form.getlist('satuan[]')
            harga_satuan_items = request.form.getlist('harga_satuan[]')
            
            total_anggaran = 0
            
            for i in range(len(nama_items)):
                if nama_items[i]:  # Skip empty items
                    quantity = float(quantity_items[i]) if quantity_items[i] else 0
                    harga_satuan = float(harga_satuan_items[i]) if harga_satuan_items[i] else 0
                    total_harga = quantity * harga_satuan
                    
                    item = ItemRAB(
                        rab_id=rab_baru.id,
                        kategori_item=kategori_items[i],
                        nama_item=nama_items[i],
                        spesifikasi=spesifikasi_items[i],
                        quantity=quantity,
                        satuan=satuan_items[i] or 'unit',
                        harga_satuan=harga_satuan,
                        total_harga=total_harga
                    )
                    
                    db.session.add(item)
                    total_anggaran += total_harga
            
            # Update total anggaran
            rab_baru.total_anggaran = total_anggaran
            
            db.session.commit()
            flash('✅ RAB berhasil dibuat!', 'success')
            return redirect(url_for('main.rab'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error creating RAB: {str(e)}', 'error')
            return redirect(url_for('main.buat_rab'))
    
    # GET request - tampilkan form
    return render_template('buat_rab.html')

@main_bp.route('/detail_rab/<int:id>')
@login_required
def detail_rab(id):
    """Detail RAB"""
    try:
        rab = RAB.query.get_or_404(id)
        items = ItemRAB.query.filter_by(rab_id=id).all()
        
        return render_template('detail_rab.html', rab=rab, items=items)
    except Exception as e:
        flash(f'Error loading RAB detail: {str(e)}', 'error')
        return redirect(url_for('main.rab'))

@main_bp.route('/edit_rab/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_rab(id):
    """Edit RAB"""
    rab = RAB.query.get_or_404(id)
    
    if request.method == 'POST':
        try:
            # Update data RAB
            rab.nama_proyek = request.form.get('nama_proyek')
            rab.nama_klien = request.form.get('nama_klien')
            rab.lokasi_proyek = request.form.get('lokasi_proyek')
            rab.deskripsi = request.form.get('deskripsi')
            rab.tanggal = datetime.strptime(request.form.get('tanggal'), '%Y-%m-%d')
            rab.status = request.form.get('status', 'DRAFT')
            
            # Hapus items lama
            ItemRAB.query.filter_by(rab_id=id).delete()
            
            # Tambahkan items baru
            total_anggaran = 0
            kategori_items = request.form.getlist('kategori_item[]')
            nama_items = request.form.getlist('nama_item[]')
            spesifikasi_items = request.form.getlist('spesifikasi[]')
            quantity_items = request.form.getlist('quantity[]')
            satuan_items = request.form.getlist('satuan[]')
            harga_satuan_items = request.form.getlist('harga_satuan[]')
            
            for i in range(len(nama_items)):
                if nama_items[i]:  # Skip empty items
                    quantity = float(quantity_items[i]) if quantity_items[i] else 0
                    harga_satuan = float(harga_satuan_items[i]) if harga_satuan_items[i] else 0
                    total_harga = quantity * harga_satuan
                    
                    item = ItemRAB(
                        rab_id=id,
                        kategori_item=kategori_items[i],
                        nama_item=nama_items[i],
                        spesifikasi=spesifikasi_items[i],
                        quantity=quantity,
                        satuan=satuan_items[i] or 'unit',
                        harga_satuan=harga_satuan,
                        total_harga=total_harga
                    )
                    
                    db.session.add(item)
                    total_anggaran += total_harga
            
            # Update total anggaran
            rab.total_anggaran = total_anggaran
            
            db.session.commit()
            flash('✅ RAB berhasil diupdate!', 'success')
            return redirect(url_for('main.detail_rab', id=id))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating RAB: {str(e)}', 'error')
    
    # GET request - tampilkan form edit
    items = ItemRAB.query.filter_by(rab_id=id).all()
    return render_template('edit_rab.html', rab=rab, items=items)

@main_bp.route('/hapus_rab/<int:id>', methods=['POST'])
@login_required
def hapus_rab(id):
    """Hapus RAB"""
    try:
        rab = RAB.query.get_or_404(id)
        
        # Hapus items terlebih dahulu
        ItemRAB.query.filter_by(rab_id=id).delete()
        
        # Hapus RAB
        db.session.delete(rab)
        db.session.commit()
        
        flash('✅ RAB berhasil dihapus!', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting RAB: {str(e)}', 'error')
    
    return redirect(url_for('main.rab'))

@main_bp.route('/update_status_rab/<int:id>', methods=['POST'])
@login_required
def update_status_rab(id):
    """Update status RAB"""
    try:
        rab = RAB.query.get_or_404(id)
        
        new_status = request.json.get('status')
        if new_status in ['DRAFT', 'REVIEW', 'APPROVED', 'REJECTED']:
            rab.status = new_status
            db.session.commit()
            return jsonify({'success': True, 'message': 'Status updated!'})
        else:
            return jsonify({'success': False, 'message': 'Status tidak valid!'})
            
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})

# --- PDF & WHATSAPP ROUTES ---

def generate_pdf_report(template_name, data, filename_prefix):
    """Function untuk generate PDF"""
    try:
        # Tambahkan data umum
        data.update({
            'company_name': "PT. Daniar Furniture Art",
            'company_address': "Jln.Mesjid Kp.Kaum No.20, RT.01/RW.11, Ciparigi, Kota Bogor",
            'current_date': datetime.now().strftime('%d %B %Y %H:%M')
        })
        
        # Render HTML template
        html_content = render_template(template_name, **data)
        
        # Konfigurasi PDF
        config = pdfkit.configuration(wkhtmltopdf='/usr/bin/wkhtmltopdf')
        
        # Generate filename
        pdf_filename = f"{filename_prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        pdf_path = os.path.join('static', 'pdf', pdf_filename)
        
        # Buat folder jika belum ada
        os.makedirs(os.path.dirname(pdf_path), exist_ok=True)
        
        # Convert HTML ke PDF
        pdfkit.from_string(html_content, pdf_path, configuration=config)
        
        return pdf_path, pdf_filename
        
    except Exception as e:
        raise Exception(f"Error generating PDF: {str(e)}")

@main_bp.route('/export-rab-pdf/<int:rab_id>')
@login_required
def export_rab_pdf(rab_id):
    """Export RAB ke PDF"""
    try:
        # Ambil data RAB dari database
        rab = RAB.query.get_or_404(rab_id)
        items = ItemRAB.query.filter_by(rab_id=rab_id).all()
        
        # Data untuk PDF
        pdf_data = {
            'rab': rab,
            'items': items,
            'total_budget': rab.total_anggaran,
            'project_name': rab.nama_proyek,
            'client_name': rab.nama_klien,
            'project_location': rab.lokasi_proyek,
            'project_description': rab.deskripsi,
            'rab_code': rab.kode_rab,
            'created_date': rab.tanggal.strftime('%d %B %Y'),
            'status': rab.status
        }
        
        pdf_path, pdf_filename = generate_pdf_report(
            template_name='pdf/rab_pdf.html',
            data=pdf_data,
            filename_prefix=f"rab_{rab.kode_rab}"
        )
        
        return send_file(pdf_path, as_attachment=True, download_name=pdf_filename)
        
    except Exception as e:
        flash(f'Error generating PDF: {str(e)}', 'error')
        return redirect(url_for('main.rab'))

@main_bp.route('/kirim-rab-whatsapp/<int:rab_id>')
@login_required
def kirim_rab_whatsapp(rab_id):
    """Kirim notifikasi RAB via WhatsApp"""
    try:
        rab = RAB.query.get_or_404(rab_id)
        
        # Message untuk WhatsApp
        whatsapp_message = f"""
📋 *RENCANA ANGGARAN BIAYA (RAB)*
*PT. Daniar Furniture Art*

📌 *Proyek:* {rab.nama_proyek}
👤 *Klien:* {rab.nama_klien}
📍 *Lokasi:* {rab.lokasi_proyek or '-'}
💰 *Total Anggaran:* {rab.total_anggaran | currency}
📅 *Tanggal:* {rab.tanggal.strftime('%d %B %Y')}
📊 *Status:* {rab.status}
🔢 *Kode RAB:* {rab.kode_rab}

📥 *Download PDF:* {url_for('main.export_rab_pdf', rab_id=rab_id, _external=True)}

_Generated by Daniar Furniture Art System_
"""
        
        # Untuk sementara, tampilkan message yang bisa di-copy
        flash(f'📱 WhatsApp Message Ready - Copy dan kirim manual: {whatsapp_message}', 'info')
        
        return redirect(url_for('main.detail_rab', id=rab_id))
        
    except Exception as e:
        flash(f'Error preparing WhatsApp: {str(e)}', 'error')
        return redirect(url_for('main.rab'))
    

@main_bp.route('/print_rab/<int:rab_id>')
@login_required
def print_rab(rab_id):
    """Halaman khusus untuk print RAB"""
    try:
        rab = RAB.query.get_or_404(rab_id)
        items = ItemRAB.query.filter_by(rab_id=rab_id).all()
        
        return render_template('print_rab.html', rab=rab, items=items)
    except Exception as e:
        flash(f'Error loading print view: {str(e)}', 'error')
        return redirect(url_for('main.rab'))

# ===== ROUTE SLIP GAJI YANG DIPERBAIKI =====

@main_bp.route('/slip_gaji/print/<int:id>')
@login_required
def print_slip_gaji(id):
    """Route untuk print slip gaji individual"""
    slip = SlipGaji.query.get_or_404(id)
    return render_template('print_slip_gaji.html', slip=slip)

@main_bp.route('/slip_gaji')
@login_required
def slip_gaji():
    """Menampilkan halaman slip gaji"""
    try:
        # Ambil data karyawan
        karyawan_list = Karyawan.query.order_by(Karyawan.nama).all()
        
        # Ambil data slip gaji
        slip_list = SlipGaji.query.join(Karyawan).order_by(SlipGaji.tanggal_dibuat.desc()).all()
        
        # Hitung statistik
        total_pengeluaran_gaji = sum(s.total_gaji for s in slip_list) if slip_list else 0
        total_gaji_pokok = sum(s.gaji_pokok for s in slip_list) if slip_list else 0
        total_tunjangan = sum(s.tunjangan for s in slip_list) if slip_list else 0
        total_bonus = sum(s.bonus for s in slip_list) if slip_list else 0
        total_potongan = sum(s.potongan for s in slip_list) if slip_list else 0
        
        # Hitung rata-rata gaji
        jumlah_slip = len(slip_list)
        rata_rata_gaji = total_pengeluaran_gaji / jumlah_slip if jumlah_slip > 0 else 0
        
        # Ambil periode terbaru
        periode_terbaru = slip_list[0].periode if slip_list else None
        
        return render_template('slip_gaji.html',
            karyawan=karyawan_list,
            slip_gaji=slip_list,
            total_pengeluaran_gaji=total_pengeluaran_gaji,
            total_gaji_pokok=total_gaji_pokok,
            total_tunjangan=total_tunjangan,
            total_bonus=total_bonus,
            total_potongan=total_potongan,
            rata_rata_gaji=rata_rata_gaji,
            periode_terbaru=periode_terbaru,
            current_year=datetime.now().year
        )
        
    except Exception as e:
        flash(f'Error mengambil data slip gaji: {str(e)}', 'error')
        return render_template('slip_gaji.html', 
            karyawan=[], 
            slip_gaji=[],
            total_pengeluaran_gaji=0,
            total_gaji_pokok=0,
            total_tunjangan=0,
            total_bonus=0,
            total_potongan=0,
            rata_rata_gaji=0,
            periode_terbaru=None,
            current_year=datetime.now().year
        )

@main_bp.route('/buat_slip_gaji', methods=['POST'])
@login_required
def buat_slip_gaji():
    """Membuat slip gaji baru"""
    try:
        # Ambil data dari form
        karyawan_id = request.form.get('karyawan_id')
        periode_bulan = request.form.get('periode_bulan')
        periode_tahun = request.form.get('periode_tahun')
        gaji_pokok = float(request.form.get('gaji_pokok', 0))
        tunjangan = float(request.form.get('tunjangan', 0))
        bonus = float(request.form.get('bonus', 0))
        potongan = float(request.form.get('potongan', 0))
        keterangan_tunjangan = request.form.get('keterangan_tunjangan', '')
        keterangan_potongan = request.form.get('keterangan_potongan', '')
        
        # Validasi
        if not karyawan_id or not periode_bulan or not periode_tahun:
            flash('Data karyawan dan periode harus diisi!', 'error')
            return redirect(url_for('main.slip_gaji'))
        
        # Format periode (YYYY-MM)
        periode = f"{periode_tahun}-{periode_bulan:0>2}"
        
        # Cek apakah slip gaji untuk periode ini sudah ada
        existing_slip = SlipGaji.query.filter_by(
            karyawan_id=karyawan_id, 
            periode=periode
        ).first()
        
        if existing_slip:
            flash(f'Slip gaji untuk periode {periode} sudah ada!', 'error')
            return redirect(url_for('main.slip_gaji'))
        
        # Hitung total gaji
        total_gaji = gaji_pokok + tunjangan + bonus - potongan
        
        # Buat slip gaji baru
        slip_baru = SlipGaji(
            karyawan_id=karyawan_id,
            periode=periode,
            gaji_pokok=gaji_pokok,
            tunjangan=tunjangan,
            bonus=bonus,
            potongan=potongan,
            total_gaji=total_gaji,
            keterangan_tunjangan=keterangan_tunjangan,
            keterangan_potongan=keterangan_potongan,
            status='DRAFT',
            tanggal_dibuat=datetime.utcnow()
        )
        
        db.session.add(slip_baru)
        db.session.commit()
        
        flash('Slip gaji berhasil dibuat!', 'success')
        return redirect(url_for('main.slip_gaji'))
        
    except Exception as e:
        db.session.rollback()
        flash('Error membuat slip gaji: ' + str(e), 'error')
        return redirect(url_for('main.slip_gaji'))

@main_bp.route('/slip_gaji/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_slip_gaji(id):
    """Edit slip gaji"""
    slip = SlipGaji.query.get_or_404(id)
    
    if request.method == 'POST':
        try:
            slip.gaji_pokok = float(request.form.get('gaji_pokok', 0))
            slip.tunjangan = float(request.form.get('tunjangan', 0))
            slip.bonus = float(request.form.get('bonus', 0))
            slip.potongan = float(request.form.get('potongan', 0))
            slip.keterangan_tunjangan = request.form.get('keterangan_tunjangan', '')
            slip.keterangan_potongan = request.form.get('keterangan_potongan', '')
            slip.status = request.form.get('status', 'DRAFT')
            
            # Hitung ulang total gaji
            slip.total_gaji = slip.gaji_pokok + slip.tunjangan + slip.bonus - slip.potongan
            
            # Jika status diubah menjadi PAID, set tanggal_dibayar
            if slip.status == 'PAID' and not slip.tanggal_dibayar:
                slip.tanggal_dibayar = datetime.utcnow()
            
            db.session.commit()
            flash('Slip gaji berhasil diupdate!', 'success')
            return redirect(url_for('main.slip_gaji'))
            
        except Exception as e:
            db.session.rollback()
            flash('Error mengupdate slip gaji: ' + str(e), 'error')
    
    # Untuk GET request, tampilkan form edit
    return render_template('edit_slip_gaji.html', slip=slip)

@main_bp.route('/slip_gaji/hapus/<int:id>', methods=['POST'])
@login_required
def hapus_slip_gaji(id):
    """Hapus slip gaji"""
    slip = SlipGaji.query.get_or_404(id)
    try:
        db.session.delete(slip)
        db.session.commit()
        flash('Slip gaji berhasil dihapus!', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Error menghapus slip gaji!', 'error')
    
    return redirect(url_for('main.slip_gaji'))

@main_bp.route('/slip_gaji/cetak_semua')
@login_required
def print_semua_slip_gaji():
    """Cetak semua slip gaji sekaligus"""
    try:
        # Ambil semua slip gaji
        slip_gaji = SlipGaji.query.join(Karyawan).order_by(SlipGaji.periode.desc(), Karyawan.nama).all()
        
        # Hitung statistik dengan nilai default
        total_slip = len(slip_gaji)
        total_pengeluaran = sum(slip.total_gaji for slip in slip_gaji) if slip_gaji else 0
        
        # Tentukan periode cetak
        periode_cetak = datetime.now().strftime('%B %Y')
        
        return render_template('cetak_semua_slip_gaji.html',
                             slip_gaji=slip_gaji,
                             total_slip=total_slip,
                             total_pengeluaran=total_pengeluaran,
                             periode_cetak=periode_cetak)
                             
    except Exception as e:
        flash('Error saat mencetak slip gaji: ' + str(e), 'error')
        return redirect(url_for('main.slip_gaji'))


# ===== ROUTE KARYAWAN =====

@main_bp.route('/karyawan')
@login_required
def karyawan():
    """Menampilkan halaman data karyawan"""
    try:
        karyawan_list = Karyawan.query.order_by(Karyawan.nama).all()
        return render_template('karyawan.html', karyawan=karyawan_list)
    except Exception as e:
        flash('Error mengambil data karyawan: ' + str(e), 'error')
        return render_template('karyawan.html', karyawan=[])

@main_bp.route('/tambah_karyawan', methods=['GET', 'POST'])
@login_required
def tambah_karyawan():
    """Menangani form tambah karyawan dan proses submit"""
    if request.method == 'GET':
        # Menampilkan form tambah karyawan
        return render_template('tambah_karyawan.html')
    
    # POST method - proses tambah karyawan
    try:
        # Data dasar
        nama = request.form.get('nama', '').strip()
        nik = request.form.get('nik', '').strip() or None
        jabatan = request.form.get('jabatan', '').strip()
        divisi = request.form.get('divisi', '').strip() or None
        status = request.form.get('status', 'TETAP').strip()
        
        # Handle gaji_pokok
        gaji_pokok_str = request.form.get('gaji_pokok', '0').replace('.', '').replace(',', '.').strip()
        try:
            gaji_pokok = float(gaji_pokok_str) if gaji_pokok_str else 0.0
        except ValueError:
            flash('Format gaji pokok tidak valid!', 'error')
            return render_template('tambah_karyawan.html')
        
        # Informasi pribadi
        tempat_lahir = request.form.get('tempat_lahir', '').strip() or None
        tanggal_lahir_str = request.form.get('tanggal_lahir')
        tanggal_masuk_str = request.form.get('tanggal_masuk')
        
        # Validasi field wajib sesuai model
        if not nama or not jabatan or gaji_pokok <= 0 or not tanggal_masuk_str:
            flash('Nama, Jabatan, Gaji Pokok, dan Tanggal Masuk harus diisi!', 'error')
            return render_template('tambah_karyawan.html')
        
        # Cek NIK duplikat (jika diisi)
        if nik and Karyawan.query.filter_by(nik=nik).first():
            flash('NIK sudah terdaftar! Gunakan NIK yang berbeda.', 'error')
            return render_template('tambah_karyawan.html')
        
        # Parse tanggal
        try:
            tanggal_masuk = datetime.strptime(tanggal_masuk_str, '%Y-%m-%d').date()
            tanggal_lahir = datetime.strptime(tanggal_lahir_str, '%Y-%m-%d').date() if tanggal_lahir_str else None
        except ValueError as e:
            flash('Format tanggal tidak valid!', 'error')
            return render_template('tambah_karyawan.html')
        
        # Informasi lainnya
        alamat = request.form.get('alamat', '') or None
        no_telepon = request.form.get('no_telepon', '') or None
        email = request.form.get('email', '') or None
        pendidikan_terakhir = request.form.get('pendidikan_terakhir', '') or None
        status_perkawinan = request.form.get('status_perkawinan', '') or None
        keterangan = request.form.get('keterangan', '') or None
        
        # Informasi bank & pajak
        bank = request.form.get('bank', '') or None
        no_rekening = request.form.get('no_rekening', '') or None
        npwp = request.form.get('npwp', '') or None
        
        # Handle foto profil
        foto_profil = None
        foto_file = request.files.get('foto_profil')
        if foto_file and foto_file.filename:
            # Generate unique filename
            import os
            from werkzeug.utils import secure_filename
            
            filename = secure_filename(foto_file.filename)
            file_ext = os.path.splitext(filename)[1]
            unique_filename = f"profile_{int(datetime.utcnow().timestamp())}{file_ext}"
            
            # Save file
            upload_path = os.path.join(current_app.root_path, 'static', 'uploads', 'profiles')
            os.makedirs(upload_path, exist_ok=True)
            foto_file.save(os.path.join(upload_path, unique_filename))
            foto_profil = unique_filename
        
        # Buat karyawan baru
        karyawan_baru = Karyawan(
            nama=nama,
            nik=nik,
            jabatan=jabatan,
            divisi=divisi,
            status=status,
            gaji_pokok=gaji_pokok,
            tempat_lahir=tempat_lahir,
            tanggal_lahir=tanggal_lahir,
            tanggal_masuk=tanggal_masuk,
            alamat=alamat,
            no_telepon=no_telepon,
            email=email,
            pendidikan_terakhir=pendidikan_terakhir,
            status_perkawinan=status_perkawinan,
            keterangan=keterangan,
            bank=bank,
            no_rekening=no_rekening,
            npwp=npwp,
            foto_profil=foto_profil
        )
        
        db.session.add(karyawan_baru)
        db.session.commit()
        
        flash(f'Karyawan {nama} berhasil ditambahkan!', 'success')
        return redirect(url_for('main.karyawan'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error menambah karyawan: {str(e)}', 'error')
        return render_template('tambah_karyawan.html')

@main_bp.route('/edit_karyawan/<int:id>', methods=['GET', 'POST'])
def edit_karyawan(id):
    karyawan = Karyawan.query.get_or_404(id)
    
    if request.method == 'POST':
        try:
            # Validasi NIK (gunakan re)
            nik = request.form.get('nik', '').strip()
            if nik and not re.match(r'^[0-9]+$', nik):
                flash('NIK harus berupa angka', 'error')
                return render_template('edit_karyawan.html', karyawan=karyawan)
            
            # Update data karyawan
            karyawan.nik = nik
            karyawan.nama = request.form.get('nama', '').strip()
            karyawan.jabatan = request.form.get('jabatan', '').strip()
            karyawan.divisi = request.form.get('divisi', '').strip()
            karyawan.status = request.form.get('status', '').strip()
            
            # Handle gaji_pokok
            gaji_pokok = request.form.get('gaji_pokok', '0')
            try:
                karyawan.gaji_pokok = float(gaji_pokok)
            except ValueError:
                flash('Format gaji pokok tidak valid', 'error')
                return render_template('edit_karyawan.html', karyawan=karyawan)
            
            # Data pribadi
            karyawan.tempat_lahir = request.form.get('tempat_lahir', '').strip()
            
            tanggal_lahir = request.form.get('tanggal_lahir')
            karyawan.tanggal_lahir = datetime.strptime(tanggal_lahir, '%Y-%m-%d').date() if tanggal_lahir else None
            
            karyawan.alamat = request.form.get('alamat', '').strip()
            karyawan.no_telepon = request.form.get('no_telepon', '').strip()
            karyawan.email = request.form.get('email', '').strip()
            
            # Informasi bank & pajak
            karyawan.bank = request.form.get('bank', '').strip()
            karyawan.no_rekening = request.form.get('no_rekening', '').strip()
            karyawan.npwp = request.form.get('npwp', '').strip()
            
            # Informasi lainnya
            karyawan.pendidikan_terakhir = request.form.get('pendidikan_terakhir', '').strip()
            karyawan.status_perkawinan = request.form.get('status_perkawinan', '').strip()
            
            tanggal_masuk = request.form.get('tanggal_masuk')
            if tanggal_masuk:
                karyawan.tanggal_masuk = datetime.strptime(tanggal_masuk, '%Y-%m-%d').date()
            
            karyawan.keterangan = request.form.get('keterangan', '').strip()
            
            # Handle foto profil
            remove_photo = request.form.get('remove_photo') == 'true'
            
            if remove_photo and karyawan.foto_profil:
                # Hapus file foto lama
                import os
                foto_path = os.path.join(current_app.root_path, 'static', 'uploads', 'profiles', karyawan.foto_profil)
                if os.path.exists(foto_path):
                    os.remove(foto_path)
                karyawan.foto_profil = None
            
            foto_file = request.files.get('foto_profil')
            if foto_file and foto_file.filename:
                # Hapus foto lama jika ada
                if karyawan.foto_profil:
                    old_foto_path = os.path.join(current_app.root_path, 'static', 'uploads', 'profiles', karyawan.foto_profil)
                    if os.path.exists(old_foto_path):
                        os.remove(old_foto_path)
                
                # Simpan foto baru
                filename = secure_filename(foto_file.filename)
                unique_filename = f"{karyawan.id}_{int(datetime.now().timestamp())}_{filename}"
                save_path = os.path.join(current_app.root_path, 'static', 'uploads', 'profiles', unique_filename)
                
                foto_file.save(save_path)
                karyawan.foto_profil = unique_filename
            
            db.session.commit()
            flash('Data karyawan berhasil diupdate!', 'success')
            return redirect(url_for('main.karyawan'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error mengupdate karyawan: {str(e)}', 'error')
            return render_template('edit_karyawan.html', karyawan=karyawan)
    
    return render_template('edit_karyawan.html', karyawan=karyawan)


@main_bp.route('/update_karyawan/<int:id>', methods=['POST'])
@login_required
def update_karyawan(id):
    """Update data karyawan dengan upload foto yang diperbaiki"""
    try:
        # Cari karyawan berdasarkan ID
        karyawan = Karyawan.query.get_or_404(id)
        
        # Update data dasar
        karyawan.nik = request.form.get('nik')
        karyawan.nama = request.form.get('nama')
        karyawan.jabatan = request.form.get('jabatan')
        karyawan.divisi = request.form.get('divisi')
        karyawan.status = request.form.get('status')
        karyawan.gaji_pokok = float(request.form.get('gaji_pokok', 0))
        karyawan.tunjangan = float(request.form.get('tunjangan', 0))
        karyawan.alamat = request.form.get('alamat')
        karyawan.telepon = request.form.get('telepon')
        karyawan.email = request.form.get('email')
        
        # Handle tanggal masuk
        tanggal_masuk = request.form.get('tanggal_masuk')
        if tanggal_masuk:
            karyawan.tanggal_masuk = datetime.strptime(tanggal_masuk, '%Y-%m-%d').date()
        
        # === PERBAIKAN BAGIAN UPLOAD FOTO ===
        if 'foto' in request.files:
            file = request.files['foto']
            
            # Cek jika file benar-benar diupload (bukan empty)
            if file and file.filename and file.filename != '':
                print(f"Processing file upload: {file.filename}")
                
                # Validasi file type
                allowed_types = ['image/jpeg', 'image/png', 'image/jpg']
                if file.content_type not in allowed_types:
                    flash('Format file tidak didukung. Gunakan JPEG, JPG, atau PNG.', 'danger')
                    return redirect(url_for('main.edit_karyawan', id=id))
                
                # Validasi file size (max 2MB)
                file.seek(0, 2)  # Go to end
                file_size = file.tell()
                file.seek(0)     # Reset to beginning
                
                if file_size > 2 * 1024 * 1024:
                    flash('Ukuran file terlalu besar. Maksimal 2MB.', 'danger')
                    return redirect(url_for('main.edit_karyawan', id=id))
                
                # Generate unique filename
                from werkzeug.utils import secure_filename
                filename = secure_filename(file.filename)
                unique_filename = f"{uuid.uuid4().hex}_{filename}"
                
                # Tentukan upload folder - PASTIKAN PATH BENAR
                upload_folder = os.path.join('static', 'uploads', 'karyawan')
                
                # Buat folder jika belum ada
                if not os.path.exists(upload_folder):
                    os.makedirs(upload_folder, exist_ok=True)
                    print(f"Created upload folder: {upload_folder}")
                
                # Full path untuk menyimpan file
                file_path = os.path.join(upload_folder, unique_filename)
                print(f"Saving file to: {file_path}")
                
                # Save file
                file.save(file_path)
                
                # Hapus foto lama jika ada
                if karyawan.foto and os.path.exists(karyawan.foto):
                    try:
                        os.remove(karyawan.foto)
                        print(f"Deleted old photo: {karyawan.foto}")
                    except Exception as e:
                        print(f"Warning: Could not delete old photo: {e}")
                
                # Simpan path relatif ke database
                karyawan.foto = file_path  # atau f"uploads/karyawan/{unique_filename}"
                print(f"Saved new photo path: {karyawan.foto}")
        
        # Commit ke database
        db.session.commit()
        
        flash('Data karyawan berhasil diupdate!', 'success')
        return redirect(url_for('main.detail_karyawan', id=id))
        
    except Exception as e:
        db.session.rollback()
        print(f"Error updating karyawan: {str(e)}")
        flash(f'Error mengupdate karyawan: {str(e)}', 'danger')
        return redirect(url_for('main.edit_karyawan', id=id))
    
@main_bp.route('/detail_karyawan/<int:id>')
@login_required
def detail_karyawan(id):
    """Menampilkan detail karyawan"""
    try:
        from datetime import date
        
        karyawan = Karyawan.query.get_or_404(id)
        
        # Hitung lama kerja
        today = date.today()
        lama_kerja = today - karyawan.tanggal_masuk
        tahun = lama_kerja.days // 365
        bulan = (lama_kerja.days % 365) // 30
        lama_kerja_str = f"{tahun} tahun {bulan} bulan"
        
        return render_template('detail_karyawan.html', 
                             karyawan=karyawan, 
                             lama_kerja=lama_kerja_str)
    except Exception as e:
        flash('Error mengambil detail karyawan: ' + str(e), 'error')
        return redirect(url_for('main.karyawan'))

@main_bp.route('/hapus_karyawan/<int:id>', methods=['POST'])
@login_required
def hapus_karyawan(id):
    """Menghapus karyawan"""
    try:
        karyawan = Karyawan.query.get_or_404(id)
        
        # Cek apakah karyawan memiliki slip gaji
        slip_count = SlipGaji.query.filter_by(karyawan_id=id).count()
        if slip_count > 0:
            flash('Tidak dapat menghapus karyawan yang memiliki slip gaji!', 'error')
            return redirect(url_for('main.karyawan'))
        
        db.session.delete(karyawan)
        db.session.commit()
        flash('Karyawan berhasil dihapus!', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash('Error menghapus karyawan: ' + str(e), 'error')
    
    return redirect(url_for('main.karyawan'))

@main_bp.route('/slip_gaji_karyawan/<int:id>')
@login_required
def slip_gaji_karyawan(id):
    """Menampilkan slip gaji karyawan"""
    try:
        karyawan = Karyawan.query.get_or_404(id)
        return render_template('slip_gaji.html', karyawan=karyawan)
    except Exception as e:
        flash('Error mengambil slip gaji: ' + str(e), 'error')
        return redirect(url_for('main.karyawan'))

@main_bp.route('/cetak_semua_slip_gaji')
@login_required
def cetak_semua_slip_gaji():
    """Cetak semua slip gaji"""
    try:
        karyawan_list = Karyawan.query.all()
        if not karyawan_list:
            flash('Tidak ada data karyawan untuk dicetak', 'warning')
            return redirect(url_for('main.karyawan'))
        
        # Logic untuk mencetak semua slip gaji
        # Ini bisa berupa generate PDF atau redirect ke halaman print
        flash(f'Slip gaji untuk {len(karyawan_list)} karyawan siap dicetak', 'success')
        return redirect(url_for('main.karyawan'))
        
    except Exception as e:
        flash('Error mencetak slip gaji: ' + str(e), 'error')
        return redirect(url_for('main.karyawan'))

@main_bp.route('/laporan_karyawan')
@login_required
def laporan_karyawan():
    """Halaman laporan karyawan"""
    try:
        from datetime import date
        
        # Statistik dasar
        total_karyawan = Karyawan.query.count()
        karyawan_tetap = Karyawan.query.filter_by(status='TETAP').count()
        karyawan_kontrak = Karyawan.query.filter_by(status='KONTRAK').count()
        karyawan_percobaan = Karyawan.query.filter_by(status='PERCOBAAN').count()
        karyawan_harian = Karyawan.query.filter_by(status='HARIAN').count()
        total_gaji = db.session.query(db.func.sum(Karyawan.gaji_pokok)).scalar() or 0
        
        # Data untuk chart
        jabatan_stats = db.session.query(
            Karyawan.jabatan, 
            db.func.count(Karyawan.id)
        ).group_by(Karyawan.jabatan).all()
        
        status_stats = db.session.query(
            Karyawan.status, 
            db.func.count(Karyawan.id)
        ).group_by(Karyawan.status).all()
        
        # Data tambahan untuk insights
        all_karyawan = Karyawan.query.all()
        
        # Karyawan dengan gaji tertinggi
        max_gaji_karyawan = Karyawan.query.order_by(Karyawan.gaji_pokok.desc()).first()
        
        # Karyawan dengan gaji terendah
        min_gaji_karyawan = Karyawan.query.order_by(Karyawan.gaji_pokok.asc()).first()
        
        # Karyawan terlama
        oldest_karyawan = Karyawan.query.order_by(Karyawan.tanggal_masuk.asc()).first()
        
        # Hitung lama kerja karyawan terlama
        if oldest_karyawan and oldest_karyawan.tanggal_masuk:
            today = date.today()
            lama_kerja = today - oldest_karyawan.tanggal_masuk
            tahun = lama_kerja.days // 365
            bulan = (lama_kerja.days % 365) // 30
            oldest_kerja = f"{tahun} tahun {bulan} bulan"
        else:
            oldest_kerja = "-"
        
        return render_template("laporan_karyawan.html",
                             total_karyawan=total_karyawan,
                             karyawan_tetap=karyawan_tetap,
                             karyawan_kontrak=karyawan_kontrak,
                             karyawan_percobaan=karyawan_percobaan,
                             karyawan_harian=karyawan_harian,
                             total_gaji=total_gaji,
                             jabatan_stats=jabatan_stats,
                             status_stats=status_stats,
                             all_karyawan=all_karyawan,
                             max_gaji_karyawan=max_gaji_karyawan,
                             min_gaji_karyawan=min_gaji_karyawan,
                             oldest_karyawan=oldest_karyawan,
                             oldest_kerja=oldest_kerja,
                             current_date=date.today())
                             
    except Exception as e:
        flash(f'Error loading laporan: {str(e)}', 'error')
        return redirect(url_for("main.karyawan"))

@main_bp.route('/export_karyawan_excel')
@login_required
def export_karyawan_excel():
    """Export data karyawan ke Excel"""
    try:
        from io import BytesIO
        from datetime import date
        import pandas as pd
        from flask import send_file
        
        # Ambil data karyawan
        karyawan_list = Karyawan.query.all()
        
        if not karyawan_list:
            flash('Tidak ada data karyawan untuk diexport', 'warning')
            return redirect(url_for('main.karyawan'))
        
        # Siapkan data untuk Excel
        data = []
        for karyawan in karyawan_list:
            # Hitung lama kerja
            if karyawan.tanggal_masuk:
                today = date.today()
                lama_kerja = today - karyawan.tanggal_masuk
                tahun = lama_kerja.days // 365
                bulan = (lama_kerja.days % 365) // 30
                lama_kerja_str = f"{tahun} tahun {bulan} bulan"
            else:
                lama_kerja_str = "-"
            
            data.append({
                'NIK': karyawan.nik or '-',
                'Nama': karyawan.nama,
                'Jabatan': karyawan.jabatan,
                'Divisi': karyawan.divisi or '-',
                'Status': karyawan.status,
                'Gaji Pokok': karyawan.gaji_pokok,
                'Tanggal Masuk': karyawan.tanggal_masuk.strftime('%d/%m/%Y') if karyawan.tanggal_masuk else '-',
                'Lama Kerja': lama_kerja_str,
                'Tempat Lahir': karyawan.tempat_lahir or '-',
                'Tanggal Lahir': karyawan.tanggal_lahir.strftime('%d/%m/%Y') if karyawan.tanggal_lahir else '-',
                'No. Telepon': karyawan.no_telepon or '-',
                'Email': karyawan.email or '-',
                'Pendidikan Terakhir': karyawan.pendidikan_terakhir or '-',
                'Status Perkawinan': karyawan.status_perkawinan or '-',
                'Alamat': karyawan.alamat or '-'
            })
        
        # Buat DataFrame
        df = pd.DataFrame(data)
        
        # Buat file Excel di memory
        output = BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, sheet_name='Data Karyawan', index=False)
            
            # Formatting
            workbook = writer.book
            worksheet = writer.sheets['Data Karyawan']
            
            # Format currency untuk kolom gaji
            money_format = workbook.add_format({'num_format': 'Rp #,##0'})
            worksheet.set_column('F:F', 15, money_format)
            
            # Auto-adjust column widths
            for i, col in enumerate(df.columns):
                column_len = max(df[col].astype(str).str.len().max(), len(col)) + 2
                worksheet.set_column(i, i, column_len)
        
        output.seek(0)
        
        # Kirim file
        filename = f"Data_Karyawan_{date.today().strftime('%Y%m%d')}.xlsx"
        return send_file(
            output,
            download_name=filename,
            as_attachment=True,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        
    except Exception as e:
        flash(f'Error exporting Excel: {str(e)}', 'error')
        return redirect(url_for('main.karyawan'))

# ============================
# FILTER LAPORAN KARYAWAN
# ============================
@main_bp.route("/laporan_karyawan/filter", methods=["POST"])
@login_required
def filter_laporan_karyawan():
    """Filter laporan karyawan berdasarkan kriteria"""
    try:
        from datetime import date
        
        # Ambil parameter filter dari form
        divisi_filter = request.form.get('divisi')
        status_filter = request.form.get('status')
        jabatan_filter = request.form.get('jabatan')
        
        # Query dasar
        query = Karyawan.query
        
        # Apply filters
        if divisi_filter and divisi_filter != 'ALL':
            query = query.filter(Karyawan.divisi == divisi_filter)
        
        if status_filter and status_filter != 'ALL':
            query = query.filter(Karyawan.status == status_filter)
            
        if jabatan_filter and jabatan_filter != 'ALL':
            query = query.filter(Karyawan.jabatan == jabatan_filter)
        
        # Eksekusi query
        filtered_karyawan = query.all()
        
        # Hitung statistik untuk data yang difilter
        total_karyawan = len(filtered_karyawan)
        total_gaji = sum(k.gaji_pokok for k in filtered_karyawan)
        
        # Data untuk chart (dari data yang difilter)
        jabatan_stats = {}
        status_stats = {}
        
        for karyawan in filtered_karyawan:
            # Hitung distribusi jabatan
            jabatan = karyawan.jabatan or 'Tidak Diketahui'
            jabatan_stats[jabatan] = jabatan_stats.get(jabatan, 0) + 1
            
            # Hitung distribusi status
            status = karyawan.status or 'Tidak Diketahui'
            status_stats[status] = status_stats.get(status, 0) + 1
        
        # Konversi ke format yang diharapkan template
        jabatan_stats_list = [(k, v) for k, v in jabatan_stats.items()]
        status_stats_list = [(k, v) for k, v in status_stats.items()]
        
        return render_template("laporan_karyawan.html",
                             total_karyawan=total_karyawan,
                             karyawan_tetap=status_stats.get('TETAP', 0),
                             karyawan_kontrak=status_stats.get('KONTRAK', 0),
                             karyawan_percobaan=status_stats.get('PERCOBAAN', 0),
                             karyawan_harian=status_stats.get('HARIAN', 0),
                             total_gaji=total_gaji,
                             jabatan_stats=jabatan_stats_list,
                             status_stats=status_stats_list,
                             all_karyawan=filtered_karyawan,
                             current_date=date.today(),
                             divisi_filter=divisi_filter,
                             status_filter=status_filter,
                             jabatan_filter=jabatan_filter)
                             
    except Exception as e:
        flash(f'Error filtering laporan: {str(e)}', 'error')
        return redirect(url_for("main.laporan_karyawan"))

# ============================
# UPDATE FOTO PROFIL
# ============================
@main_bp.route('/update_foto_profil/<int:id>', methods=['POST'])
@login_required
def update_foto_profil(id):
    """Update foto profil karyawan"""
    try:
        karyawan = Karyawan.query.get_or_404(id)
        
        if 'foto_profil' in request.files:
            file = request.files['foto_profil']
            if file and file.filename:
                # Validasi file
                if not allowed_file(file.filename):
                    flash('Format file tidak didukung. Gunakan JPG, PNG, atau JPEG.', 'error')
                    return redirect(url_for('main.detail_karyawan', id=id))
                
                # Generate unique filename
                filename = secure_filename(f"profile_{karyawan.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}")
                file_path = os.path.join(current_app.root_path, 'static', 'uploads', 'profiles', filename)
                
                # Create directory if not exists
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                
                # Save file
                file.save(file_path)
                
                # Delete old photo if exists
                if karyawan.foto_profil:
                    old_file_path = os.path.join(current_app.root_path, 'static', 'uploads', 'profiles', karyawan.foto_profil)
                    if os.path.exists(old_file_path):
                        os.remove(old_file_path)
                
                # Update database
                karyawan.foto_profil = filename
                db.session.commit()
                
                flash('Foto profil berhasil diupdate!', 'success')
        
        # Handle delete photo request
        elif request.form.get('hapus_foto'):
            if karyawan.foto_profil:
                file_path = os.path.join(current_app.root_path, 'static', 'uploads', 'profiles', karyawan.foto_profil)
                if os.path.exists(file_path):
                    os.remove(file_path)
                
                karyawan.foto_profil = None
                db.session.commit()
                flash('Foto profil berhasil dihapus!', 'success')
        
        return redirect(url_for('main.detail_karyawan', id=id))
        
    except Exception as e:
        db.session.rollback()
        flash('Error mengupdate foto profil: ' + str(e), 'error')
        return redirect(url_for('main.detail_karyawan', id=id))

def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in {'png', 'jpg', 'jpeg', 'gif'}


# ----------------------------
# Pengaturan
# ----------------------------
@main_bp.route("/pengaturan", methods=["GET", "POST"])
def pengaturan():
    if request.method == "POST":
        flash("Pengaturan berhasil diperbarui", "success")
        return redirect(url_for("main.pengaturan"))
    return render_template("pengaturan.html")






if __name__ == '__main__':
    app.run(debug=True)
