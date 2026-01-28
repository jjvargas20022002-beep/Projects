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

EXTRA_FILTER_TABS = [
    "LI1 TGI",
    "LI2 DIJUSA",
    "LI2 ERAM",
    "LI3 INTER",
    "LI4 TGI",
    "LI4 SMP",
    "LI7 MARCOS",
    "LI4 BROKERS",
]

@app.route("/")
def index():
    # 🔒 TAB seguro
    selected_tab = request.args.get("tab")
    if not selected_tab or selected_tab not in SHEETS:
        selected_tab = list(SHEETS.keys())[0]

    gid = SHEETS[selected_tab]

    url = (
        f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}"
        f"/export?format=csv&gid={gid}"
    )

    df = pd.read_csv(url)
    df.columns = df.columns.str.strip()

    # 📍 Google Maps desde "Coordenadas"
    if "Coordenadas" in df.columns:
        df["MAP_LINK"] = df["Coordenadas"].apply(
            lambda x: f"https://www.google.com/maps?q={x}"
            if pd.notna(x) and "," in str(x)
            else ""
        )
        df = df.drop(columns=["Coordenadas"])
    else:
        df["MAP_LINK"] = ""

    show_extra_filters = selected_tab in EXTRA_FILTER_TABS

    selected_site = request.args.get("site", "")
    selected_reporte = request.args.get("reporte", "")

    # 🔽 Filtros dinámicos
    if show_extra_filters:
        if "SITE" in df.columns:
            sites = sorted(df["SITE"].dropna().unique())
            if selected_site:
                df = df[df["SITE"] == selected_site]
        else:
            sites = []

        if "Reporte de Contrata" in df.columns:
            reportes = sorted(df["Reporte de Contrata"].dropna().unique())
            if selected_reporte:
                df = df[df["Reporte de Contrata"] == selected_reporte]
        else:
            reportes = []
    else:
        sites = []
        reportes = []

    headers = list(df.columns)
    rows = df.to_dict("records")

    return render_template(
        "index.html",
        tabs=list(SHEETS.keys()),
        selected_tab=selected_tab,
        headers=headers,
        rows=rows,
        show_extra_filters=show_extra_filters,
        sites=sites,
        reportes=reportes,
        selected_site=selected_site,
        selected_reporte=selected_reporte,
    )

if __name__ == "__main__":
    app.run(debug=True)