import json
import requests

# Store UI context triggers per request so your mobile/web app still receives {"context": "..."}!
UI_CONTEXT_EVENT = {}
# Track UI triggers per request
LAST_TRIGGERED_UI = {}

# Exact menu & sub-menu structure matching your Rasa Pro standard
GUEST_MENUS = [
        "Informasi Pendaftaran (PMB)",
        "Kalender Akademik",
        "Kontak BAAK & Layanan"
    ],

MAHASISWA_MENUS = [
    "Kartu Rencana Studi (KRS)",
    "Kartu Hasil Studi (KHS)",
    "Pembayaran",
    "Cuti Akademik",
    "Transkrip Nilai",
    "Kartu Peserta Ujian",
    "Tugas Akhir",
    "Wisuda",
    "SKPI",
    "Konseling",
    "Pertukaran Mahasiswa",
    "Fast Track",
    #"Profil"
]

DOSEN_BASE_MENUS = [
    "Jadwal Mengajar",
    "Input Nilai",
    "Bimbingan Tugas Akhir",
    "Penelitian & Pengabdian",
    "Profil Dosen"
]

DOSENWALI_EXTRA_MENUS = [
    "Approval KRS Mahasiswa",
    "Monitoring KHS Mahasiswa",
    "Persetujuan Cuti Mahasiswa",
    "Perwalian Akademik"
]

ROLE_MENUS = {
    "guest": GUEST_MENUS,
    "mahasiswa": MAHASISWA_MENUS,
    "dosen": DOSEN_BASE_MENUS,
    "dosenwali": DOSEN_BASE_MENUS + DOSENWALI_EXTRA_MENUS
}

SUBMENU_MAP = {
    # Mahasiswa
    "krs": ["Prosedur KRS", "Persyaratan KRS", "Transaksi KRS", "Hasil KRS"],
    "khs": ["Prosedur KHS", "Persyaratan KHS", "Hasil KHS"],
    "pembayaran": ["Prosedur Pembayaran", "Persyaratan Pembayaran", "Transaksi Pembayaran", "Status Pembayaran"],
    "cuti": ["Prosedur Cuti", "Persyaratan Cuti", "Transaksi Cuti", "Hasil Cuti"],
    "transkrip": ["Prosedur Transkrip", "Persyaratan Transkrip", "Hasil Transkrip"],
    "kartu_ujian": ["Prosedur Kartu Ujian", "Persyaratan Kartu Ujian", "Transaksi Kartu Ujian", "Hasil Kartu Ujian"],
    "tugas_akhir": ["Prosedur Tugas Akhir", "Persyaratan Tugas Akhir", "Transaksi Tugas Akhir", "Hasil Tugas Akhir"],
    "wisuda": ["Prosedur Wisuda", "Persyaratan Wisuda", "Transaksi Wisuda", "Hasil Wisuda"],
    "skpi": ["Prosedur SKPI", "Persyaratan SKPI", "Transaksi SKPI", "Hasil SKPI"],
    "konseling": ["Prosedur Konseling", "Persyaratan Konseling", "Transaksi Konseling", "Hasil Konseling"],
    "pertukaran": ["Prosedur Pertukaran Mahasiswa", "Persyaratan Pertukaran Mahasiswa", "Transaksi Pertukaran Mahasiswa", "Hasil Pertukaran Mahasiswa"],
    "fast_track": ["Prosedur Fast Track", "Persyaratan Fast Track", "Transaksi Fast Track", "Hasil Fast Track"],
    #"profil": ["Prosedur Profil", "Persyaratan Profil", "Transaksi Profil", "Hasil Profil"],
    
    # Dosen
    "jadwal_mengajar": ["Prosedur Jadwal Mengajar", "Persyaratan Jadwal Mengajar", "Transaksi Jadwal Mengajar", "Hasil Jadwal Mengajar"],
    "input_nilai": ["Prosedur Input Nilai", "Persyaratan Input Nilai", "Transaksi Input Nilai", "Hasil Input Nilai"],
    "bimbingan_ta": ["Prosedur Bimbingan TA", "Persyaratan Bimbingan TA", "Transaksi Bimbingan TA", "Hasil Bimbingan TA"],
    "penelitian": ["Prosedur Penelitian", "Persyaratan Penelitian", "Transaksi Penelitian", "Hasil Penelitian"],
    "profil_dosen": ["Prosedur Profil Dosen", "Persyaratan Profil Dosen", "Transaksi Profil Dosen", "Hasil Profil Dosen"],
    
    # Dosen Wali
    "approval_krs": ["Prosedur Approval KRS", "Persyaratan Approval KRS", "Transaksi Approval KRS", "Hasil Approval KRS"],
    "monitoring_khs": ["Prosedur Monitoring KHS", "Persyaratan Monitoring KHS", "Transaksi Monitoring KHS", "Hasil Monitoring KHS"],
    "persetujuan_cuti": ["Prosedur Persetujuan Cuti", "Persyaratan Persetujuan Cuti", "Transaksi Persetujuan Cuti", "Hasil Persetujuan Cuti"],
    "perwalian": ["Prosedur Perwalian", "Persyaratan Perwalian", "Transaksi Perwalian", "Hasil Perwalian"],
}

def show_menu_buttons(session_id: str, category: str = "main", role: str = "mahasiswa") -> str:
    """
    Menampilkan daftar tombol pilihan menu utama atau sub-menu (Prosedur, Persyaratan, Transaksi, Hasil) di layar chat.
    - Gunakan category='main' jika user bertanya 'menu apa saja yang tersedia' atau 'daftar layanan'.
    - Gunakan category='krs', 'khs', 'pembayaran', 'cuti', 'transkrip', 'wisuda', 'tugas_akhir', 'skpi', atau 'konseling'
      jika user memilih salah satu menu utama tanpa menyebut sub-menu spesifik.
    """
    cat = category.lower().strip()
    if cat == "main":
        buttons = ROLE_MENUS.get(role.lower(), ROLE_MENUS["mahasiswa"])
    else:
        buttons = SUBMENU_MAP.get(cat, [f"Prosedur {category}", f"Persyaratan {category}", f"Transaksi {category}", f"Hasil {category}"])

    LAST_TRIGGERED_UI.setdefault(session_id, {})["buttons"] = buttons
    return json.dumps({
        "status": "buttons_displayed",
        "buttons": buttons,
        "instruction": "Tombol pilihan sudah tampil di layar user. Jawab cukup 1 kalimat singkat meminta user memilih salah satu tombol."
    })


def get_peraturan_sismob(id_login: str, context_name: str) -> str:
    """
    Mengambil peraturan resmi terbaru dari API sismob.trisakti.ac.id berdasarkan IdLogin user dan context_name.
    Gunakan HANYA jika user memilih atau bertanya tentang 'Prosedur' atau 'Persyaratan'.
    """
    try:
        response = requests.post(
            "https://sismob.trisakti.ac.id/api/get-peraturan",
            json={"IdLogin": id_login, "context": context_name},
            timeout=10
        )
        if response.status_code == 200:
            data = response.json()
            aturan = data.get("body", {}).get("data", {}).get("aturan")
            if aturan:
                return aturan
    except Exception as e:
        print(f"Failed to fetch from get-peraturan API: {e}")
    return "Gunakan informasi prosedur/persyaratan dari dokumen panduan kampus."


def trigger_ui_context(session_id: str, menu_context: str) -> str:
    """
    Memicu tombol aksi layanan/portal di aplikasi mobile atau website SIS Trisakti.
    Gunakan fungsi ini HANYA jika user memilih atau meminta 'Hasil' atau 'Transaksi' dari suatu layanan
    (contoh: 'Hasil KHS', 'Transaksi KRS', 'Hasil Pembayaran', 'Transaksi Cuti').
    Nilai menu_context: 'kartuHasilStudi', 'kartuRencanaStudi', 'cuti', 'pembayaran', 'transkrip', 'wisuda', 'konseling', 'skpi', 'tugasAkhir', 'profil'.
    """
    LAST_TRIGGERED_UI.setdefault(session_id, {})["context"] = menu_context
    return json.dumps({
        "status": "action_button_shown",
        "context": menu_context,
        "instruction": "Tombol akses layanan sudah tampil di layar user. Jawab dengan SANGAT SINGKAT (1 kalimat)."
    })


STUDENT_TOOLS = [show_menu_buttons, get_peraturan_sismob, trigger_ui_context]

def open_sis_menu_ui(menu_context: str) -> str:
    """
    Memicu tampilan tombol/card menu di aplikasi mobile atau website SIS Trisakti.
    Gunakan fungsi ini saat user ingin melihat hasil/halaman layanan tertentu, seperti:
    'kartuHasilStudi', 'kartuRencanaStudi', 'cuti', 'pembayaran', 'transkrip', 'wisuda', 'konseling', 'skpi', 'tugasAkhir', 'profil'.
    """
    UI_CONTEXT_EVENT["context"] = menu_context
    return json.dumps({"status": "ui_triggered", "context": menu_context})