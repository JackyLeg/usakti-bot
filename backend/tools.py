import json
import requests

# Store UI context triggers per request so your mobile/web app still receives {"context": "..."}!
UI_CONTEXT_EVENT = {}
# Track UI triggers per request
LAST_TRIGGERED_UI = {}

# Exact menu & sub-menu structure matching your Rasa Pro standard
ROLE_MENUS = {
    "mahasiswa": [
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
        "Profil"
    ],
    "dosen": [
        "Jadwal Mengajar",
        "Input Nilai",
        "Perwalian",
        "Profil Dosen"
    ],
    "dosenwali": [
        "Approval KRS Mahasiswa",
        "Monitoring KHS Mahasiswa",
        "Persetujuan Cuti",
        "Bimbingan Akademik"
    ]
}

SUBMENU_MAP = {
    "krs": ["Prosedur KRS", "Persyaratan KRS", "Transaksi KRS", "Hasil KRS"],
    "khs": ["Prosedur KHS", "Persyaratan KHS", "Transaksi KHS", "Hasil KHS"],
    "pembayaran": ["Prosedur Pembayaran", "Persyaratan Pembayaran", "Transaksi Pembayaran", "Hasil Pembayaran"],
    "cuti": ["Prosedur Cuti", "Persyaratan Cuti", "Transaksi Cuti", "Hasil Cuti"],
    "transkrip": ["Prosedur Transkrip", "Persyaratan Transkrip", "Transaksi Transkrip", "Hasil Transkrip"],
    "wisuda": ["Prosedur Wisuda", "Persyaratan Wisuda", "Transaksi Wisuda", "Hasil Wisuda"],
    "tugas_akhir": ["Prosedur Tugas Akhir", "Persyaratan Tugas Akhir", "Transaksi Tugas Akhir", "Hasil Tugas Akhir"],
    "skpi": ["Prosedur SKPI", "Persyaratan SKPI", "Transaksi SKPI", "Hasil SKPI"],
    "konseling": ["Prosedur Konseling", "Persyaratan Konseling", "Transaksi Konseling", "Hasil Konseling"],
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