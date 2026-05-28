import os
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, request

BASE_URL = "https://www.pinetoplakes-association.com"
LOGIN_PATH = "/sl_login.php?redirect=%2Frequestmanager.php%3Fview%3Dusersubmit%26cat%3D1"
FORM_PATH = "/requestmanager.php?view=usersubmit&cat=1"

HOA_USERNAME = os.environ.get("HOA_USERNAME", "")
HOA_PASSWORD = os.environ.get("HOA_PASSWORD", "")
API_KEY = os.environ.get("API_KEY", "")

app = Flask(__name__)


def abs_url(path: str) -> str:
    return urljoin(BASE_URL, path)


class HoaClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (compatible; HOA-Zapier-Bridge/1.0)",
            }
        )

    def login(self):
        from requests import Request
    
        login_url = abs_url("/sl_login.php?redirect=%2Frequestmanager.php%3Fview%3Dusersubmit%26cat%3D1")
    
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Mobile Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": BASE_URL,
            "Referer": login_url,
        })
    
        login_get = self.session.get(login_url, timeout=20)
        login_get.raise_for_status()
        
        print("USERNAME LENGTH:", len(HOA_USERNAME), "PASSWORD LENGTH:", len(HOA_PASSWORD), flush=True)    
        print("LOGIN GET URL:", login_get.url, flush=True)
        print("COOKIES AFTER GET:", self.session.cookies.get_dict(), flush=True)
        print("GET STATUS:", login_get.status_code, flush=True)
    
        payload = {
            "uname": HOA_USERNAME,
            "pass": HOA_PASSWORD,
            "submit2": "Submit",
        }
    
        req = Request(
            "POST",
            login_url,
            data=payload,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": BASE_URL,
                "Referer": login_url,
            },
        )
    
        prepared = self.session.prepare_request(req)
    
        print("PREPARED POST URL:", prepared.url, flush=True)
        print("PREPARED POST HEADERS:", dict(prepared.headers), flush=True)
        print("PREPARED POST BODY:", prepared.body, flush=True)
    
        login_post = self.session.send(
            prepared,
            allow_redirects=True,
            timeout=20,
        )
        login_post.raise_for_status()
    
        print("LOGIN POST FINAL URL:", login_post.url, flush=True)
        print("COOKIES AFTER POST:", self.session.cookies.get_dict(), flush=True)
        print("POST STATUS:", login_post.status_code, flush=True)
        print("POST BODY START:", login_post.text[:300], flush=True)
    
        if 'id="sl_login_title"' in login_post.text or ">Login<" in login_post.text:
            raise RuntimeError("Login failed; still receiving login page")
    
        return login_post

    def fetch_form(self):
        r = self.session.get(abs_url(FORM_PATH), timeout=20)
        r.raise_for_status()

        if 'id="sl_login_title"' in r.text:
            raise RuntimeError("Not authenticated when fetching form")

        soup = BeautifulSoup(r.text, "html.parser")
        form = soup.find("form", {"id": "rm-form"})
        if not form:
            raise RuntimeError("Rental form not found")

        action = form.get("action", FORM_PATH)
        inputs = {}
        for el in form.find_all("input"):
            name = el.get("name")
            if not name:
                continue
            t = (el.get("type") or "").lower()
            if t in ("submit", "button", "image", "file"):
                continue
            inputs[name] = el.get("value", "")

        return action, inputs

    def submit_rental(self, data: dict):
        action, form_inputs = self.fetch_form()

        form_inputs.update(
            {
                "catlong": "Rental Registration Form",
                "name": data["name"],
                "email": data["email"],
                "field[0][data]": data["lease_start_date"],
                "field[1][data]": data["lease_end_date"],
                "field[2][data]": data["owner_name"],
                "field[3][data]": data["owner_phone"],
                "field[4][data]": data.get("unit_lot_number", ""),
                "field[5][data]": data["pla_address"],
                "field[6][data]": data["owner_email"],
                "field[7][data]": data["responsible_tenant_name"],
                "field[8][data]": data["tenant_mobile_number"],
                "field[9][data]": data.get("other_tenant_names", ""),
                "field[10][data]": data.get("vehicles", ""),
                "submit": "true",
                "gvalidate": data.get("gvalidate", ""),
            }
        )

        post_url = abs_url(action.split("#")[0])

        r = self.session.post(
            post_url,
            data=form_inputs,
            timeout=30,
            allow_redirects=True,
        )
        r.raise_for_status()
        return r


def require_api_key(req):
    if not API_KEY:
        return None
    auth = req.headers.get("Authorization", "")
    if auth == f"Bearer {API_KEY}":
        return None
    if req.headers.get("X-API-Key", "") == API_KEY:
        return None
    return jsonify({"status": "error", "detail": "Unauthorized"}), 401


@app.route("/healthz", methods=["GET"])
def healthz():
    return jsonify({"status": "ok"}), 200


@app.route("/submit-rental", methods=["POST"])
def submit_rental():
    auth_error = require_api_key(request)
    if auth_error:
        return auth_error


    app.logger.warning("RAW BODY: %s", request.get_data(as_text=True))
    payload = request.get_json(silent=True) or {}
    app.logger.warning("INCOMING AUTH: %s", request.headers.get("Authorization"))
    app.logger.warning("INCOMING JSON: %s", payload)
    
    required = [
        "name",
        "email",
        "lease_start_date",
        "lease_end_date",
        "owner_name",
        "owner_phone",
        "pla_address",
        "owner_email",
        "responsible_tenant_name",
        "tenant_mobile_number",
    ]
    missing = [k for k in required if not str(payload.get(k, "")).strip()]
    if missing:
        return jsonify({"status": "error", "missing_fields": missing}), 400

    try:
        client = HoaClient()
        client.login()
        response = client.submit_rental(payload)
        body = response.text

        success_signals = [
            "thank you",
            "request has been submitted",
            "form has been submitted",
            "successfully submitted",
        ]
        success = any(s in body.lower() for s in success_signals)

        return (
            jsonify(
                {
                    "status": "ok" if success else "unknown",
                    "http_status": response.status_code,
                    "success_detected": success,
                }
            ),
            200,
        )
    except Exception as e:
        return (
            jsonify(
                {
                    "status": "error",
                    "detail": str(e),
                }
            ),
            500,
        )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
