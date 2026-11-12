
import json

from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from jinja2 import (
    Environment,
    FileSystemLoader,
    select_autoescape,
)


FRONTEND_DIR = Path(__file__).resolve().parent
BACKEND_URL = "http://127.0.0.1:8000"
MAX_REQUEST_SIZE = 20 * 1024 * 1024

templates = Environment(
    loader=FileSystemLoader(FRONTEND_DIR / "templates"),
    autoescape=select_autoescape(["html"]),
)

PAGES = {
    "/": "owner_home.html",
    "/owner": "owner_home.html",
    "/owner/reports": "owner_reports.html",
    "/owner/account": "owner_account.html",
    "/owner/report/new": "owner_report_step1.html",
    "/owner/report/details": "owner_report_step2.html",
    "/login": "owner_login.html",
    "/register": "owner_register.html",
}


class PreviewHandler(BaseHTTPRequestHandler):

    def redirect(self, destination):
        self.send_response(302)
        self.send_header("Location", destination)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def get_current_user(self):
        headers = {}

        cookie = self.headers.get("Cookie")
        if cookie:
            headers["Cookie"] = cookie

        request = Request(
            BACKEND_URL + "/api/auth/me",
            headers=headers,
            method="GET",
        )

        try:
            with urlopen(request, timeout=5) as response:
                return json.load(response)

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
            length = int(
                self.headers.get("Content-Length", "0")
            )
        except ValueError:
            self.send_error(400, "Invalid Content-Length")
            return

        if length < 0 or length > MAX_REQUEST_SIZE:
            self.send_error(413, "Request too large")
            return

        body = self.rfile.read(length) if length else None

        forwarded_headers = {}

        for header in ("Content-Type", "Cookie", "Accept"):
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
            response = urlopen(request, timeout=30)

        except HTTPError as error:
            response = error

        except (URLError, TimeoutError, OSError):
            self.send_error(502, "Backend is unavailable")
            return

        with response:
            response_body = response.read()

            self.send_response(response.status)

            for header in (
                "Content-Type",
                "Cache-Control",
                "Location",
            ):
                value = response.headers.get(header)
                if value:
                    self.send_header(header, value)

            for cookie in response.headers.get_all(
                "Set-Cookie", []
            ):
                self.send_header("Set-Cookie", cookie)

            self.send_header(
                "Content-Length",
                str(len(response_body)),
            )
            self.end_headers()

            if response_body:
                try:
                    self.wfile.write(response_body)
                except (
                    BrokenPipeError,
                    ConnectionAbortedError,
                    ConnectionResetError,
                ):
                    pass

    def do_GET(self):
        path = urlsplit(self.path).path

        # Forward API requests to FastAPI.
        if path.startswith("/api/"):
            self.proxy_api()
            return

        # Redirect the root URL to Owner Home.
        if path == "/":
            self.redirect("/owner")
            return

        template_name = PAGES.get(path)

        if template_name is None:
            self.send_error(404, "Page not built yet")
            return

        # Always initialize user, including on public pages.
        user = None

        # Protect Owner pages using the backend session.
        if path.startswith("/owner"):
            try:
                user = self.get_current_user()

            except (
                HTTPError,
                URLError,
                TimeoutError,
                OSError,
                ValueError,
            ):
                self.send_error(
                    502,
                    "Authentication service unavailable"
                )
                return

            if user is None:
                self.redirect("/login")
                return

            if user.get("role") != "owner":
                self.send_error(
                    403,
                    "Owner access required"
                )
                return

        # Use real account information for logged-in Owners.
        if user is not None:
            account = {
                "display_name": (
                    user.get("display_name")
                    or "Not provided"
                ),
                "email": user.get("email", ""),
            }
        else:
            account = {
                "display_name": "Not provided",
                "email": "",
            }

        html = templates.get_template(
            template_name
        ).render(
            reports=[],
            active_page=(
                "account" if path == "/owner/account"
                else "reports" if path == "/owner/reports"
                else "home"
            ),
            account=account,
        )

        body = html.encode("utf-8")

        self.send_response(200)
        self.send_header(
            "Content-Type",
            "text/html; charset=utf-8",
        )
        self.send_header(
            "Content-Length",
            str(len(body)),
        )
        self.end_headers()

        try:
            self.wfile.write(body)
        except (
            BrokenPipeError,
            ConnectionAbortedError,
            ConnectionResetError,
        ):
            pass

    def do_POST(self):
        if urlsplit(self.path).path.startswith("/api/"):
            self.proxy_api()
        else:
            self.send_error(404, "Page not built yet")

    def do_PUT(self):
        if urlsplit(self.path).path.startswith("/api/"):
            self.proxy_api()
        else:
            self.send_error(404, "Page not built yet")


if __name__ == "__main__":
    server = HTTPServer(
        ("127.0.0.1", 8001),
        PreviewHandler,
    )

    print("PrivateFind frontend preview")
    print("Login: http://127.0.0.1:8001/login")
    print("Register: http://127.0.0.1:8001/register")
    print("Home: http://127.0.0.1:8001/owner")
    print("Reports: http://127.0.0.1:8001/owner/reports")
    print("Account: http://127.0.0.1:8001/owner/account")
    print("API: http://127.0.0.1:8001/api/health")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
