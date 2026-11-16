import json
import requests

# Store UI context triggers per request so your mobile/web app still receives {"context": "..."}!
UI_CONTEXT_EVENT = {}

def get_peraturan_sismob(id_login: str, context_name: str) -> str:
    """
    Mengambil peraturan resmi terbaru dari API sismob.trisakti.ac.id berdasarkan IdLogin user dan context_name.
    Contoh context_name: 'kartuHasilStudi_prosedur', 'kartuHasilStudi_persyaratan', 'cuti_prosedur', 'pembayaran_prosedur'.
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
    return "API SISMOB sedang tidak merespons, gunakan informasi dari dokumen panduan kampus."


def trigger_ui_context(menu_context: str) -> str:
    """
    Memicu tampilan tombol/card menu di frontend website/mobile SIS Trisakti.
    Gunakan fungsi ini jika user ingin membuka layanan/hasil tertentu, misalnya:
    'kartuHasilStudi', 'kartuRencanaStudi', 'cuti', 'pembayaran', 'transkrip', 'wisuda', 'konseling', 'skpi', 'tugasAkhir', 'profil'.
    """
    return json.dumps({"triggered_context": menu_context})

STUDENT_TOOLS = [get_peraturan_sismob, trigger_ui_context]

def open_sis_menu_ui(menu_context: str) -> str:
    """
    Memicu tampilan tombol/card menu di aplikasi mobile atau website SIS Trisakti.
    Gunakan fungsi ini saat user ingin melihat hasil/halaman layanan tertentu, seperti:
    'kartuHasilStudi', 'kartuRencanaStudi', 'cuti', 'pembayaran', 'transkrip', 'wisuda', 'konseling', 'skpi', 'tugasAkhir', 'profil'.
    """
    UI_CONTEXT_EVENT["context"] = menu_context
    return json.dumps({"status": "ui_triggered", "context": menu_context})