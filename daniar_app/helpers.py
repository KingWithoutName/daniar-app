# FILE: daniar_app/helpers.py

from functools import wraps
from flask import session, redirect, url_for, flash
from datetime import datetime

# --------------------------
# DECORATOR UNTUK AUTENTIKASI
# --------------------------
def login_required(f):
    """Decorator untuk memastikan user sudah login"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            flash('Anda harus login terlebih dahulu.', 'warning')
            return redirect(url_for('main.login'))
        return f(*args, **kwargs)
    return decorated_function


# --------------------------
# HELPER FUNCTIONS - FORMATTING
# --------------------------
def format_currency(value):
    """Format angka menjadi Rupiah, misal Rp 1.000.000"""
    if value is None:
        return "Rp 0"
    try:
        return f"Rp {float(value):,.0f}".replace(",", ".")
    except (ValueError, TypeError):
        return "Rp 0"


# --------------------------
# HELPER FUNCTIONS - KATEGORI CASHFLOW
# --------------------------
def kategori_besar(jenis):
    """Mengelompokkan jenis transaksi ke kategori besar"""
    
    # Daftar kategori pemasukan
    pemasukan = [
        'PENJUALAN TUNAI', 'PENERIMAAN PIUTANG', 'PINJAMAN / CASH INJECTION',
        'PENDAPATAN BUNGA', 'PENGEMBALIAN PAJAK', 'PENERIMAAN TUNAI LAINNYA',
        'FUNDING', 'BAYAR KASBON'
    ]
    
    # Daftar kategori HPP (Harga Pokok Penjualan)
    hpp = [
        'BIAYA PRODUK / LAYANAN LANGSUNG', 'PAJAK PENGGAJIAN - LANGSUNG',
        'GAJI - TKL', 'PERSEDIAAN', 'LAINNYA'
    ]
    
    # Daftar kategori operasional
    operasional = [
        'GAJI KARYAWAN', 'IKLAN', 'BIAYA BANK', 'PELATIHAN', 'ASURANSI',
        'INTERNET', 'LISENSI / IZIN', 'MAKANAN / HIBURAN', 'PERALATAN KANTOR',
        'PAJAK GAJI', 'ONGKOS KIRIM', 'PENCETAKAN', 'KONSULTAN', 'OKUPANSI',
        'BIAYA SEWA', 'SUBCONTRACTOR', 'TELEPON', 'TRANSPORTASI', 'PERJALANAN DINAS',
        'BIAYA LISTRIK', 'PENGEMBALIAN WEB', 'DOMAIN WEB DAN HOSTING', 'BIAYA AIR',
        'BIAYA SUBSCRIPTION', 'PAJAK PEMBELIAN', 'LAINNYA'
    ]
    
    # Daftar kategori pengeluaran lain-lain
    lain_lain = [
        'PENGELUARAN TUNAI UNTUK PEMILIK', 'KASBON', 'BEBAN BUNGA',
        'BEBAN PAJAK PENGHASILAN', 'BIAYA ADMIN', 'LAINNYA', 'KEWAJIBAN'
    ]
    
    # Kategorisasi
    if jenis in pemasukan:
        return 'PEMASUKAN'
    elif jenis in hpp:
        return 'HPP'
    elif jenis in operasional:
        return 'OPERASIONAL'
    elif jenis in lain_lain:
        return 'LAIN-LAIN'
    else:
        return 'PENGELUARAN'  # Mengubah 'LAINNYA' menjadi 'PENGELUARAN'


def filter_cashflow(data, month=None, year=None):
    """Filter data cashflow berdasarkan bulan dan tahun"""
    filtered_data = data
    
    if month:
        filtered_data = [d for d in filtered_data if d.tanggal.month == int(month)]
    
    if year:
        filtered_data = [d for d in filtered_data if d.tanggal.year == int(year)]
    
    return filtered_data


def kategorikan_cashflow(data):
    """Mengkategorikan data cashflow menjadi pemasukan dan pengeluaran"""
    pemasukan = []
    pengeluaran = []
    
    for transaksi in data:
        kategori = kategori_besar(transaksi.jenis)
        
        if kategori == 'PEMASUKAN':
            pemasukan.append(transaksi)
        else:  # HPP, OPERASIONAL, LAIN-LAIN, PENGELUARAN
            pengeluaran.append(transaksi)
    
    return pemasukan, pengeluaran


# --------------------------
# HELPER FUNCTIONS - PENYUSUTAN ASET TETAP
# --------------------------
def hitung_penyusutan(aset):
    """
    Hitung penyusutan tahunan dan nilai buku terakhir
    
    Args:
        aset: Object aset dengan atribut harga_perolehan, nilai_sisa, umur_ekonomis, tanggal_perolehan
    
    Returns:
        tuple: (penyusutan_tahunan, nilai_buku)
    """
    if not aset or not aset.harga_perolehan or not aset.umur_ekonomis:
        return 0, 0
    
    # Hitung penyusutan tahunan
    penyusutan_tahunan = (aset.harga_perolehan - aset.nilai_sisa) / aset.umur_ekonomis
    
    # Hitung tahun berjalan
    tahun_berjalan = min(
        aset.umur_ekonomis, 
        (datetime.utcnow().year - aset.tanggal_perolehan.year)
    )
    
    # Hitung nilai buku
    nilai_buku = aset.harga_perolehan - (penyusutan_tahunan * tahun_berjalan)
    
    return round(penyusutan_tahunan, 2), round(nilai_buku, 2)


def jadwal_penyusutan(aset):
    """
    Buat jadwal penyusutan per tahun untuk aset
    
    Args:
        aset: Object aset dengan atribut harga_perolehan, nilai_sisa, umur_ekonomis
    
    Returns:
        list: List dictionary berisi jadwal penyusutan per tahun
    """
    if not aset or not aset.harga_perolehan or not aset.umur_ekonomis:
        return []
    
    schedule = []
    akumulasi = 0
    penyusutan_tahunan = (aset.harga_perolehan - aset.nilai_sisa) / aset.umur_ekonomis
    
    for tahun in range(1, aset.umur_ekonomis + 1):
        akumulasi += penyusutan_tahunan
        nilai_buku_akhir = aset.harga_perolehan - akumulasi
        
        schedule.append({
            "tahun": tahun,
            "penyusutan": round(penyusutan_tahunan, 2),
            "akumulasi": round(akumulasi, 2),
            "nilai_buku": round(nilai_buku_akhir, 2)
        })
    
    return schedule