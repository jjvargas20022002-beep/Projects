from flask import Flask, render_template, request
import pandas as pd

app = Flask(__name__)

SPREADSHEET_ID = "1eaNxCpm8JF1JcZS3_ldwMRINGYFaW6RsQQWybvRi_P8"

SHEETS = {
    "LI1 TGI": "36214359",
    "LI2 DIJUSA": "123456789",
    "LI2 ERAM": "234567891",
    "LI3 INTER": "345678912",
    "LI4 TGI": "456789123",
    "LI4 SMP": "567891234",
    "LI7 MARCOS": "678912345",
    "LI4 BROKERS": "789123456",
    "CANCELADOS": "891234567",
    "ONLINE LIMA": "912345678"
}

FILTER_TABS = [
    "LI1 TGI",
    "LI2 DIJUSA",
    "LI2 ERAM",
    "LI3 INTER",
    "LI4 TGI",
    "LI4 SMP",
    "LI7 MARCOS",
    "LI4 BROKERS"
]

@app.route("/")
def index():
    selected_tab = request.args.get("tab", list(SHEETS.keys())[0])
    site_filter = request.args.get("site", "")
    reporte_filter = request.args.get("reporte", "")

    gid = SHEETS.get(selected_tab)
    csv_url = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=csv&gid={gid}"

    df = pd.read_csv(csv_url)

    # Limpiar encabezados
    df.columns = df.columns.str.strip()

    # Detectar columnas reales
    has_coords = "Coordenadas" in df.columns
    has_site = "SITE" in df.columns
    has_reporte = "Reporte de Contrata" in df.columns

    # Filtros SOLO si existen
    if selected_tab in FILTER_TABS:
        if has_site and site_filter:
            df = df[df["SITE"] == site_filter]
        if has_reporte and reporte_filter:
            df = df[df["Reporte de Contrata"] == reporte_filter]

    # Opciones de filtros
    sites = sorted(df["SITE"].dropna().unique()) if has_site else []
    reportes = sorted(df["Reporte de Contrata"].dropna().unique()) if has_reporte else []

    # MAPA
    if has_coords:
        def build_map(coord):
            if isinstance(coord, str) and "," in coord:
                lat, lon = coord.split(",")
                return f"https://www.google.com/maps?q={lat.strip()},{lon.strip()}"
            return None

        df["MAP_LINK"] = df["Coordenadas"].apply(build_map)
    else:
        df["MAP_LINK"] = None

    headers = [c for c in df.columns if c != "Coordenadas" and c != "MAP_LINK"]

    return render_template(
        "index.html",
        tabs=SHEETS.keys(),
        selected_tab=selected_tab,
        headers=headers,
        rows=df.to_dict(orient="records"),
        show_extra_filters=selected_tab in FILTER_TABS,
        sites=sites,
        reportes=reportes,
        selected_site=site_filter,
        selected_reporte=reporte_filter
    )

if __name__ == "__main__":
    app.run(debug=True)