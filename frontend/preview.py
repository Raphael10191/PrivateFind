import json
import os
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from jinja2 import Environment, FileSystemLoader, select_autoescape

FRONTEND_DIR = Path(__file__).resolve().parent
BACKEND_URL = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")
MAX_REQUEST_SIZE = 20 * 1024 * 1024

templates = Environment(
    loader=FileSystemLoader(FRONTEND_DIR / "templates"),
    autoescape=select_autoescape(["html"]),
)


def english_date(value):
    if not value:
        return "Not specified"
    date = datetime.fromisoformat(value)
    months = (
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    )
    return f"{months[date.month - 1]} {date.day}, {date.year}"


templates.filters["english_date"] = english_date

ASSETS = {
    "/assets/privatefind.css": ("privatefind.css", "text/css"),
    "/assets/privatefind.js": ("privatefind.js", "text/javascript"),
}

PAGES = {
    "/": ("public_home.html", "public"),
    "/owner": ("owner_home.html", "home"),
    "/owner/reports": ("owner_reports.html", "reports"),
    "/owner/account": ("owner_account.html", "account"),
    "/owner/report/new": ("owner_report_form.html", "reports"),
    "/owner/report/details": ("owner_report_form.html", "reports"),
    "/owner/report/view": ("owner_report_detail.html", "reports"),
    "/owner/claim": ("owner_claim.html", "claims"),
    "/owner/claims": ("owner_claims.html", "claims"),
    "/found/new": ("finder_deposit.html", "finder"),
    "/login": ("owner_login.html", "login"),
    "/register": ("owner_register.html", "register"),
    "/admin": ("admin_dashboard.html", "admin"),
    "/admin/claims": ("admin_claims.html", "admin_claims"),
    "/admin/items": ("admin_items.html", "admin_items"),
    "/admin/lockers": ("admin_lockers.html", "admin_lockers"),
    "/admin/audit": ("admin_audit.html", "admin_audit"),
}


class PreviewHandler(BaseHTTPRequestHandler):
    def redirect(self, destination):
        self.send_response(302)
        self.send_header("Location", destination)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def get_backend_json(self, path, timeout):
        cookie = self.headers.get("Cookie")
        headers = {"Cookie": cookie} if cookie else {}
        request = Request(BACKEND_URL + path, headers=headers)
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)

    def get_current_user(self):
        try:
            return self.get_backend_json("/api/auth/me", timeout=5)
        except HTTPError as error:
            if error.code == 401:
                return None
            raise

    def proxy_api(self):
        url_parts = urlsplit(self.path)
        backend_url = BACKEND_URL + url_parts.path

        if url_parts.query:
            backend_url += "?" + url_parts.query

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_error(400, "Invalid Content-Length")
            return

        if length < 0 or length > MAX_REQUEST_SIZE:
            self.send_error(413, "Request too large")
            return

        body = self.rfile.read(length) if length else None

        forwarded_headers = {}

        for header in ("Content-Type", "Cookie", "Accept", "X-Deposit-Token"):
            value = self.headers.get(header)
            if value:
                forwarded_headers[header] = value

        request = Request(
            backend_url,
            data=body,
            headers=forwarded_headers,
            method=self.command,
        )

        try:
            long_request = url_parts.path == "/api/claims" or url_parts.path.endswith(
                "/candidates"
            )
            response = urlopen(request, timeout=135 if long_request else 30)

        except HTTPError as error:
            response = error

        except OSError:
            self.send_error(502, "Backend is unavailable")
            return

        with response:
            headers = [
                (name, response.headers[name])
                for name in ("Content-Type", "Cache-Control", "Location")
                if response.headers.get(name)
            ]
            headers.extend(
                ("Set-Cookie", cookie)
                for cookie in response.headers.get_all("Set-Cookie", [])
            )
            self.send_body(response.status, response.read(), headers)

    def send_body(self, status, body, headers):
        self.send_response(status)
        for name, value in headers:
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                pass

    def get_owner_reports(self):
        reports = self.get_backend_json("/api/lost-reports", timeout=10)
        if not isinstance(reports, list):
            raise TypeError("Invalid reports response")
        return reports

    def do_GET(self):
        path = urlsplit(self.path).path
        if path.startswith("/api/"):
            self.proxy_api()
            return
        if path in ASSETS:
            name, content_type = ASSETS[path]
            body = (FRONTEND_DIR / "assets" / name).read_bytes()
            self.send_body(
                200, body, [("Content-Type", content_type + "; charset=utf-8")]
            )
            return
        if path not in PAGES:
            self.send_error(404, "Page not built yet")
            return

        template, active_page = PAGES[path]
        route_group = path.split("/", 2)[1]
        user = {}
        if route_group in ("owner", "admin"):
            try:
                user = self.get_current_user()
            except (OSError, ValueError):
                self.send_error(502, "Authentication service unavailable")
                return
            if user is None:
                login_url = "/login"
                if path in ("/owner/report/new", "/owner/report/details"):
                    login_url += "?" + urlencode({"next": "/owner/report/new"})
                self.redirect(login_url)
                return
            if user.get("role") != route_group:
                self.send_error(403, route_group.title() + " access required")
                return

        reports = []
        if path in ("/owner", "/owner/reports"):
            try:
                reports = self.get_owner_reports()
            except (OSError, ValueError, TypeError):
                self.send_error(502, "Could not load reports from the backend")
                return

        html = templates.get_template(template).render(
            reports=reports,
            active_page=active_page,
            account={
                "display_name": user.get("display_name") or "Not provided",
                "email": user.get("email", ""),
            },
            role=user.get("role", "guest"),
        )
        self.send_body(
            200,
            html.encode("utf-8"),
            [
                ("Content-Type", "text/html; charset=utf-8"),
                ("Cache-Control", "no-store"),
            ],
        )

    def do_POST(self):
        if urlsplit(self.path).path.startswith("/api/"):
            self.proxy_api()
        else:
            self.send_error(404, "Page not built yet")

    do_PUT = do_POST


def main():
    host = os.environ.get("FRONTEND_HOST", "127.0.0.1")
    port = int(os.environ.get("FRONTEND_PORT", "8001"))
    with ThreadingHTTPServer((host, port), PreviewHandler) as server:
        print(f"PrivateFind: http://localhost:{port}/login", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
