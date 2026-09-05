from datetime import datetime
import os
import pandas as pd
from flask import Flask, flash, redirect, render_template, request, session, url_for
from flask_sqlalchemy import SQLAlchemy

basedir = os.path.abspath(os.path.dirname(__file__))
app = Flask(__name__)
app.secret_key = "kunci_rahasia_sistem_absensi_sekolah"

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(
    basedir, "absensi.db"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

UPLOAD_FOLDER = os.path.join(basedir, "static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nis = db.Column(db.String(50), unique=True, nullable=False)
    nama = db.Column(db.String(100), nullable=False)
    kelas = db.Column(db.String(50), nullable=True)
    password = db.Column(db.String(100), nullable=False, default="123")
    role = db.Column(db.String(20), nullable=False, default="siswa")


class Absen(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nis = db.Column(db.String(50), nullable=False)
    nama = db.Column(db.String(100), nullable=True)
    kelas = db.Column(db.String(50), nullable=True)
    tanggal = db.Column(db.String(20), nullable=False)
    jam = db.Column(db.String(20), nullable=False)
    foto = db.Column(db.String(200), nullable=True)
    status = db.Column(db.String(50), nullable=False, default="Hadir")


with app.app_context():
    db.create_all()
    admin_default = User.query.filter_by(nis="admin").first()
    if not admin_default:
        db.session.add(
            User(
                nis="admin",
                nama="Administrator",
                kelas="-",
                password="adminpassword",
                role="admin",
            )
        )
        db.session.commit()


@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        nis_input = request.form.get("nis", "").strip()
        password_input = request.form.get("password", "").strip()
        user = User.query.filter_by(nis=nis_input).first()

        if user and user.password == password_input:
            session.clear()
            session["user"] = user.nis
            session["role"] = user.role
            session["nama"] = user.nama
            session["kelas"] = user.kelas

            if user.role == "admin":
                flash("Berhasil masuk menggunakan jalur darurat!", "success")
                return redirect(url_for("admin_dashboard"))
            else:
                return redirect(url_for("halaman_absen"))
        else:
            flash("NIS atau Password salah!", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/absen")
def halaman_absen():
    if "user" not in session or session.get("role") != "siswa":
        return redirect(url_for("login"))
    return render_template("absen.html")


@app.route("/proses_absen_gps", methods=["POST"])
def proses_absen_gps():
    if "user" not in session or session.get("role") != "siswa":
        return "Unauthorized", 403

    import base64
    import uuid
    from math import atan2, cos, radians, sin, sqrt

    data = request.get_json()
    if not data:
        return "Data tidak valid", 400

    lat = data.get("lat")
    lon = data.get("lon")
    image_data = data.get("image")

    if lat is None or lon is None:
        return "Koordinat GPS tidak ditemukan!", 400

    SEKOLAH_LAT = 1.7889520997064394
    SEKOLAH_LON = 101.31798279776869
    MAX_RADIUS_METER = 1000

    def hitung_jarak(lat1, lon1, lat2, lon2):
        R = 6371000
        phi1, phi2 = radians(lat1), radians(lat2)
        dphi = radians(lat2 - lat1)
        dlambda = radians(lon2 - lon1)
        a = (
            sin(dphi / 2) ** 2
            + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
        )
        c = 2 * atan2(sqrt(a), sqrt(1 - a))
        return R * c

    jarak = hitung_jarak(lat, lon, SEKOLAH_LAT, SEKOLAH_LON)
    if jarak > MAX_RADIUS_METER:
        return (
            f"Absen gagal! Anda berada di luar radius sekolah ({int(jarak)} meter).",
            400,
        )

    filename = None
    if image_data:
        try:
            header, encoded = image_data.split(",", 1)
            image_binary = base64.b64decode(encoded)
            filename = f"{session['user']}_{uuid.uuid4().hex[:8]}.jpg"
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            with open(filepath, "wb") as fh:
                fh.write(image_binary)
        except Exception as e:
            print("Gagal simpan foto:", e)

    now = datetime.now()
    tanggal_str = now.strftime("%Y-%m-%d")
    jam_str = now.strftime("%H:%M:%S")

    sudah_absen = Absen.query.filter_by(
        nis=session["user"], tanggal=tanggal_str
    ).first()
    if sudah_absen:
        return "Anda sudah melakukan absensi hari ini!", 400

    absen_baru = Absen(
        nis=session["user"],
        nama=session["nama"],
        kelas=session["kelas"],
        tanggal=tanggal_str,
        jam=jam_str,
        foto=filename,
        status="Hadir",
    )
    db.session.add(absen_baru)
    db.session.commit()

    return "Absensi berhasil direkam!"


@app.route("/admin", methods=["GET", "POST"])
def admin_dashboard():
    if "user" not in session or session.get("role") != "admin":
        return redirect(url_for("login"))

    keyword_siswa = request.args.get("qs", "").strip()
    keyword_absen = request.args.get("qa", "").strip()

    if request.method == "POST":
        form_source = request.form.get("form_source")
        action = request.form.get("action")

        if form_source == "siswa":
            if action == "hapus_pilih":
                ids = request.form.getlist("selected_ids")
                if ids:
                    User.query.filter(
                        User.id.in_(ids), User.role == "siswa"
                    ).delete(synchronize_session=False)
                    db.session.commit()
                    flash("Data siswa terpilih berhasil dihapus.", "success")

            elif action == "hapus_semua":
                User.query.filter_by(role="siswa").delete()
                db.session.commit()
                flash("Seluruh data siswa berhasil dikosongkan.", "success")

        elif form_source == "absen":
            if action == "hapus_pilih":
                ids = request.form.getlist("selected_ids")
                if ids:
                    Absen.query.filter(Absen.id.in_(ids)).delete(
                        synchronize_session=False
                    )
                    db.session.commit()
                    flash("Data absen terpilih berhasil dihapus.", "success")

            elif action == "hapus_semua":
                Absen.query.delete()
                db.session.commit()
                flash("Seluruh rekapitulasi absen dikosongkan.", "success")

        return redirect(url_for("admin_dashboard"))

    query_siswa = User.query.filter_by(role="siswa")
    if keyword_siswa:
        query_siswa = query_siswa.filter(
            db.or_(
                User.nama.ilike(f"%{keyword_siswa}%"),
                User.nis.ilike(f"%{keyword_siswa}%"),
                User.kelas.ilike(f"%{keyword_siswa}%"),
            )
        )

    query_absen = Absen.query
    if keyword_absen:
        query_absen = query_absen.filter(
            db.or_(
                Absen.nama.ilike(f"%{keyword_absen}%"),
                Absen.nis.ilike(f"%{keyword_absen}%"),
                Absen.kelas.ilike(f"%{keyword_absen}%"),
            )
        )

    return render_template(
        "admin_dashboard.html",
        siswa=query_siswa.all(),
        absen=query_absen.all(),
        keyword_siswa=keyword_siswa,
        keyword_absen=keyword_absen,
    )


@app.route("/admin/cetak_absen")
def cetak_absen():
    if "user" not in session or session.get("role") != "admin":
        return redirect(url_for("login"))
    return render_template("cetak_absen.html", absen=Absen.query.all())


# ==========================================
# MANAJEMEN SISWA & UPLOAD EXCEL
# ==========================================

@app.route("/admin/tambah_siswa", methods=["POST"])
def tambah_siswa():
    if "user" not in session or session.get("role") != "admin":
        return redirect(url_for("login"))
    nis = request.form.get("nis", "").strip()
    nama = request.form.get("nama", "").strip()
    kelas = request.form.get("kelas", "").strip()
    password = request.form.get("password", "123").strip()

    if User.query.filter_by(nis=nis).first():
        flash(f"NIS {nis} sudah terdaftar!", "danger")
    else:
        db.session.add(
            User(
                nis=nis,
                nama=nama,
                kelas=kelas,
                password=password if password else "123",
                role="siswa",
            )
        )
        db.session.commit()
        flash(f"Siswa {nama} berhasil ditambahkan.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/upload_excel_siswa", methods=["POST"])
def upload_excel_siswa():
    if "user" not in session or session.get("role") != "admin":
        return redirect(url_for("login"))
    
    file = request.files.get("file_excel")
    if file and file.filename.endswith((".xlsx", ".xls")):
        try:
            df = pd.read_excel(file)
            count = 0
            for _, row in df.iterrows():
                # Pastikan kolom excel sesuai (nis, nama, kelas)
                nis = str(row.get("nis", "")).strip()
                nama = str(row.get("nama", "")).strip()
                kelas = str(row.get("kelas", "")).strip()

                if nis and nis != "nan" and nama and nama != "nan":
                    # Jika NIS belum ada, masukkan ke database
                    if not User.query.filter_by(nis=nis).first():
                        db.session.add(
                            User(
                                nis=nis,
                                nama=nama,
                                kelas=kelas if kelas != "nan" else "",
                                password="123",
                                role="siswa",
                            )
                        )
                        count += 1
            db.session.commit()
            flash(f"Berhasil mengimpor {count} data siswa dari Excel.", "success")
        except Exception as e:
            flash(f"Gagal memproses file Excel: {e}", "danger")
    else:
        flash("Format file harus berupa .xlsx atau .xls", "danger")
        
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/edit_siswa/<int:id>", methods=["POST"])
def edit_siswa(id):
    if "user" not in session or session.get("role") != "admin":
        return redirect(url_for("login"))
    s = User.query.get_or_404(id)
    s.nis = request.form.get("nis", "").strip()
    s.nama = request.form.get("nama", "").strip()
    s.kelas = request.form.get("kelas", "").strip()
    db.session.commit()
    flash("Data siswa berhasil diperbarui.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/ganti_password/<int:id>", methods=["POST"])
def ganti_password_admin(id):
    if "user" not in session or session.get("role") != "admin":
        return redirect(url_for("login"))
    s = User.query.get_or_404(id)
    pw = request.form.get("new_password", "").strip()
    if pw:
        s.password = pw
        db.session.commit()
        flash(f"Password untuk siswa {s.nama} berhasil diubah.", "success")
    else:
        flash("Password tidak boleh kosong!", "danger")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/hapus_siswa/<int:id>")
def hapus_siswa(id):
    if "user" not in session or session.get("role") != "admin":
        return redirect(url_for("login"))
    s = User.query.get_or_404(id)
    if s.role == "siswa":
        db.session.delete(s)
        db.session.commit()
        flash("Siswa berhasil dihapus.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/hapus_absen/<int:id>")
def hapus_absen(id):
    if "user" not in session or session.get("role") != "admin":
        return redirect(url_for("login"))
    a = Absen.query.get_or_404(id)
    db.session.delete(a)
    db.session.commit()
    flash("Data absensi berhasil dihapus.", "success")
    return redirect(url_for("admin_dashboard"))


if __name__ == "__main__":
    app.run(debug=True)
