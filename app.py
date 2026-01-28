from flask import Flask, render_template
import pandas as pd

app = Flask(__name__)

TABS_SITE_ONLY = {
    "LI1 TGI",
    "LI2 DIJUSA",
    "LI2 ERAM",
    "LI3 INTER",
    "LI4 TGI",
    "LI4 SMP",
    "LI7 MARCOS",
    "LI4 BROKERS"
}

@app.route("/")
def index():
    df = pd.read_csv("data.csv")

    # 🔒 Asegurar columnas mínimas
    for col in ["TAB", "SITE", "BRANCH", "CONTRATA", "LATITUDE", "LONGITUDE"]:
        if col not in df.columns:
            df[col] = ""

    # 🔗 Google Maps
    df["MAP_LINK"] = df.apply(
        lambda r: f"https://www.google.com/maps?q={r['LATITUDE']},{r['LONGITUDE']}"
        if pd.notna(r["LATITUDE"]) and pd.notna(r["LONGITUDE"]) and str(r["LATITUDE"]).strip() != ""
        else "",
        axis=1
    )

    tabs = sorted(df["TAB"].dropna().unique())

    data = {}

    for tab in tabs:
        tab_df = df[df["TAB"] == tab]

        # 👉 SOLO SITE
        if tab in TABS_SITE_ONLY:
            grouped = {
                "SITE": {
                    site: tab_df[tab_df["SITE"] == site].to_dict("records")
                    for site in sorted(tab_df["SITE"].dropna().unique())
                }
            }

        # 👉 BRANCH / CONTRATA
        else:
            grouped = {
                "BRANCH": {
                    b: tab_df[tab_df["BRANCH"] == b].to_dict("records")
                    for b in sorted(tab_df["BRANCH"].dropna().unique())
                },
                "CONTRATA": {
                    c: tab_df[tab_df["CONTRATA"] == c].to_dict("records")
                    for c in sorted(tab_df["CONTRATA"].dropna().unique())
                }
            }

        data[tab] = grouped

    return render_template("index.html", tabs=tabs, data=data)

if __name__ == "__main__":
    app.run(debug=True)