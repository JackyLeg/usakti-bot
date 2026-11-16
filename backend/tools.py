import json
import requests

# Store UI context triggers per request so your mobile/web app still receives {"context": "..."}!
UI_CONTEXT_EVENT = {}
# Track UI triggers per request
LAST_TRIGGERED_UI = {}

def get_peraturan_sismob(id_login: str, context_name: str) -> str:
    """
    Mengambil peraturan resmi terbaru dari API sismob.trisakti.ac.id berdasarkan IdLogin user dan context_name.
    Gunakan HANYA jika user bertanya tentang 'prosedur' atau 'persyaratan'.
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
    Memicu tombol/card menu interaktif di aplikasi mobile atau website SIS Trisakti.
    Gunakan fungsi ini saat user ingin melihat hasil/data pribadi atau membuka layanan tertentu, seperti:
    'kartuHasilStudi', 'kartuRencanaStudi', 'cuti', 'pembayaran', 'transkrip', 'wisuda', 'konseling', 'skpi', 'tugasAkhir', 'profil'.
    """
    LAST_TRIGGERED_UI[session_id] = menu_context
    return json.dumps({
        "status": "button_shown",
        "context": menu_context,
        "instruction": "Tombol menu sudah ditampilkan di layar aplikasi user. Jawab dengan SANGAT SINGKAT (maksimal 1-2 kalimat) tanpa menjelaskan langkah-langkah portal panjang lebar."
    })

STUDENT_TOOLS = [get_peraturan_sismob, trigger_ui_context]

def open_sis_menu_ui(menu_context: str) -> str:
    """
    Memicu tampilan tombol/card menu di aplikasi mobile atau website SIS Trisakti.
    Gunakan fungsi ini saat user ingin melihat hasil/halaman layanan tertentu, seperti:
    'kartuHasilStudi', 'kartuRencanaStudi', 'cuti', 'pembayaran', 'transkrip', 'wisuda', 'konseling', 'skpi', 'tugasAkhir', 'profil'.
    """
    UI_CONTEXT_EVENT["context"] = menu_context
    return json.dumps({"status": "ui_triggered", "context": menu_context})