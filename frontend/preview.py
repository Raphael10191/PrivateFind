
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from jinja2 import Environment, FileSystemLoader, select_autoescape

FRONTEND_DIR = Path(__file__).resolve().parent

templates = Environment(
    loader=FileSystemLoader(FRONTEND_DIR / "templates"),
    autoescape=select_autoescape(["html"])
)

PAGES = {
    "/": "owner_home.html",
    "/owner": "owner_home.html",
    "/owner/reports": "owner_reports.html",
}


class PreviewHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlsplit(self.path).path
        template_name = PAGES.get(path)

        if template_name is None:
            self.send_error(404, "Page not built yet")
            return

        html = templates.get_template(template_name).render(
            reports=[],
            active_page=(
                "reports" if path == "/owner/reports" else "home"
            )
        )

        body = html.encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", 8001), PreviewHandler)

    print("PrivateFind frontend preview")
    print("Home: http://127.0.0.1:8001/owner")
    print("Reports: http://127.0.0.1:8001/owner/reports")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
