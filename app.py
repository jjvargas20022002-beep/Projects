from flask import Flask, render_template, request, redirect, url_for, session, send_file, jsonify
import gspread
from gspread.exceptions import APIError
from google.oauth2.service_account import Credentials
import os
import pandas as pd
from io import BytesIO
from pathlib import Path
import difflib
import unicodedata
import json
import re
import hashlib
import time
import requests
from google.auth.transport.requests import Request
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
import time

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "secret_key_temporal")

# =====================
# GOOGLE SHEETS CONFIG
# =====================
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

SHEET_INIT_ERROR = None
sheet = None

def _get_service_account_info():
    required_env = [
        "GCP_PROJECT_ID",
        "GCP_PRIVATE_KEY_ID",
        "GCP_PRIVATE_KEY",
        "GCP_CLIENT_EMAIL",
        "GCP_CLIENT_ID",
        "GCP_CLIENT_CERT_URL",
    ]
    missing_vars = [var for var in required_env if not os.environ.get(var)]
    if missing_vars:
        raise ValueError(f"Faltan variables de entorno: {', '.join(missing_vars)}")

    return {
        "type": "service_account",
        "project_id": os.environ["GCP_PROJECT_ID"],
        "private_key_id": os.environ["GCP_PRIVATE_KEY_ID"],
        "private_key": os.environ["GCP_PRIVATE_KEY"].replace("\\n", "\n"),
        "client_email": os.environ["GCP_CLIENT_EMAIL"],
        "client_id": os.environ["GCP_CLIENT_ID"],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_x509_cert_url": os.environ["GCP_CLIENT_CERT_URL"],
    }


def _get_service_account_credentials(scopes):
    info = _get_service_account_info()
    return Credentials.from_service_account_info(info, scopes=scopes)

def init_google_sheet():
    global sheet, SHEET_INIT_ERROR

    required_env = [
        "GCP_PROJECT_ID",
        "GCP_PRIVATE_KEY_ID",
        "GCP_PRIVATE_KEY",
        "GCP_CLIENT_EMAIL",
        "GCP_CLIENT_ID",
        "GCP_CLIENT_CERT_URL",
        "SPREADSHEET_ID",
    ]
    missing_vars = [var for var in required_env if not os.environ.get(var)]
    if missing_vars:
        SHEET_INIT_ERROR = f"Faltan variables de entorno: {', '.join(missing_vars)}"
        sheet = None
        return
    try:
        creds = _get_service_account_credentials(SCOPES)
        gc = gspread.authorize(creds)
        sheet = gc.open_by_key(os.environ["SPREADSHEET_ID"])
        SHEET_INIT_ERROR = None
    except Exception as exc:
        sheet = None
        SHEET_INIT_ERROR = f"No se pudo conectar a Google Sheets: {exc}"


def get_sheet_or_error():
    if sheet is None:
        init_google_sheet()
    return sheet, SHEET_INIT_ERROR


UPDATE_SUMMARY_CACHE = {
    "fetched_at": 0.0,
    "data": None,
}
UPDATE_SUMMARY_TTL_SECONDS = int(os.environ.get("UPDATE_SUMMARY_TTL_SECONDS", "45"))
UPDATE_MIN_TABS_WITH_ROW_CHANGES = int(os.environ.get("UPDATE_MIN_TABS_WITH_ROW_CHANGES", "3"))



UPDATE_NOTIFIER_STATE_PATH = Path(
    os.environ.get(
        "UPDATE_NOTIFIER_STATE_PATH",
        Path(__file__).resolve().parent / "update_notifier_state.json",
    )
)
FCM_PUSH_ENABLED = os.environ.get("FCM_PUSH_ENABLED", "0") == "1"
FCM_PROJECT_ID = os.environ.get("FCM_PROJECT_ID", os.environ.get("GCP_PROJECT_ID", "")).strip()
FCM_TOPIC_AVERIAS = os.environ.get("FCM_TOPIC_AVERIAS", "averias_updates").strip()
FCM_TOPIC_DESPLIEGUE = os.environ.get("FCM_TOPIC_DESPLIEGUE", "despliegue_updates").strip()
SCHEDULER_TOKEN = os.environ.get("SCHEDULER_TOKEN", "").strip()

def _build_sheet_fingerprint(values):
    """Calcula un hash estable sin materializar una copia gigante en memoria.

    La versión anterior usaba json.dumps(values), lo que duplicaba temporalmente
    la data completa de cada pestaña como un único string grande.
    """
    digest = hashlib.sha256()
    row_sep = "\x1e".encode("utf-8")
    col_sep = "\x1f".encode("utf-8")

    for row in values:
        for cell in row:
            digest.update(str(cell).encode("utf-8"))
            digest.update(col_sep)
        digest.update(row_sep)

    return digest.hexdigest()


def compute_updates_summary(sheet_client):
    worksheets = sheet_client.worksheets()
    averias_fingerprints_by_title = {}
    despliegue_fingerprint = ""
    total_data_rows = 0
    tab_row_counts = {}

    for ws in worksheets:
        title = ws.title
        values = ws.get_all_values()
        digest = _build_sheet_fingerprint(values)
        row_count = max(len(values) - 1, 0)
        tab_row_counts[title] = row_count
        total_data_rows += row_count

        if title == DEPLOYMENT_TAB:
            despliegue_fingerprint = digest
        else:
            averias_fingerprints_by_title[title] = digest

    averias_digest_builder = hashlib.sha256()
    for title in sorted(averias_fingerprints_by_title):
        averias_digest_builder.update(title.encode("utf-8"))
        averias_digest_builder.update(b":")
        averias_digest_builder.update(averias_fingerprints_by_title[title].encode("utf-8"))
        averias_digest_builder.update(b"|")
    averias_digest = averias_digest_builder.hexdigest()


    return {
        "averias_hash": averias_digest,
        "despliegue_hash": despliegue_fingerprint,
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "total_data_rows": total_data_rows,
        "tab_row_counts": tab_row_counts,
    }


def get_updates_summary_cached(force_refresh=False):
    now = time.time()
    cache_data = UPDATE_SUMMARY_CACHE.get("data")
    age = now - UPDATE_SUMMARY_CACHE.get("fetched_at", 0.0)

    if not force_refresh and cache_data and age < UPDATE_SUMMARY_TTL_SECONDS:
        return cache_data

    sheet_client, _ = get_sheet_or_error()
    if sheet_client is None:
        fallback = cache_data or {
            "averias_hash": "",
            "despliegue_hash": "",
            "generated_at": "",
            "last_change_at": "",
            "total_data_rows": 0,
            "tab_row_counts": {},
            "tabs_with_row_changes": 0,
            "awaiting_full_restore": False,
        }
        return fallback
    fallback = cache_data or {
        "averias_hash": "",
        "despliegue_hash": "",
        "generated_at": "",
        "last_change_at": "",
        "total_data_rows": 0,
        "tab_row_counts": {},
        "tabs_with_row_changes": 0,
        "awaiting_full_restore": False,
    }



    try:
        summary = compute_updates_summary(sheet_client)
    except APIError:
        # Si Google Sheets devuelve 429 por cuota, mantener servicio con cache previa.
        return fallback

    previous_summary = cache_data or _load_update_notifier_state()
    had_previous = bool(
        previous_summary.get("averias_hash")
        or previous_summary.get("despliegue_hash")
    )

    # Cuando toda la data desaparece temporalmente, marcamos espera de restauración
    # y conservamos el último timestamp válido.
    if had_previous and summary.get("total_data_rows", 0) == 0:
        stable_summary = {
            **previous_summary,
            "generated_at": summary.get("generated_at", previous_summary.get("generated_at", "")),
            "total_data_rows": summary.get("total_data_rows", 0),
            "awaiting_full_restore": True,
        }
        UPDATE_SUMMARY_CACHE["fetched_at"] = now
        UPDATE_SUMMARY_CACHE["data"] = stable_summary
        return stable_summary
    awaiting_full_restore = bool(previous_summary.get("awaiting_full_restore", False))
    full_restore_detected = awaiting_full_restore and summary.get("total_data_rows", 0) > 0



    previous_tab_rows = previous_summary.get("tab_row_counts", {})
    current_tab_rows = summary.get("tab_row_counts", {})
    tabs_to_compare = set(previous_tab_rows.keys()) | set(current_tab_rows.keys())
    tabs_with_row_changes = sum(
        1
        for tab_name in tabs_to_compare
        if int(current_tab_rows.get(tab_name, 0) or 0) != int(previous_tab_rows.get(tab_name, 0) or 0)
    )
    summary["tabs_with_row_changes"] = tabs_with_row_changes

    should_update_last_change_at = (
        not had_previous
        or full_restore_detected
        or tabs_with_row_changes >= UPDATE_MIN_TABS_WITH_ROW_CHANGES
    )

    if should_update_last_change_at:
        summary["last_change_at"] = summary.get("generated_at", "")
    else:
        summary["last_change_at"] = previous_summary.get("last_change_at", "")
    summary["awaiting_full_restore"] = False


    UPDATE_SUMMARY_CACHE["fetched_at"] = now
    UPDATE_SUMMARY_CACHE["data"] = summary
    return summary


def _load_update_notifier_state():
    if not UPDATE_NOTIFIER_STATE_PATH.exists():
        return {
            "averias_hash": "",
            "despliegue_hash": "",
            "averias_has_data": False,
            "despliegue_has_data": False,
            "generated_at": "",
            "last_change_at": "",
            "total_data_rows": 0,
            "tab_row_counts": {},
            "tabs_with_row_changes": 0,
            "awaiting_full_restore": False,
        }

    try:
        with UPDATE_NOTIFIER_STATE_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {
            "averias_hash": "",
            "despliegue_hash": "",
            "averias_has_data": False,
            "despliegue_has_data": False,
            "generated_at": "",
            "last_change_at": "",
            "total_data_rows": 0,
            "tab_row_counts": {},
            "tabs_with_row_changes": 0,
            "awaiting_full_restore": False,
        }

    if not isinstance(data, dict):
        return {
            "averias_hash": "",
            "despliegue_hash": "",
            "averias_has_data": False,
            "despliegue_has_data": False,
            "generated_at": "",
            "last_change_at": "",
            "total_data_rows": 0,
            "tab_row_counts": {},
            "tabs_with_row_changes": 0,
            "awaiting_full_restore": False,
        }

    return {
        "averias_hash": data.get("averias_hash", ""),
        "despliegue_hash": data.get("despliegue_hash", ""),
        "averias_has_data": bool(data.get("averias_has_data", False)),
        "despliegue_has_data": bool(data.get("despliegue_has_data", False)),
        "generated_at": data.get("generated_at", ""),
        "last_change_at": data.get("last_change_at", ""),
        "total_data_rows": int(data.get("total_data_rows", 0) or 0),
        "tab_row_counts": data.get("tab_row_counts", {}) if isinstance(data.get("tab_row_counts", {}), dict) else {},
        "tabs_with_row_changes": int(data.get("tabs_with_row_changes", 0) or 0),
        "awaiting_full_restore": bool(data.get("awaiting_full_restore", False)),
    }


def _save_update_notifier_state(summary):
    UPDATE_NOTIFIER_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "averias_hash": summary.get("averias_hash", ""),
        "despliegue_hash": summary.get("despliegue_hash", ""),
        "averias_has_data": bool(summary.get("averias_has_data", False)),
        "despliegue_has_data": bool(summary.get("despliegue_has_data", False)),
        "generated_at": summary.get("generated_at", ""),
        "last_change_at": summary.get("last_change_at", ""),
        "total_data_rows": int(summary.get("total_data_rows", 0) or 0),
        "tab_row_counts": summary.get("tab_row_counts", {}) if isinstance(summary.get("tab_row_counts", {}), dict) else {},
        "tabs_with_row_changes": int(summary.get("tabs_with_row_changes", 0) or 0),
        "awaiting_full_restore": bool(summary.get("awaiting_full_restore", False)),
    }
    with UPDATE_NOTIFIER_STATE_PATH.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _send_fcm_topic_message(topic, body_message, data_payload=None):
    if not FCM_PUSH_ENABLED:
        return {"sent": False, "reason": "fcm_disabled"}

    if not FCM_PROJECT_ID:
        return {"sent": False, "reason": "missing_fcm_project_id"}

    if not topic:
        return {"sent": False, "reason": "missing_topic"}

    try:
        creds = _get_service_account_credentials(["https://www.googleapis.com/auth/firebase.messaging"])
        creds.refresh(Request())
    except Exception as exc:
        return {"sent": False, "reason": f"token_error:{exc}"}

    payload = {
        "message": {
            "topic": topic,
            "notification": {
                "title": "Averías FTTH",
                "body": body_message,
            },
            "data": data_payload or {},
        }
    }

    try:
        response = requests.post(
            f"https://fcm.googleapis.com/v1/projects/{FCM_PROJECT_ID}/messages:send",
            headers={
                "Authorization": f"Bearer {creds.token}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            json=payload,
            timeout=12,
        )
    except Exception as exc:
        return {"sent": False, "reason": f"request_error:{exc}"}

    if response.status_code >= 400:
        return {
            "sent": False,
            "reason": f"http_{response.status_code}",
            "response": response.text[:350],
        }

    return {"sent": True}


def check_and_send_update_notifications(force_refresh=True):
    """Detecta cambios reales en la data y dispara push FCM desde backend."""
    previous_state = _load_update_notifier_state()
    summary = get_updates_summary_cached(force_refresh=force_refresh)

    previous_last_change_at = previous_state.get("last_change_at", "")
    current_last_change_at = summary.get("last_change_at", "")
    has_real_change = bool(current_last_change_at and current_last_change_at != previous_last_change_at)

    averias_changed = (
        bool(summary.get("averias_hash"))
        and summary.get("averias_hash") != previous_state.get("averias_hash", "")
        and has_real_change
    )
    despliegue_changed = (
        bool(summary.get("despliegue_hash"))
        and summary.get("despliegue_hash") != previous_state.get("despliegue_hash", "")
        and has_real_change
    )

    body_message = f"Información actualizada ({current_last_change_at})"

    averias_notify = {"sent": False, "reason": "no_change"}
    if averias_changed:
        averias_notify = _send_fcm_topic_message(
            topic=FCM_TOPIC_AVERIAS,
            body_message=body_message,
            data_payload={
                "type": "updates_summary",
                "segment": "averias",
                "last_change_at": current_last_change_at,
            },
        )

    despliegue_notify = {"sent": False, "reason": "no_change"}
    if despliegue_changed:
        despliegue_notify = _send_fcm_topic_message(
            topic=FCM_TOPIC_DESPLIEGUE,
            body_message=body_message,
            data_payload={
                "type": "updates_summary",
                "segment": "despliegue",
                "last_change_at": current_last_change_at,
            },
        )

    results = {
        "averias": {
            "triggered": averias_changed,
            "notify": averias_notify,
        },
        "despliegue": {
            "triggered": despliegue_changed,
            "notify": despliegue_notify,
        },
        "last_change_at_changed": has_real_change,
        "summary": summary,
    }



    _save_update_notifier_state(summary)
    return results


# ======================
# ESTADO DE CAJAS DESDE PENDIENTES ODN
# =====================
estado_cajas = {}
ESTADO_CAJAS_LAST_REFRESH = 0
ESTADO_CAJAS_TTL_SECONDS = int(os.environ.get("ESTADO_CAJAS_TTL_SECONDS", "300"))



def refresh_estado_cajas():
    global estado_cajas, ESTADO_CAJAS_LAST_REFRESH

    estado_cajas = {}

    sheet_client, _ = get_sheet_or_error()
    if sheet_client is None:
        return

    try:
        ws_odn = sheet_client.worksheet("PENDIENTES ODN")
        odn_data = ws_odn.get_all_values()
        odn_headers = odn_data[0]
        odn_rows = odn_data[1:]

        caja_odn_idx = None
        estado_odn_idx = None

        for i, h in enumerate(odn_headers):
            if h.strip().upper() == "CAJA":
                caja_odn_idx = i
            if "STATUS DE LA CAJA" in h.strip().upper():
                estado_odn_idx = i

        if caja_odn_idx is not None and estado_odn_idx is not None:
            for r in odn_rows:
                if len(r) > max(caja_odn_idx, estado_odn_idx):
                    caja = r[caja_odn_idx].strip().upper()
                    estado = r[estado_odn_idx].strip()
                    if caja and estado:
                        estado_cajas[caja] = estado
        ESTADO_CAJAS_LAST_REFRESH = int(time.time())
    except Exception:
        estado_cajas = {}
        ESTADO_CAJAS_LAST_REFRESH = 0


def ensure_estado_cajas_fresh(force=False):
    now = int(time.time())
    if force or not estado_cajas or (now - ESTADO_CAJAS_LAST_REFRESH) >= ESTADO_CAJAS_TTL_SECONDS:
        refresh_estado_cajas()




# =====================
# CONFIG
# ====================
BRANCH_TABS = [
    "GARANTIAS LIMA",
    "GARANTIAS PROVINCIA",
    "FUERA DE GARANTÍA PROVINCIA",
    "CANCELADOS",
    "PENDIENTES ODN",
]

SINGLE_BRANCH_TAB = "ONLINE LIMA"
DEPLOYMENT_TAB = "DESPLIEGUE"

STATUS_FROM_ODN_TABS = [
    "GARANTIAS LIMA",
    "LI1 TGI",
    "LI2 DIJUSA",
    "LI2 ERAM",
    "LI3 INTER",
    "LI4 TGI",
    "LI4 BROKERS",
    "LI7 MARCOS",
]

UNFILTERED_ACCESS_TABS = {
    "LI1 TGI",
    "LI2 DIJUSA",
    "LI2 ERAM",
    "LI3 INTER",
    "LI4 TGI",
    "LI4 BROKERS",
    "LI7 MARCOS",
}
UNFILTERED_PARTNER_TABS = {
    "LI1 TGI",
    "LI2 DIJUSA",
    "LI2 ERAM",
    "LI3 INTER",
    "LI4 TGI",
    "LI4 BROKERS",
    "LI7 MARCOS",
}


PROVINCIA_TABS = {
    "GARANTIAS PROVINCIA",
    "FUERA DE GARANTÍA PROVINCIA",
}

PROVINCIA_BRANCHES = {"ARE", "CAJ", "CUS", "HUN", "JUN", "LAL", "PIU", "SAN"}


PORT_VALIDATION_SPREADSHEET_ID = os.environ.get(
    "PORT_VALIDATION_SPREADSHEET_ID",
    "1u1I-DCeWaLeyqAQ4Nw0geoBY2p2xQ9RExFzBlsQ7huc",
).strip()
PORT_VALIDATION_OLTS = [1, 2, 3, 11]
PORT_VALIDATION_VALID_OLTS = [1, 2, 11]
PORT_VALIDATION_BRAS_ENDPOINT = os.environ.get(
    "PORT_VALIDATION_BRAS_ENDPOINT",
    "http://10.121.62.102:8080/backup/cgi-bin/bras_checkuser/bras_checkkick_online.php",
).strip()
PORT_VALIDATION_STATE_KEY = "port_validation_state"


# =====================
# PORT VALIDATION UTILS
# =====================
def get_gspread_client_or_error():
    try:
        creds = _get_service_account_credentials(SCOPES)
        return gspread.authorize(creds), None
    except Exception as exc:
        return None, f"No se pudo crear cliente de Google Sheets: {exc}"


def open_port_validation_spreadsheet_or_error():
    gc, error = get_gspread_client_or_error()
    if gc is None:
        return None, error

    spreadsheet_id = (PORT_VALIDATION_SPREADSHEET_ID or "").strip()
    if not spreadsheet_id:
        return None, "PORT_VALIDATION_SPREADSHEET_ID está vacío."

    try:
        return gc.open_by_key(spreadsheet_id), None
    except Exception as exc:
        return None, f"No se pudo abrir el spreadsheet de validación: {exc}"


def worksheet_to_dataframe(spreadsheet, worksheet_title):
    ws = spreadsheet.worksheet(worksheet_title)
    values = ws.get_all_values()
    if not values:
        return pd.DataFrame()

    headers = [str(h).strip() for h in values[0]]
    rows = values[1:]
    max_len = max([len(headers)] + [len(r) for r in rows])

    padded_headers = headers + [f"COL_{i+1}" for i in range(len(headers), max_len)]
    normalized_rows = [r + [""] * (max_len - len(r)) for r in rows]

    return pd.DataFrame(normalized_rows, columns=padded_headers)


def _cell_from_row(row, idx=None, key=None, default=""):
    if key and key in row:
        return str(row.get(key, default) or default)
    if idx is not None:
        try:
            return str(row.iloc[idx] or default)
        except Exception:
            return default
    return default


def generar_infra(site, olt, box):
    site = (site or "").strip()
    box = (box or "").strip()
    if not (site and olt and box):
        return ""

    tercer_char = box[2] if len(box) >= 3 else ""
    if int(olt) == 11:
        return f"{site}-XB{olt}-HB0{tercer_char}-{box}".upper()
    return f"{site}-XB0{olt}-HB0{tercer_char}-{box}".upper()


def generar_port(site, olt, box):
    orden_map = {
        11: 1, 12: 2, 13: 3, 14: 4,
        21: 5, 22: 6, 23: 7, 24: 8,
        31: 9, 32: 10, 33: 11, 34: 12,
        41: 13, 42: 14, 43: 15, 44: 16,
    }

    box = (box or "").strip()
    site = (site or "").strip()
    if len(box) < 4:
        return None

    try:
        par = int(box[2:4])
    except Exception:
        return None

    orden = orden_map.get(par)
    if not orden:
        return None

    return f"{site.upper()}OLT0{olt}/3/{orden}".upper()


def extraer_estado(texto):
    text = str(texto or "")
    lowered = text.lower()
    if "online on bras" in lowered:
        return "ONLINE"
    if "not online on bras" in lowered or "no session" in lowered:
        return "NOT ONLINE"
    return "UNKNOWN"


def extraer_info(texto):
    text = str(texto or "")
    estado = extraer_estado(text)
    ipv4 = re.search(r"ipv4[-_\s]*address\s*:\s*([\d\.]+)", text, flags=re.IGNORECASE)
    if ipv4:
        ip_value = ipv4.group(1)
        ip_status = "IP OK" if not (ip_value.startswith("172.") or ip_value.startswith("9.")) else "IP NOK"
    else:
        ip_status = "IP NOK"
    return estado, ip_status


def consultar_estado_en_bras(username, bras):
    params = {
        "cat": "view",
        "acc": (username or "").strip(),
        "domain": "",
        "bras": (bras or "").strip(),
    }

    try:
        response = requests.get(PORT_VALIDATION_BRAS_ENDPOINT, params=params, timeout=7)
        if response.status_code != 200:
            return "ERROR", "IP NOK"

        cleaned = re.sub(r"<script[\s\S]*?</script>", " ", response.text, flags=re.IGNORECASE)
        cleaned = re.sub(r"<style[\s\S]*?</style>", " ", cleaned, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", cleaned)
        text = re.sub(r"\s+", " ", text).strip()
        return extraer_info(text)
    except Exception:
        return "ERROR", "IP NOK"


def obtener_resultado_estado(df_tms, site, olt, box):
    port = generar_port(site, olt, box)
    if not port:
        return None, "No se pudo formar PORT."

    if df_tms.empty or df_tms.shape[1] < 12:
        return None, "La hoja TMs no tiene columnas suficientes."

    col_d_clean = df_tms.iloc[:, 3].astype(str).apply(lambda x: x.split(":")[0])
    df_filtrado = df_tms[col_d_clean.str.contains(f"^{re.escape(port)}/", regex=True, na=False)]

    if df_filtrado.empty:
        return pd.DataFrame(), None

    estados = []
    ips = []
    for _, row in df_filtrado.iterrows():
        username = _cell_from_row(row, idx=1, key="USERNAME")
        bras = _cell_from_row(row, key="BRAS")
        estado, ip_status = consultar_estado_en_bras(username, bras)
        estados.append(estado)
        ips.append(ip_status)

    resultado = pd.DataFrame({
        "USERNAME": df_filtrado.apply(lambda r: _cell_from_row(r, idx=1, key="USERNAME"), axis=1),
        "Estado_D": df_filtrado.iloc[:, 3].replace({"0": "Activo", "2": "Suspendido", 0: "Activo", 2: "Suspendido"}),
        "Col_E": df_filtrado.iloc[:, 4],
        "Ultima_sesion": df_filtrado.iloc[:, 11].fillna("Never ONLINE"),
        "Estado_BRAS": estados,
        "IP_Status": ips,
    })

    return resultado, None


def calcular_diferencias(df_ref, df_new):
    if df_ref is None or df_new is None or df_ref.empty or df_new.empty:
        return pd.DataFrame()

    ref = df_ref.copy().fillna("").astype(str)
    new = df_new.copy().fillna("").astype(str)

    common_cols = [c for c in ref.columns if c in new.columns]
    if not common_cols:
        return pd.DataFrame()

    if "USERNAME" in common_cols:
        ref = ref.set_index("USERNAME", drop=False)
        new = new.set_index("USERNAME", drop=False)
        aligned_index = ref.index.intersection(new.index)
        if aligned_index.empty:
            return pd.DataFrame()
        ref = ref.loc[aligned_index, common_cols]
        new = new.loc[aligned_index, common_cols]
    else:
        min_len = min(len(ref), len(new))
        ref = ref.iloc[:min_len][common_cols]
        new = new.iloc[:min_len][common_cols]

    mask = (new != ref).any(axis=1)
    return new.loc[mask].reset_index(drop=True)



# =====================
# LOGIN DESDE STAFF.xlsx
# =====================
STAFF_PATH = Path(os.environ.get("STAFF_FILE_PATH", Path(__file__).resolve().parent / "STAFF.xlsx"))
ADMIN_USERS = {
    username.strip().lower()
    for username in os.environ.get("ADMIN_USERS", "").split(",")
    if username.strip()
}

PASSWORD_OVERRIDES_PATH = Path(
    os.environ.get(
        "PASSWORD_OVERRIDES_PATH",
        Path(__file__).resolve().parent / "password_overrides.json",
    )
)
PASSWORD_AUDIT_LOG_PATH = Path(
    os.environ.get(
        "PASSWORD_AUDIT_LOG_PATH",
        Path(__file__).resolve().parent / "password_changes.log",
    )
)


def load_staff_users():
    users = {}

    if not STAFF_PATH.exists():
        return users

    try:
        staff_df = pd.read_excel(STAFF_PATH, dtype=str).fillna("")
    except Exception:
        return users

    normalized_columns = {normalize(col): col for col in staff_df.columns}

    username_col = normalized_columns.get("USUARIO") or normalized_columns.get("USERNAME")
    password_col = (
        normalized_columns.get("CONTRASEÑA")
        or normalized_columns.get("CONTRASENA")
        or normalized_columns.get("PASSWORD")
    )
    role_col = normalized_columns.get("ROLE")
    branch_col = normalized_columns.get("BRANCH")
    partner_col = normalized_columns.get("PARTNER")
    access_cols = [
        col
        for normalized_name, col in normalized_columns.items()
        if normalized_name.startswith("ACCESS")
    ]

    if not username_col or not password_col:
        return users

    for _, row in staff_df.iterrows():
        username = str(row.get(username_col, "")).strip().lower()
        password = str(row.get(password_col, "")).strip()
        role = str(row.get(role_col, "")).strip() if role_col else ""
        branch = str(row.get(branch_col, "")).strip() if branch_col else ""
        partner = str(row.get(partner_col, "")).strip() if partner_col else ""
        allowed_tabs = [
            str(row.get(col, "")).strip()
            for col in access_cols
            if str(row.get(col, "")).strip()
        ]


        if not username or not password:
            continue

        is_admin = (
            username in ADMIN_USERS
            or normalize(role) == "ADMIN"
            or normalize(branch) == "ADMIN"
            or normalize(partner) == "ADMIN"
        )

        users[username] = {
            "password": password,
            "role": role,
            "branch": branch,
            "partner": partner,
            "is_admin": is_admin,
            "allowed_tabs": allowed_tabs,
        }

    return users

# =====================
# UTILS
# =====================
def coord_to_link(value):
    try:
        lat, lng = map(float, value.replace(" ", "").split(",", 1))
        return f"https://www.google.com/maps?q={lat},{lng}"
    except:
        return None


def get_coord_indices(headers):
    coord_idx = find_col_from_candidates(headers, ["COORDENADAS", "COORDENADA", "COORD", "LAT,LNG", "LATITUD,LONGITUD"])
    lat_idx = find_col_from_candidates(headers, ["LAT", "LATITUD"])
    lng_idx = find_col_from_candidates(headers, ["LNG", "LONG", "LONGITUD"])
    return coord_idx, lat_idx, lng_idx

def parse_coord_text(value):
    text = (value or "").strip()
    if not text:
        return None

    # Acepta formatos como:
    # -16.3781,-71.5062
    # -16,3781,-71,5062
    # -16,3781; -71,5062
    matches = re.findall(r"[-+]?\d+(?:[\.,]\d+)?", text)
    if len(matches) < 2:
        return None

    try:
        lat = float(matches[0].replace(",", "."))
        lng = float(matches[1].replace(",", "."))
    except Exception:
        return None

    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None

    return lat, lng


def get_row_lat_lng(row, coord_idx=None, lat_idx=None, lng_idx=None):
    try:
        if coord_idx is not None and len(row) > coord_idx and row[coord_idx].strip():
            parsed = parse_coord_text(row[coord_idx])
            if parsed:
                return parsed


        if (
            lat_idx is not None and lng_idx is not None
            and len(row) > max(lat_idx, lng_idx)
            and row[lat_idx].strip() and row[lng_idx].strip()
        ):
            return float(row[lat_idx].replace(",", ".")), float(row[lng_idx].replace(",", "."))
    except Exception:
        return None

    return None

def normalize(text):
    return "".join(text.upper().split()) if text else ""

def normalize_key(text):
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", str(text))
    without_accents = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return "".join(ch for ch in without_accents.upper() if ch.isalnum())

def normalize_username_input(value):
    return (value or "").strip().lower()

USERS = {}
USERS_SIGNATURE = None


def get_staff_signature():
    if not STAFF_PATH.exists():
        return None

    stat_result = STAFF_PATH.stat()
    return (stat_result.st_mtime_ns, stat_result.st_size)


def get_users(force_reload=False):
    global USERS, USERS_SIGNATURE

    current_signature = get_staff_signature()

    if force_reload or USERS_SIGNATURE != current_signature:
        USERS = load_staff_users()
        USERS_SIGNATURE = current_signature

    return USERS

def load_password_overrides():
    if not PASSWORD_OVERRIDES_PATH.exists():
        return {}

    try:
        with PASSWORD_OVERRIDES_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}

    return data if isinstance(data, dict) else {}


def save_password_overrides(overrides):
    PASSWORD_OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with PASSWORD_OVERRIDES_PATH.open("w", encoding="utf-8") as f:
        json.dump(overrides, f, ensure_ascii=False, indent=2)


def append_password_audit(username):
    PASSWORD_AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    with PASSWORD_AUDIT_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(f"{timestamp}\t{username}\tPASSWORD_CHANGED\n")

def reset_user_password_override(username):
    username = (username or "").strip().lower()
    if not username:
        return False

    overrides = load_password_overrides()
    if username not in overrides:
        return False

    overrides.pop(username, None)
    save_password_overrides(overrides)

    PASSWORD_AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    with PASSWORD_AUDIT_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(f"{timestamp}\t{username}\tPASSWORD_RESET_TO_STAFF\n")

    return True


def verify_user_password(username, password, user_data=None):
    if not username or not password:
        return False

    username = username.strip().lower()
    user_data = user_data or get_users().get(username)
    if not user_data:
        return False

    overrides = load_password_overrides()
    hashed = overrides.get(username)
    if hashed:
        return check_password_hash(hashed, password)

    return user_data.get("password") == password


def update_user_password(username, new_password):
    username = username.strip().lower()
    overrides = load_password_overrides()
    overrides[username] = generate_password_hash(new_password)
    save_password_overrides(overrides)
    append_password_audit(username)


get_users(force_reload=True)

def find_col(headers, expected_name):
    expected = normalize(expected_name)
    for i, h in enumerate(headers):
        if expected in normalize(h):
            return i
    return None

def find_col_exact(headers, expected_name):
    for i, h in enumerate(headers):
        if h.strip().upper() == expected_name.upper():
            return i
    return None

def find_col_from_candidates(headers, candidates):
    for candidate in candidates:
        idx = find_col(headers, candidate)
        if idx is not None:
            return idx
    return None

def is_partner_branch_wide(user_info):
    return normalize((user_info or {}).get("partner", "")) == "BITEL"

def is_provincia_scope(selected_tab, user_info):
    if normalize(selected_tab) not in {normalize(t) for t in PROVINCIA_TABS}:
        return False

    return normalize((user_info or {}).get("branch", "")) in PROVINCIA_BRANCHES


def get_allowed_tabs(all_tabs, user_info):
    if not user_info or user_info.get("is_admin"):
        return all_tabs

    allowed_tabs = [tab for tab in (user_info.get("allowed_tabs") or []) if tab]
    if not allowed_tabs:
        return all_tabs


    normalized_all_tabs = {normalize_key(tab): tab for tab in all_tabs}
    available_keys = list(normalized_all_tabs.keys())

    resolved_tabs = []
    for raw_tab in allowed_tabs:
        requested_key = normalize_key(raw_tab)
        if not requested_key:
            continue

        exact = normalized_all_tabs.get(requested_key)
        if exact:
            if exact not in resolved_tabs:
                resolved_tabs.append(exact)
            continue

        close = difflib.get_close_matches(requested_key, available_keys, n=1, cutoff=0.82)
        if close:
            candidate = normalized_all_tabs[close[0]]
            if candidate not in resolved_tabs:
                resolved_tabs.append(candidate)

    return resolved_tabs

def has_unfiltered_tab_access(user_info, selected_tab):
    if not user_info or user_info.get("is_admin") or not selected_tab:
        return False

    normalized_unfiltered_tabs = {normalize(t) for t in UNFILTERED_ACCESS_TABS}
    if normalize(selected_tab) not in normalized_unfiltered_tabs:
        return False

    allowed_tabs = get_allowed_tabs([selected_tab], user_info)
    return selected_tab in allowed_tabs


def apply_user_access_filter(rows, headers, user_info, selected_tab=None):
    if not user_info or user_info.get("is_admin"):
        return rows

    if has_unfiltered_tab_access(user_info, selected_tab):
        return rows


    branch_idx = find_col_from_candidates(headers, ["BRANCH", "SITE"])
    partner_idx = find_col_from_candidates(headers, ["CONTRATA", "REPORTE DE CONTRATA", "PARTNER"])

    allowed_branch = normalize(user_info.get("branch", ""))
    allowed_partner = normalize(user_info.get("partner", ""))
    branch_wide_partner = is_partner_branch_wide(user_info)
    provincia_scope = is_provincia_scope(selected_tab, user_info)

    def has_access(row):
        branch_ok = True
        partner_ok = True

        if branch_idx is not None and allowed_branch and len(row) > branch_idx:
            branch_ok = normalize(row[branch_idx]) == allowed_branch

        if (
            not branch_wide_partner
            and partner_idx is not None
            and allowed_partner
            and len(row) > partner_idx
        ):
            partner_ok = normalize(row[partner_idx]) == allowed_partner
        if provincia_scope:
            return branch_ok and partner_ok


        return branch_ok and partner_ok

    return [r for r in rows if has_access(r)]


def get_session_user_info():
    username = session.get("user")
    if not username:
        return None

    user_info = get_users().get(username.lower())
    if not user_info:
        return None

    session["is_admin"] = user_info.get("is_admin", False)
    session["branch"] = user_info.get("branch", "")
    session["partner"] = user_info.get("partner", "")
    session["allowed_tabs"] = user_info.get("allowed_tabs", [])

    return user_info

def get_extra_filter_config(headers, selected_tab, user_info=None):
    tab_norm = normalize(selected_tab)
    is_admin = (user_info or {}).get("is_admin")
    if is_admin and tab_norm not in {
        normalize(DEPLOYMENT_TAB),
        normalize("FUERA DE GARANTÍA PROVINCIA"),
    }:
        return []

    bitel_partner = is_partner_branch_wide(user_info)
    filters = []

    if tab_norm == normalize("GARANTIAS LIMA"):
        if bitel_partner:
            contrata_idx = find_col(headers, "CONTRATA")
            if contrata_idx is not None:
                filters.append(("contrata_filter", "CONTRATA", contrata_idx))
        return filters

    if tab_norm == normalize(DEPLOYMENT_TAB):
        if (user_info or {}).get("is_admin"):
            contrata_idx = find_col(headers, "CONTRATA")
            if contrata_idx is not None:
                filters.append(("contrata_filter", "CONTRATA", contrata_idx))
            return filters

        site_idx = find_col(headers, "SITE")
        if site_idx is not None:
            filters.append(("site_filter", "SITE", site_idx))

        status_idx = find_col_from_candidates(headers, ["STATUS", "ESTADO", "STATUS DE LA CAJA"])
        if status_idx is not None:
            filters.append(("status_filter", "STATUS", status_idx))

        if bitel_partner:
            contrata_idx = find_col(headers, "CONTRATA")
            if contrata_idx is not None:
                filters.append(("contrata_filter", "CONTRATA", contrata_idx))
        return filters

    if tab_norm == normalize("PENDIENTES ODN"):
        site_idx = find_col(headers, "SITE")
        if site_idx is not None:
            filters.append(("site_filter", "SITE", site_idx))

        status_idx = find_col(headers, "STATUS DE LA CAJA")
        if status_idx is not None:
            filters.append(("status_caja_filter", "STATUS DE LA CAJA", status_idx))

        contrata_idx = find_col(headers, "CONTRATA")
        if contrata_idx is not None:
            filters.append(("contrata_filter", "CONTRATA", contrata_idx))
        return filters

    if tab_norm in {normalize(t) for t in UNFILTERED_PARTNER_TABS}:
        site_idx = find_col(headers, "SITE")
        if site_idx is not None:
            filters.append(("site_filter", "SITE", site_idx))

        reporte_idx = find_col(headers, "Reporte de Contrata")
        if reporte_idx is not None:
            filters.append(("reporte_contrata_filter", "Reporte de Contrata", reporte_idx))
        return filters

    if tab_norm == normalize("GARANTIAS PROVINCIA"):
        if bitel_partner:
            contrata_idx = find_col(headers, "CONTRATA")
            if contrata_idx is not None:
                filters.append(("contrata_filter", "CONTRATA", contrata_idx))
        return filters

    if tab_norm == normalize("FUERA DE GARANTÍA PROVINCIA"):
        site_idx = find_col(headers, "SITE")
        if site_idx is not None:
            filters.append(("site_filter", "SITE", site_idx))

    return filters

def can_apply_extra_filters(selected_tab, user_info=None):
    if not (user_info or {}).get("is_admin"):
        return True

    tab_norm = normalize(selected_tab)
    return tab_norm in {
        normalize(DEPLOYMENT_TAB),
        normalize("FUERA DE GARANTÍA PROVINCIA"),
    }

# ======================================================
# FUNCIÓN COMPARTIDA PARA FILTROS
# ======================================================
def get_filtered_data(selected_tab, selected_filter1="", selected_filter2="", user_info=None, extra_filters=None):
    sheet_client, _ = get_sheet_or_error()
    if sheet_client is None:
        return [], []

    ws = sheet_client.worksheet(selected_tab)

    data = ws.get_all_values()
    headers = data[0]
    rows_all = data[1:]
    rows_all = apply_user_access_filter(rows_all, headers, user_info, selected_tab=selected_tab)
    coord_idx, lat_idx, lng_idx = get_coord_indices(headers)

    if selected_tab == DEPLOYMENT_TAB:
        col1_name, col2_name = "BRANCH", "SITE"
        use_filter2 = True
    elif selected_tab in BRANCH_TABS:
        col1_name, col2_name = "BRANCH", "CONTRATA"
        use_filter2 = True
    elif selected_tab == SINGLE_BRANCH_TAB:
        col1_name, col2_name = "BRANCH", None
        use_filter2 = False
    else:
        col1_name, col2_name = "SITE", "Reporte de Contrata"
        use_filter2 = True

    col1_idx = find_col(headers, col1_name)
    col2_idx = find_col(headers, col2_name) if col2_name else None

    def matches(cell_value, filter_value):
        return normalize(cell_value) == normalize(filter_value)

    extra_filter_config = get_extra_filter_config(headers, selected_tab, user_info=user_info)
    should_apply_extra_filters = can_apply_extra_filters(selected_tab, user_info=user_info)

    filters1_values = set()
    filters2_values = set()
    extra_filter_option_values = {
        param_name: set() for param_name, _, _ in extra_filter_config
    }


    filtered_rows = [
        r for r in rows_after_f1
        if not (use_filter2 and col2_idx is not None and selected_filter2)
        or (len(r) > col2_idx and matches(r[col2_idx], selected_filter2))
    ]

    if extra_filters:
        extra_filter_config = get_extra_filter_config(headers, selected_tab, user_info=user_info)
        should_apply_extra_filters = can_apply_extra_filters(selected_tab, user_info=user_info)
        if should_apply_extra_filters:
            for param_name, _, col_idx in extra_filter_config:
                filter_value = (extra_filters.get(param_name) or "").strip()
                if not filter_value:
                    continue
                filtered_rows = [
                    r for r in filtered_rows
                    if len(r) > col_idx and matches(r[col_idx], filter_value)
                ]

    hidden_idxs = {i for i, h in enumerate(headers) if "LINK" in h.upper()}
    for idx in (coord_idx, lat_idx, lng_idx):
        if idx is not None:
            hidden_idxs.add(idx)

    visible_headers = [h for i, h in enumerate(headers) if i not in hidden_idxs]
    visible_rows = [
        [c for i, c in enumerate(r) if i not in hidden_idxs]
        for r in filtered_rows
    ]

    return visible_headers, visible_rows

@app.before_request
def refresh_staff_cache():
    get_users()


# =====================
# LOGIN ROUTES
# =====================
@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    success = "Contraseña actualizada correctamente. Inicia sesión con tu nueva contraseña." if request.args.get("changed") == "1" else None

    if request.method == "POST":
        username = normalize_username_input(request.form.get("username", ""))
        password = request.form.get("password", "").strip()
        user_data = get_users().get(username)

        if user_data and verify_user_password(username, password, user_data=user_data):
            session["user"] = username
            session["is_admin"] = user_data.get("is_admin", False)
            session["branch"] = user_data.get("branch", "")
            session["partner"] = user_data.get("partner", "")
            return redirect(url_for("index"))

        error = "Usuario o contraseña incorrectos"

    return render_template("login.html", error=error, success=success)



@app.route("/change_password", methods=["GET", "POST"])
def change_password():
    error = None

    if request.method == "POST":
        username = normalize_username_input(request.form.get("username", ""))
        old_password = request.form.get("old_password", "").strip()
        new_password = request.form.get("new_password", "").strip()
        repeat_new_password = request.form.get("repeat_new_password", "").strip()

        user_data = get_users().get(username)
        if not user_data:
            error = "Usuario no encontrado"
        elif not verify_user_password(username, old_password, user_data=user_data):
            error = "La contraseña antigua es incorrecta"
        elif not new_password:
            error = "La nueva contraseña no puede estar vacía"
        elif new_password != repeat_new_password:
            error = "Las contraseñas nuevas no coinciden"
        elif new_password == old_password:
            error = "La nueva contraseña debe ser distinta a la anterior"

        else:
            update_user_password(username, new_password)
            session.clear()
            return redirect(url_for("login", changed="1"))

    return render_template("change_password.html", error=error)

@app.route("/admin/reset_password", methods=["POST"])
def admin_reset_password():
    if "user" not in session:
        return redirect(url_for("login"))

    user_info = get_session_user_info()
    if not user_info or not user_info.get("is_admin"):
        return "No autorizado", 403

    username = normalize_username_input(request.form.get("username", ""))
    if not username:
        return redirect(url_for("index", reset_status="invalid"))

    target_user = get_users().get(username)
    if not target_user:
        return redirect(url_for("index", reset_status="not_found", reset_user=username))

    try:
        was_reset = reset_user_password_override(username)
    except Exception:
        return redirect(url_for("index", reset_status="error", reset_user=username))

    status = "done" if was_reset else "already_default"
    return redirect(url_for("index", reset_status=status, reset_user=username))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok"}), 200


@app.route("/api/updates_summary")
def updates_summary():
    if "user" not in session:
        return jsonify({"error": "unauthorized"}), 401

    summary = get_updates_summary_cached(force_refresh=False)
    return jsonify(summary)

@app.route("/internal/check_updates_notify", methods=["POST"])
def internal_check_updates_notify():
    token = request.headers.get("X-Scheduler-Token", "").strip()
    if not SCHEDULER_TOKEN or token != SCHEDULER_TOKEN:
        return jsonify({"error": "forbidden"}), 403

    result = check_and_send_update_notifications(force_refresh=True)
    return jsonify(result)



# =====================
# MAIN ROUTE
# =====================
@app.route("/")
def index():
    if "user" not in session:
        return redirect(url_for("login"))

    user_info = get_session_user_info()
    if not user_info:
        session.clear()
        return redirect(url_for("login"))

    sheet_client, sheet_error = get_sheet_or_error()
    if sheet_client is None:
        return f"Error de configuración de Google Sheets: {sheet_error}", 503

    try:
        tabs_all = [ws.title for ws in sheet_client.worksheets()]
    except APIError:
        return (
            "Google Sheets excedió la cuota de lectura temporalmente (429) al cargar pestañas. "
            "Vuelve a intentar en unos segundos.",
            503,
        )


    tabs = get_allowed_tabs(tabs_all, user_info)
    if not tabs:
        return "No tienes pestañas asignadas. Revisa columnas access_* en STAFF.xlsx (nombres de pestañas).", 403

    selected_tab = request.args.get("tab", tabs[0])
    if selected_tab not in tabs:
        selected_tab = tabs[0]
    last_tab = request.args.get("last_tab", "")
    selected_filter1 = request.args.get("filter1", "").strip()
    selected_filter2 = request.args.get("filter2", "").strip()
    extra_filters = {
        "site_filter": request.args.get("site_filter", "").strip(),
        "contrata_filter": request.args.get("contrata_filter", "").strip(),
        "reporte_contrata_filter": request.args.get("reporte_contrata_filter", "").strip(),
        "status_caja_filter": request.args.get("status_caja_filter", "").strip(),
        "status_filter": request.args.get("status_filter", "").strip(),
    }

    reset_status = request.args.get("reset_status", "").strip()
    reset_user = request.args.get("reset_user", "").strip()
    
    reset_feedback_messages = {
        "done": f"Reset OK: {reset_user}. Ahora usa la contraseña de STAFF.xlsx",
        "already_default": f"{reset_user} ya estaba usando la contraseña de STAFF.xlsx",
        "not_found": f"Usuario no encontrado: {reset_user}",
        "invalid": "Usuario inválido para reset",
        "error": f"No se pudo completar el reset de {reset_user}. Revisa logs del servidor.",
    }
    reset_feedback = reset_feedback_messages.get(reset_status)

    if not user_info.get("is_admin"):
        if has_unfiltered_tab_access(user_info, selected_tab):
            selected_filter1 = ""
            selected_filter2 = ""
        else:
            selected_filter1 = user_info.get("branch", "")
            if selected_tab == DEPLOYMENT_TAB:
                selected_filter2 = ""
            else:
                selected_filter2 = "" if is_partner_branch_wide(user_info) else user_info.get("partner", "")


    elif last_tab != selected_tab:
        selected_filter1 = ""
        selected_filter2 = ""


    try:
        ws = sheet_client.worksheet(selected_tab)
    except APIError:
        return (
            "Google Sheets excedió la cuota de lectura temporalmente (429) al abrir la pestaña. "
            "Vuelve a intentar en unos segundos.",
            503,
        )

    try:
        data = ws.get_all_values()
    except APIError:
        return (
            "Google Sheets excedió la cuota de lectura temporalmente (429). "
            "Vuelve a intentar en unos segundos.",
            503,
        )
    headers = data[0]
    rows_all = data[1:]
    data = None
    rows_all = apply_user_access_filter(rows_all, headers, user_info, selected_tab=selected_tab)
    total_rows = len(rows_all)

    coord_idx, lat_idx, lng_idx = get_coord_indices(headers)
    caja_idx = find_col_exact(headers, "CAJA")
    cuenta_idx = find_col(headers, "CUENTA")
    status_idx = find_col_from_candidates(headers, ["STATUS", "ESTADO", "STATUS DE LA CAJA"])

    # ================= FILTROS =================
    if selected_tab == DEPLOYMENT_TAB:
        col1_name, col2_name = "BRANCH", "SITE"
        use_filter2 = True
    elif selected_tab in BRANCH_TABS:
        col1_name, col2_name = "BRANCH", "CONTRATA"
        use_filter2 = True
    elif selected_tab == SINGLE_BRANCH_TAB:
        col1_name, col2_name = "BRANCH", None
        use_filter2 = False
    else:
        col1_name, col2_name = "SITE", "Reporte de Contrata"
        use_filter2 = True

    col1_idx = find_col(headers, col1_name)
    col2_idx = find_col(headers, col2_name) if col2_name else None

    def matches(cell_value, filter_value):
        return normalize(cell_value) == normalize(filter_value)


    extra_filter_config = get_extra_filter_config(headers, selected_tab, user_info=user_info)
    should_apply_extra_filters = can_apply_extra_filters(selected_tab, user_info=user_info)

    filters1_values = set()
    filters2_values = set()
    extra_filter_option_values = {
        param_name: set() for param_name, _, _ in extra_filter_config
    }



    filtered_rows = []
    for r in rows_all:
        if col1_idx is not None and len(r) > col1_idx and r[col1_idx].strip():
            filters1_values.add(r[col1_idx])

        passes_filter1 = (
            col1_idx is None
            or (
                len(r) > col1_idx
                and (not selected_filter1 or matches(r[col1_idx], selected_filter1))
            )
        )
        if not passes_filter1:
            continue

        if use_filter2 and col2_idx is not None and len(r) > col2_idx and r[col2_idx].strip():
            filters2_values.add(r[col2_idx])

        if should_apply_extra_filters:
            for param_name, _, col_idx in extra_filter_config:
                if len(r) > col_idx and r[col_idx].strip():
                    extra_filter_option_values[param_name].add(r[col_idx])

        passes_filter2 = not (

            use_filter2
            and col2_idx is not None
            and selected_filter2
            and len(r) > col2_idx
            and not matches(r[col2_idx], selected_filter2)
        )
        if not passes_filter2:
            continue

        passes_extra_filters = True
        if should_apply_extra_filters:
            for param_name, _, col_idx in extra_filter_config:
                filter_value = extra_filters.get(param_name, "")
                if not filter_value:
                    continue
                if len(r) <= col_idx or not matches(r[col_idx], filter_value):
                    passes_extra_filters = False
                    break

        if passes_extra_filters:
            filtered_rows.append(r)


    extra_filter_options = []
    if should_apply_extra_filters:
        for param_name, label, _ in extra_filter_config:
            options = sorted(extra_filter_option_values.get(param_name, set()))

            if selected_tab == DEPLOYMENT_TAB and param_name == "contrata_filter" and len(options) <= 1:
                continue
            extra_filter_options.append({
                "name": param_name,
                "label": label,
                "selected": extra_filters.get(param_name, ""),
                "options": options,
            })

    filters1 = sorted(filters1_values)
    filters2 = sorted(filters2_values)


    # ================= MAPA =================
    coords_info = []
    show_map_column = (coord_idx is not None or (lat_idx is not None and lng_idx is not None)) and selected_tab not in ["CANCELADOS", SINGLE_BRANCH_TAB]

    if selected_tab == "PENDIENTES ODN" or selected_tab in STATUS_FROM_ODN_TABS:
        ensure_estado_cajas_fresh()



    if show_map_column:
        cajas_map = {}

        for r in filtered_rows:
            try:
                coords = get_row_lat_lng(r, coord_idx=coord_idx, lat_idx=lat_idx, lng_idx=lng_idx)
                if not coords:
                    continue
                lat, lng = coords
                caja = r[caja_idx].strip().upper() if caja_idx is not None and len(r) > caja_idx and r[caja_idx] else ""
                cuenta = r[cuenta_idx] if cuenta_idx is not None and len(r) > cuenta_idx else ""


                marker_key = caja or f"SIN_CAJA_{lat:.6f}_{lng:.6f}"


                if marker_key not in cajas_map:
                    cajas_map[marker_key] = {
                        "lat": lat,
                        "lng": lng,
                        "caja": caja or "SIN CAJA",
                        "clientes": set(),
                        "status": ""
                    }

                    if selected_tab == DEPLOYMENT_TAB and status_idx is not None and len(r) > status_idx:
                        cajas_map[marker_key]["status"] = r[status_idx].strip()
                    elif selected_tab == "PENDIENTES ODN" or selected_tab in STATUS_FROM_ODN_TABS:
                        estado = estado_cajas.get(caja, "").strip() if caja else ""
                        cajas_map[marker_key]["status"] = estado if estado else "SIN ESTADO"

                if cuenta:
                    cajas_map[marker_key]["clientes"].add(cuenta)

            except:
                pass

        for c in cajas_map.values():
            coords_info.append({
                "lat": c["lat"],
                "lng": c["lng"],
                "caja": c["caja"],
                "clientes": sorted(list(c["clientes"])),
                "status": c["status"],
            })

    # ================= TABLA =================
    hidden_idxs = {i for i, h in enumerate(headers) if "LINK" in h.upper()}
    for idx in (coord_idx, lat_idx, lng_idx):
        if idx is not None:
            hidden_idxs.add(idx)

    visible_headers = [h for i, h in enumerate(headers) if i not in hidden_idxs]

    rows_with_links = []
    for r in filtered_rows:
        visible_row = [c for i, c in enumerate(r) if i not in hidden_idxs]
        coords = get_row_lat_lng(r, coord_idx=coord_idx, lat_idx=lat_idx, lng_idx=lng_idx)
        link = f"https://www.google.com/maps?q={coords[0]},{coords[1]}" if coords else None
        rows_with_links.append((visible_row, link))
    update_summary = get_updates_summary_cached()

    return render_template(
        "index.html",
        tabs=tabs,
        selected_tab=selected_tab,
        last_tab=selected_tab,
        headers=visible_headers,
        rows_with_links=rows_with_links,
        filters1=filters1,
        filters2=filters2,
        selected_filter1=selected_filter1,
        selected_filter2=selected_filter2,
        total_rows=total_rows,
        filtered_count=len(filtered_rows),
        coords_info=coords_info,
        has_coords=show_map_column,
        is_branch_tab=selected_tab in BRANCH_TABS or selected_tab == SINGLE_BRANCH_TAB,
        show_map_column=show_map_column,
        use_filter2=use_filter2,
        extra_filter_options=extra_filter_options,
        estado_cajas=estado_cajas,
        user_info=user_info,
        reset_feedback=reset_feedback,
        reset_status=reset_status,
        is_deployment_tab=selected_tab == DEPLOYMENT_TAB,
        update_summary=update_summary,
        user_scope_label=(
            "FBB"
            if user_info.get("is_admin")
            else f"{(user_info.get('branch') or 'N/A')} - {(user_info.get('partner') or 'N/A')}"
        ),
    )


# ======================================================
# EXPORT EXCEL (CORREGIDO – USA XLSXWRITER)
# ======================================================

@app.route("/port_validation", methods=["GET", "POST"])
def port_validation():
    if "user" not in session:
        return redirect(url_for("login"))

    user_info = get_session_user_info()
    if not user_info:
        session.clear()
        return redirect(url_for("login"))

    state = session.get(PORT_VALIDATION_STATE_KEY, {})
    site = request.values.get("site", state.get("site", "")).strip()
    box = request.values.get("box", state.get("box", "")).strip()

    raw_olt = request.values.get("olt", state.get("olt", str(PORT_VALIDATION_OLTS[0]))).strip()
    try:
        olt = int(raw_olt)
    except Exception:
        olt = PORT_VALIDATION_OLTS[0]

    action = request.values.get("action", "")

    error = None
    info = None
    infra_value = generar_infra(site, olt, box)
    infra_table = None
    estado_table = pd.DataFrame(state.get("estado_table", [])) if state.get("estado_table") else None
    diferencias_table = None

    spreadsheet = None
    spreadsheet_error = None

    if action in {"consultar_infra", "consultar_estado", "comparar"}:
        spreadsheet, spreadsheet_error = open_port_validation_spreadsheet_or_error()
        if spreadsheet is None:
            error = f"Error de configuración de Google Sheets (validación): {spreadsheet_error}"

    if action in {"consultar_infra", "consultar_estado", "comparar"} and not error:
        if not site or not box:
            error = "Completa SITE / OLT / BOX."
        elif action in {"consultar_estado", "comparar"} and olt not in PORT_VALIDATION_VALID_OLTS:
            error = "OLT inválido para consulta de estado (permitidos: 1, 2, 11)."

    if action == "consultar_infra" and not error:

        try:
            df_nims = worksheet_to_dataframe(spreadsheet, "NIMS")
        except Exception as exc:
            df_nims = pd.DataFrame()
            error = f"No se pudo leer hoja NIMS: {exc}"

        if not error:
            if df_nims.empty or df_nims.shape[1] < 9:
                error = "La hoja NIMS no tiene columnas suficientes para consulta INFRA."
            else:
                filtro = df_nims.iloc[:, 8].astype(str).str.contains(infra_value, case=False, na=False)
                df_filtrado = df_nims[filtro]
                if df_filtrado.empty:
                    info = "No se encontraron coincidencias en NIMS."
                else:
                    wanted_idxs = [0, 1, 10, 19, 4, 7, 8]
                    existing_idxs = [idx for idx in wanted_idxs if idx < df_nims.shape[1]]
                    infra_table = df_filtrado.iloc[:, existing_idxs].copy().fillna("")
                    if len(existing_idxs) > 2:
                        original_col = infra_table.columns[2]
                        infra_table.rename(columns={original_col: "Puerto BOX"}, inplace=True)

    if action in {"consultar_estado", "comparar"} and not error:
        try:
            df_tms = worksheet_to_dataframe(spreadsheet, "TMs")
        except Exception as exc:
            df_tms = pd.DataFrame()
            error = f"No se pudo leer hoja TMs: {exc}"

        if not error and action == "consultar_estado":
            estado_resultado, estado_error = obtener_resultado_estado(df_tms, site, olt, box)
            if estado_error:
                error = estado_error
            elif estado_resultado is None or estado_resultado.empty:
                info = "No hay coincidencias para el PORT calculado."
                estado_table = pd.DataFrame()
            else:
                estado_table = estado_resultado.fillna("")
                state["referencia_table"] = estado_table.to_dict(orient="records")

        if not error and action == "comparar":
            referencia = pd.DataFrame(state.get("referencia_table", []))
            if referencia.empty:
                error = "Primero ejecuta 'Consultar ESTADO' para tener referencia."
            else:
                estado_resultado, estado_error = obtener_resultado_estado(df_tms, site, olt, box)
                if estado_error:
                    error = estado_error
                elif estado_resultado is None or estado_resultado.empty:
                    info = "No hay coincidencias actuales para comparar."
                    estado_table = pd.DataFrame()
                else:
                    estado_table = estado_resultado.fillna("")
                    diferencias_table = calcular_diferencias(referencia, estado_table)
                    if diferencias_table.empty:
                        info = "No se encontraron diferencias."

    state.update({
        "site": site,
        "box": box,
        "olt": str(olt),
        "estado_table": (estado_table.fillna("").to_dict(orient="records") if isinstance(estado_table, pd.DataFrame) else []),
    })
    session[PORT_VALIDATION_STATE_KEY] = state

    def to_table_payload(df):
        if df is None or df.empty:
            return None
        return {
            "headers": [str(c) for c in df.columns],
            "rows": [[str(v) for v in row] for row in df.fillna("").values.tolist()],
        }

    return render_template(
        "port_validation.html",
        user_info=user_info,
        site=site,
        box=box,
        olt=olt,
        olt_options=PORT_VALIDATION_OLTS,
        infra_value=infra_value,
        infra_table=to_table_payload(infra_table),
        estado_table=to_table_payload(estado_table),
        diferencias_table=to_table_payload(diferencias_table),
        error_message=error,
        info_message=info,
    )


@app.route("/export_excel")
def export_excel():
    if "user" not in session:
        return redirect(url_for("login"))

    tab = request.args.get("tab")
    filter1 = request.args.get("filter1", "")
    filter2 = request.args.get("filter2", "")
    extra_filters = {
        "site_filter": request.args.get("site_filter", "").strip(),
        "contrata_filter": request.args.get("contrata_filter", "").strip(),
        "reporte_contrata_filter": request.args.get("reporte_contrata_filter", "").strip(),
        "status_caja_filter": request.args.get("status_caja_filter", "").strip(),
        "status_filter": request.args.get("status_filter", "").strip(),
    }

    user_info = get_session_user_info()
    if not user_info:
        session.clear()
        return redirect(url_for("login"))

    sheet_client, sheet_error = get_sheet_or_error()
    if sheet_client is None:
        return f"Error de configuración de Google Sheets: {sheet_error}", 503

    allowed_tabs = get_allowed_tabs([ws.title for ws in sheet_client.worksheets()], user_info)

    if tab not in allowed_tabs:
        return redirect(url_for("index"))

    if not user_info.get("is_admin"):
        if has_unfiltered_tab_access(user_info, tab):
            filter1 = ""
            filter2 = ""
        else:
            filter1 = user_info.get("branch", "")
            if tab == DEPLOYMENT_TAB:
                filter2 = ""
            else:
                filter2 = "" if is_partner_branch_wide(user_info) else user_info.get("partner", "")

    headers, rows = get_filtered_data(tab, filter1, filter2, user_info=user_info, extra_filters=extra_filters)

    df = pd.DataFrame(rows, columns=headers)

    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name=tab[:31])

    output.seek(0)

    filename = f"{tab.replace(' ', '_')}.xlsx"

    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


# =====================
# DOWNLOAD EXCEL (ORIGINAL)
# =====================
@app.route("/download_excel")
def download_excel():
    if "user" not in session:
        return redirect(url_for("login"))

    selected_tab = request.args.get("tab")
    selected_filter1 = request.args.get("filter1", "").strip()
    selected_filter2 = request.args.get("filter2", "").strip()
    extra_filters = {
        "site_filter": request.args.get("site_filter", "").strip(),
        "contrata_filter": request.args.get("contrata_filter", "").strip(),
        "reporte_contrata_filter": request.args.get("reporte_contrata_filter", "").strip(),
    }

    user_info = get_session_user_info()
    if not user_info:
        session.clear()
        return redirect(url_for("login"))


    sheet_client, sheet_error = get_sheet_or_error()
    if sheet_client is None:
        return f"Error de configuración de Google Sheets: {sheet_error}", 503

    allowed_tabs = get_allowed_tabs([ws.title for ws in sheet_client.worksheets()], user_info)

    if selected_tab not in allowed_tabs:
        return redirect(url_for("index"))

    if not user_info.get("is_admin"):
        if has_unfiltered_tab_access(user_info, selected_tab):
            selected_filter1 = ""
            selected_filter2 = ""
        else:
            selected_filter1 = user_info.get("branch", "")
            if selected_tab == DEPLOYMENT_TAB:
                selected_filter2 = ""
            else:
                selected_filter2 = "" if is_partner_branch_wide(user_info) else user_info.get("partner", "")


    ws = sheet_client.worksheet(selected_tab)
    data = ws.get_all_values()
    headers = data[0]
    rows_all = data[1:]
    rows_all = apply_user_access_filter(rows_all, headers, user_info, selected_tab=selected_tab)

    coord_idx, lat_idx, lng_idx = get_coord_indices(headers)

    if selected_tab == DEPLOYMENT_TAB:
        col1_name, col2_name = "BRANCH", "SITE"
        use_filter2 = True
    elif selected_tab in BRANCH_TABS:
        col1_name, col2_name = "BRANCH", "CONTRATA"
        use_filter2 = True
    elif selected_tab == SINGLE_BRANCH_TAB:
        col1_name, col2_name = "BRANCH", None
        use_filter2 = False
    else:
        col1_name, col2_name = "SITE", "Reporte de Contrata"
        use_filter2 = True

    col1_idx = find_col(headers, col1_name)
    col2_idx = find_col(headers, col2_name) if col2_name else None

    def matches(cell_value, filter_value):
        return normalize(cell_value) == normalize(filter_value)

    if col1_idx is None:
        rows_after_f1 = rows_all
    else:
        rows_after_f1 = [
            r for r in rows_all
            if len(r) > col1_idx
            and (not selected_filter1 or matches(r[col1_idx], selected_filter1))
        ]

    filtered_rows = [
        r for r in rows_after_f1
        if not (use_filter2 and col2_idx is not None and selected_filter2)
        or (len(r) > col2_idx and matches(r[col2_idx], selected_filter2))    ]
    should_apply_extra_filters = can_apply_extra_filters(selected_tab, user_info=user_info)
    if should_apply_extra_filters:
        extra_filter_config = get_extra_filter_config(headers, selected_tab, user_info=user_info)
        for param_name, _, col_idx in extra_filter_config:
            filter_value = extra_filters.get(param_name, "")
            if not filter_value:
                continue
            filtered_rows = [
                r for r in filtered_rows
                if len(r) > col_idx and matches(r[col_idx], filter_value)
            ]


    hidden_idxs = {i for i, h in enumerate(headers) if "LINK" in h.upper()}
    for idx in (coord_idx, lat_idx, lng_idx):
        if idx is not None:
            hidden_idxs.add(idx)

    visible_headers = [h for i, h in enumerate(headers) if i not in hidden_idxs]
    visible_rows = [
        [c for i, c in enumerate(r) if i not in hidden_idxs]
        for r in filtered_rows
    ]

    df = pd.DataFrame(visible_rows, columns=visible_headers)

    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Datos")

    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name=f"{selected_tab}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )



if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
