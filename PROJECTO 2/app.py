import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import re
from io import BytesIO

st.set_page_config(page_title="Consulta BRAS", layout="centered")

st.title("📡 Consulta de Estado BRAS")

# --- BOTÓN 1: Descargar plantilla ---
with open("TMs.xlsx", "rb") as f:
    st.download_button(
        label="📥 Descargar plantilla TMs.xlsx",
        data=f,
        file_name="TMs.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

# --- BOTÓN 2: Subir archivo ---
uploaded_file = st.file_uploader("📤 Sube tu archivo TMs.xlsx", type=["xlsx"])

if uploaded_file:
    df = pd.read_excel(uploaded_file)
    st.write("Vista previa de tu archivo:")
    st.dataframe(df.head())

    # --- BOTÓN 3: Ejecutar proceso ---
    if st.button("🚀 Ejecutar consultas"):
        resultados = []

        st.info("Consultando BRAS... por favor espera ⏳")

        for _, row in df.iterrows():
            cuenta = row['USERNAME']
            bras = row['BRAS']
            url = f"http://10.121.62.102:8080/backup/cgi-bin/bras_checkuser/bras_checkkick_online.php?cat=view&acc={cuenta}&domain=&bras={bras}"

            try:
                response = requests.get(url, timeout=5)
                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, 'html.parser')
                    for tag in soup(["script", "style"]):
                        tag.decompose()
                    texto = soup.get_text(separator='\n', strip=True)
                    resultados.append(texto)
                else:
                    resultados.append(f"Error {response.status_code}")
            except Exception as e:
                resultados.append(f"Error: {str(e)}")

        df['Resultado'] = resultados

        # --- FUNCIONES DE EXTRACCIÓN ---
        def extraer_estado(texto):
            if "ONLINE on bras" in texto:
                return "ONLINE"
            elif "NOT ONLINE ON bras" in texto or "no session" in texto.lower():
                return "NOT ONLINE"
            else:
                return "UNKNOWN"

        def extraer_info(texto):
            if not isinstance(texto, str):
                return pd.Series([None]*6)
            account = re.search(r"Account:\s*(\S+)", texto)
            account = account.group(1) if account else None
            estado = extraer_estado(texto)
            ipv4 = re.search(r"ipv4[-_\s]*address\s*:\s*([\d\.]+)", texto, re.IGNORECASE)
            ipv4 = ipv4.group(1) if ipv4 else None
            gateway = re.search(r"gateway[-_\s]*address\s*:\s*([\d\.]+)", texto, re.IGNORECASE)
            gateway = gateway.group(1) if gateway else None
            primary_dns = re.search(r"primary[-_\s]*dns\s*:\s*([\d\.]+)", texto, re.IGNORECASE)
            primary_dns = primary_dns.group(1) if primary_dns else None
            second_dns = re.search(r"second[-_\s]*dns\s*:\s*([\d\.]+)", texto, re.IGNORECASE)
            second_dns = second_dns.group(1) if second_dns else None
            return pd.Series([account, estado, ipv4, gateway, primary_dns, second_dns])

        df[['Account', 'Estado', 'ipv4-address', 'gateway-address', 'primary-dns', 'second-dns']] = df['Resultado'].apply(extraer_info)
        df['Fecha_consulta'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # --- EXPORTAR A EXCEL ---
        output = BytesIO()
        df.to_excel(output, index=False)
        output.seek(0)

        st.success("✅ Proceso completado. Archivo listo para descargar.")
        st.download_button(
            label="📄 Descargar resultado_consultas.xlsx",
            data=output,
            file_name="resultado_consultas.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
