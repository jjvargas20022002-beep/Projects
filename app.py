from flask import Flask, render_template, request, redirect, url_for, session, send_file
import gspread
from google.oauth2.service_account import Credentials
import os
import pandas as pd
from io import BytesIO
from pathlib import Path
import difflib
import unicodedata


app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "secret_key_temporal")

# =====================
# GOOGLE SHEETS CONFIG
# =====================
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

creds = Credentials.from_service_account_info(
    {
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
    },
    scopes=SCOPES,
)

gc = gspread.authorize(creds)
sheet = gc.open_by_key(os.environ["SPREADSHEET_ID"])

# =====================
# ESTADO DE CAJAS DESDE PENDIENTES ODN
# =====================
estado_cajas = {}

try:
    ws_odn = sheet.worksheet("PENDIENTES ODN")
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
except:
    estado_cajas = {}

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


# =====================
# LOGIN DESDE STAFF.xlsx
# =====================
STAFF_PATH = Path(os.environ.get("STAFF_FILE_PATH", Path(__file__).resolve().parent / "STAFF.xlsx"))
ADMIN_USERS = {
    username.strip().lower()
    for username in os.environ.get("ADMIN_USERS", "").split(",")
    if username.strip()
}

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

def normalize(text):
    return "".join(text.upper().split()) if text else ""

def normalize_key(text):
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", str(text))
    without_accents = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return "".join(ch for ch in without_accents.upper() if ch.isalnum())


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

    def has_access(row):
        branch_ok = True
        partner_ok = True

        if branch_idx is not None and allowed_branch and len(row) > branch_idx:
            branch_ok = normalize(row[branch_idx]) == allowed_branch

        if not branch_wide_partner and partner_idx is not None and allowed_partner and len(row) > partner_idx:
            partner_ok = normalize(row[partner_idx]) == allowed_partner

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

# ======================================================
# FUNCIÓN COMPARTIDA PARA FILTROS
# ======================================================
def get_filtered_data(selected_tab, selected_filter1="", selected_filter2="", user_info=None):
    ws = sheet.worksheet(selected_tab)
    data = ws.get_all_values()
    headers = data[0]
    rows_all = data[1:]
    rows_all = apply_user_access_filter(rows_all, headers, user_info, selected_tab=selected_tab)
    coord_idx = find_col(headers, "COORDENADAS")

    if selected_tab in BRANCH_TABS:
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

    rows_after_f1 = [
        r for r in rows_all
        if col1_idx is not None
        and len(r) > col1_idx
        and (not selected_filter1 or matches(r[col1_idx], selected_filter1))

    ]

    filtered_rows = [
        r for r in rows_after_f1
        if not (use_filter2 and col2_idx is not None and selected_filter2)
        or (len(r) > col2_idx and matches(r[col2_idx], selected_filter2))
    ]

    hidden_idxs = {i for i, h in enumerate(headers) if "LINK" in h.upper()}
    if coord_idx is not None:
        hidden_idxs.add(coord_idx)

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
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "").strip()
        user_data = get_users().get(username)
        if user_data and user_data.get("password") == password:
            session["user"] = username
            session["is_admin"] = user_data.get("is_admin", False)
            session["branch"] = user_data.get("branch", "")
            session["partner"] = user_data.get("partner", "")
            return redirect(url_for("index"))
        else:
            error = "Usuario o contraseña incorrectos"
    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

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

    tabs_all = [ws.title for ws in sheet.worksheets()]
    tabs = get_allowed_tabs(tabs_all, user_info)
    if not tabs:
        return "No tienes pestañas asignadas. Revisa columnas access_* en STAFF.xlsx (nombres de pestañas).", 403

    selected_tab = request.args.get("tab", tabs[0])
    if selected_tab not in tabs:
        selected_tab = tabs[0]
    last_tab = request.args.get("last_tab", "")
    selected_filter1 = request.args.get("filter1", "").strip()
    selected_filter2 = request.args.get("filter2", "").strip()

    if not user_info.get("is_admin"):
        if has_unfiltered_tab_access(user_info, selected_tab):
            selected_filter1 = ""
            selected_filter2 = ""
        else:
            selected_filter1 = user_info.get("branch", "")
            selected_filter2 = "" if is_partner_branch_wide(user_info) else user_info.get("partner", "")

    elif last_tab != selected_tab:
        selected_filter1 = ""
        selected_filter2 = ""

    ws = sheet.worksheet(selected_tab)
    data = ws.get_all_values()
    headers = data[0]
    rows_all = data[1:]
    rows_all = apply_user_access_filter(rows_all, headers, user_info, selected_tab=selected_tab)
    total_rows = len(rows_all)

    coord_idx = find_col(headers, "COORDENADAS")
    caja_idx = find_col_exact(headers, "CAJA")
    cuenta_idx = find_col(headers, "CUENTA")

    # ================= FILTROS =================
    if selected_tab in BRANCH_TABS:
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

    rows_after_f1 = [
        r for r in rows_all
        if col1_idx is not None
        and len(r) > col1_idx
        and (not selected_filter1 or matches(r[col1_idx], selected_filter1))
    ]

    filtered_rows = [
        r for r in rows_after_f1
        if not (
            use_filter2
            and col2_idx is not None
            and selected_filter2
            and len(r) > col2_idx
            and not matches(r[col2_idx], selected_filter2)
        )
    ]

    filters1 = sorted({
        r[col1_idx]
        for r in rows_all
        if col1_idx is not None and len(r) > col1_idx and r[col1_idx].strip()
    })

    filters2 = sorted({
        r[col2_idx]
        for r in rows_after_f1
        if use_filter2 and col2_idx is not None and len(r) > col2_idx and r[col2_idx].strip()
    })

    # ================= MAPA =================
    coords_info = []
    show_map_column = coord_idx is not None and selected_tab not in ["CANCELADOS", SINGLE_BRANCH_TAB]

    if show_map_column:
        cajas_map = {}

        for r in filtered_rows:
            try:
                lat, lng = map(float, r[coord_idx].replace(" ", "").split(",", 1))
                caja = r[caja_idx].strip().upper() if caja_idx is not None and r[caja_idx] else ""
                cuenta = r[cuenta_idx] if cuenta_idx is not None else ""

                if not caja:
                    continue

                if caja not in cajas_map:
                    cajas_map[caja] = {
                        "lat": lat,
                        "lng": lng,
                        "caja": caja,
                        "clientes": set(),
                        "status": ""
                    }

                    if selected_tab == "PENDIENTES ODN" or selected_tab in STATUS_FROM_ODN_TABS:
                        estado = estado_cajas.get(caja, "").strip()
                        cajas_map[caja]["status"] = estado if estado else "SIN ESTADO"

                if cuenta:
                    cajas_map[caja]["clientes"].add(cuenta)

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
    if coord_idx is not None:
        hidden_idxs.add(coord_idx)

    visible_headers = [h for i, h in enumerate(headers) if i not in hidden_idxs]

    rows_with_links = []
    for r in filtered_rows:
        visible_row = [c for i, c in enumerate(r) if i not in hidden_idxs]
        link = coord_to_link(r[coord_idx]) if coord_idx is not None else None
        rows_with_links.append((visible_row, link))

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
        estado_cajas=estado_cajas,
        user_info=user_info,
    )


# ======================================================
# EXPORT EXCEL (CORREGIDO – USA XLSXWRITER)
# ======================================================
@app.route("/export_excel")
def export_excel():
    if "user" not in session:
        return redirect(url_for("login"))

    tab = request.args.get("tab")
    filter1 = request.args.get("filter1", "")
    filter2 = request.args.get("filter2", "")
    user_info = get_session_user_info()
    if not user_info:
        session.clear()
        return redirect(url_for("login"))

    allowed_tabs = get_allowed_tabs([ws.title for ws in sheet.worksheets()], user_info)
    if tab not in allowed_tabs:
        return redirect(url_for("index"))

    if not user_info.get("is_admin"):
        if has_unfiltered_tab_access(user_info, tab):
            filter1 = ""
            filter2 = ""
        else:
            filter1 = user_info.get("branch", "")
            filter2 = "" if is_partner_branch_wide(user_info) else user_info.get("partner", "")


    headers, rows = get_filtered_data(tab, filter1, filter2, user_info=user_info)

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
    user_info = get_session_user_info()
    if not user_info:
        session.clear()
        return redirect(url_for("login"))

    allowed_tabs = get_allowed_tabs([ws.title for ws in sheet.worksheets()], user_info)
    if selected_tab not in allowed_tabs:
        return redirect(url_for("index"))

    if not user_info.get("is_admin"):
        if has_unfiltered_tab_access(user_info, selected_tab):
            selected_filter1 = ""
            selected_filter2 = ""
        else:
            selected_filter1 = user_info.get("branch", "")
            selected_filter2 = "" if is_partner_branch_wide(user_info) else user_info.get("partner", "")


    ws = sheet.worksheet(selected_tab)
    data = ws.get_all_values()
    headers = data[0]
    rows_all = data[1:]
    rows_all = apply_user_access_filter(rows_all, headers, user_info, selected_tab=selected_tab)

    coord_idx = find_col(headers, "COORDENADAS")

    if selected_tab in BRANCH_TABS:
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

    rows_after_f1 = [
        r for r in rows_all
        if col1_idx is not None
        and len(r) > col1_idx
        and (not selected_filter1 or matches(r[col1_idx], selected_filter1))
    ]

    filtered_rows = [
        r for r in rows_after_f1
        if not (use_filter2 and col2_idx is not None and selected_filter2)
        or (len(r) > col2_idx and matches(r[col2_idx], selected_filter2))    ]

    hidden_idxs = {i for i, h in enumerate(headers) if "LINK" in h.upper()}
    if coord_idx is not None:
        hidden_idxs.add(coord_idx)

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
