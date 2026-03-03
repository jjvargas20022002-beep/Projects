import os
import re
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

BRAS_INTERNAL_ENDPOINT = os.environ.get(
    "BRAS_INTERNAL_ENDPOINT",
    "http://10.121.62.102:8080/backup/cgi-bin/bras_checkuser/bras_checkkick_online.php",
).strip()
BRIDGE_TOKEN = os.environ.get("BRIDGE_TOKEN", "").strip()
REQUEST_TIMEOUT = float(os.environ.get("BRIDGE_REQUEST_TIMEOUT", "5"))


def extract_status_info(raw_html: str):
    text = str(raw_html or "")
    cleaned = re.sub(r"<script[\s\S]*?</script>", " ", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"<style[\s\S]*?</style>", " ", cleaned, flags=re.IGNORECASE)
    plain = re.sub(r"<[^>]+>", " ", cleaned)
    plain = re.sub(r"\s+", " ", plain).strip()

    lowered = plain.lower()
    if "online on bras" in lowered:
        estado = "ONLINE"
    elif "not online on bras" in lowered or "no session" in lowered:
        estado = "NOT ONLINE"
    else:
        estado = "UNKNOWN"

    ipv4 = re.search(r"ipv4[-_\s]*address\s*:\s*([\d\.]+)", plain, flags=re.IGNORECASE)
    if ipv4:
        ip_value = ipv4.group(1)
        ip_status = "IP OK" if not (ip_value.startswith("172.") or ip_value.startswith("9.")) else "IP NOK"
    else:
        ip_status = "IP NOK"

    return estado, ip_status, plain


@app.get("/health")
def health():
    return jsonify({"ok": True})


@app.get("/bras_check")
def bras_check():
    if BRIDGE_TOKEN:
        incoming = request.headers.get("X-Bridge-Token", "").strip()
        if incoming != BRIDGE_TOKEN:
            return jsonify({"error": "unauthorized"}), 401

    username = (request.args.get("acc", "") or "").strip()
    bras = (request.args.get("bras", "") or "").strip()
    domain = (request.args.get("domain", "") or "").strip()

    if not username:
        return jsonify({"error": "missing_acc"}), 400

    params = {
        "cat": "view",
        "acc": username,
        "domain": domain,
        "bras": bras,
    }

    try:
        response = requests.get(BRAS_INTERNAL_ENDPOINT, params=params, timeout=REQUEST_TIMEOUT)
    except requests.exceptions.RequestException as exc:
        return jsonify({"error": "upstream_unreachable", "detail": str(exc)[:200]}), 502

    estado, ip_status, plain = extract_status_info(response.text)
    return jsonify(
        {
            "upstream_status": response.status_code,
            "estado": estado,
            "ip_status": ip_status,
            "text": plain[:1000],
        }
    ), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8088")))
