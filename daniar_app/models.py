from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from . import db

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Cashflow(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tanggal = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    nama_barang = db.Column(db.String(200), nullable=False)
    jenis = db.Column(db.String(100), nullable=False)
    jumlah = db.Column(db.String(50))
    satuan = db.Column(db.String(50))
    harga = db.Column(db.Float, nullable=False)
    keterangan = db.Column(db.String(200))
    catatan_tambahan = db.Column(db.String(300))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<Cashflow {self.nama_barang} - {self.harga}>"

class KasbonState(db.Model):
    """
    Model untuk menyimpan state total utang kasbon.
    Hanya akan ada satu baris data di tabel ini.
    """
    id = db.Column(db.Integer, primary_key=True)
    total_utang = db.Column(db.Float, nullable=False, default=0.0)

    def __repr__(self):
        return f"<KasbonState total_utang={self.total_utang}>"

class AsetTetap(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nama_aset = db.Column(db.String(100), nullable=False)
    manufaktur = db.Column(db.String(100), nullable=True)
    tanggal_perolehan = db.Column(db.Date, nullable=False)
    harga_perolehan = db.Column(db.Float, nullable=False)
    umur_ekonomis = db.Column(db.Integer, nullable=False)
    nilai_sisa = db.Column(db.Float, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<AsetTetap {self.nama_aset}>"
    
class Karyawan(db.Model):
    __tablename__ = 'karyawan'
    
    id = db.Column(db.Integer, primary_key=True)
    nik = db.Column(db.String(20), unique=True, nullable=True)
    nama = db.Column(db.String(100), nullable=False)
    jabatan = db.Column(db.String(100), nullable=False)
    divisi = db.Column(db.String(100), nullable=True)
    status = db.Column(db.String(20), default='TETAP')
    gaji_pokok = db.Column(db.Float, nullable=False, default=0.0)
    
    # Informasi Pribadi
    tempat_lahir = db.Column(db.String(100), nullable=True)
    tanggal_lahir = db.Column(db.Date, nullable=True)
    alamat = db.Column(db.Text, nullable=True)
    no_telepon = db.Column(db.String(20), nullable=True)
    email = db.Column(db.String(100), nullable=True)
    
    # Informasi Bank & Pajak
    bank = db.Column(db.String(50), nullable=True)
    no_rekening = db.Column(db.String(50), nullable=True)
    npwp = db.Column(db.String(25), nullable=True)
    
    # Informasi Lainnya
    pendidikan_terakhir = db.Column(db.String(50), nullable=True)
    status_perkawinan = db.Column(db.String(20), nullable=True)
    tanggal_masuk = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    keterangan = db.Column(db.Text, nullable=True)
    
    # Foto Profil - TAMBAHKAN INI
    foto_profil = db.Column(db.String(255), nullable=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<Karyawan {self.nik} - {self.nama}>'

class SlipGaji(db.Model):
    __tablename__ = 'slip_gaji'
    
    id = db.Column(db.Integer, primary_key=True)
    karyawan_id = db.Column(db.Integer, db.ForeignKey('karyawan.id'), nullable=False)
    periode = db.Column(db.String(7), nullable=False)  # Format: YYYY-MM
    gaji_pokok = db.Column(db.Float, nullable=False, default=0.0)
    tunjangan = db.Column(db.Float, default=0.0)
    bonus = db.Column(db.Float, default=0.0)
    potongan = db.Column(db.Float, default=0.0)
    total_gaji = db.Column(db.Float, nullable=False, default=0.0)
    keterangan_tunjangan = db.Column(db.Text)
    keterangan_potongan = db.Column(db.Text)
    status = db.Column(db.String(20), default='DRAFT')  # DRAFT, PAID, CANCELLED
    tanggal_dibuat = db.Column(db.DateTime, default=datetime.utcnow)
    tanggal_dibayar = db.Column(db.DateTime)
    
    # Relationship
    karyawan = db.relationship('Karyawan', backref=db.backref('slip_gaji', lazy=True))
    
    def __repr__(self):
        return f'<SlipGaji {self.periode} - {self.karyawan.nama}>'

class Faktur(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nomor_faktur = db.Column(db.String(50), nullable=False, unique=True)
    nama_pelanggan = db.Column(db.String(100), nullable=False)
    tanggal_faktur = db.Column(db.Date, nullable=False)
    alamat_pelanggan = db.Column(db.Text)  # Field baru
    keterangan = db.Column(db.Text)  # Field baru
    total_harga = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Faktur {self.nomor_faktur}>"

class ItemFaktur(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    faktur_id = db.Column(db.Integer, db.ForeignKey('faktur.id'), nullable=False)
    nama_barang = db.Column(db.String(200), nullable=False)
    jumlah = db.Column(db.Float, nullable=False)
    harga = db.Column(db.Float, nullable=False)
    subtotal = db.Column(db.Float, nullable=False)
    
    # Relationship
    faktur = db.relationship('Faktur', backref=db.backref('items', lazy=True))

    def __repr__(self):
        return f"<ItemFaktur {self.nama_barang}>"

class RAB(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    kode_rab = db.Column(db.String(50), unique=True, nullable=False)
    nama_proyek = db.Column(db.String(100), nullable=False)
    nama_klien = db.Column(db.String(100), nullable=False)
    lokasi_proyek = db.Column(db.String(200))
    deskripsi = db.Column(db.Text)
    tanggal = db.Column(db.Date, default=datetime.utcnow)
    status = db.Column(db.String(20), default='DRAFT')  # DRAFT, REVIEW, APPROVED, REJECTED
    total_anggaran = db.Column(db.Float, nullable=False, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<RAB {self.kode_rab} - {self.nama_proyek}>"

class ItemRAB(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    rab_id = db.Column(db.Integer, db.ForeignKey('rab.id'), nullable=False)
    kategori_item = db.Column(db.String(100), nullable=False)  # Bahan Baku, Tenaga Kerja, dll
    nama_item = db.Column(db.String(200), nullable=False)
    spesifikasi = db.Column(db.Text)
    quantity = db.Column(db.Float, nullable=False)
    satuan = db.Column(db.String(50), nullable=False)
    harga_satuan = db.Column(db.Float, nullable=False)
    total_harga = db.Column(db.Float, nullable=False)
    
    # Relationship
    rab = db.relationship('RAB', backref=db.backref('items', lazy=True, cascade='all, delete-orphan'))

    def __repr__(self):
        return f"<ItemRAB {self.nama_item}>"

    def calculate_total(self):
        self.total_harga = self.quantity * self.harga_satuan
        return self.total_harga