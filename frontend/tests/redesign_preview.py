"""Read-only visual QA fixtures; never connects to the real backend.

Run `python frontend/tests/redesign_preview.py`, then open http://127.0.0.1:8003/owner.
Use ?empty=1 for an empty dashboard/report list. Production uses frontend/preview.py.
All writes are rejected, so checking layouts cannot create claims or operate lockers.
"""

import json
import sys
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from preview import PAGES, PreviewHandler, templates  # noqa: E402


REPORTS = [
    dict(id=1, category="headphones", brand="", model="", color="black", location="library",
         lost_at="2026-11-18T12:00:00", created_at="2026-11-18T12:00:00", status="open",
         description="Black over-ear headphones with a small mark on the headband."),
    dict(id=2, category="wallet", brand="", model="", color="brown", location="cafeteria",
         lost_at="2026-11-16T12:00:00", created_at="2026-11-16T12:00:00", status="open",
         description="Brown leather wallet with a stitched pocket."),
    dict(id=3, category="bottle", brand="", model="Water Bottle", color="black", location="lecture_hall",
         lost_at="2026-11-12T12:00:00", created_at="2026-11-12T12:00:00", status="resolved",
         description="Black reusable water bottle."),
]
CANDIDATES = [dict(found_item_id=10, category="headphones", color="black", location="library",
                   found_date="2026-11-18")]
LOCKER = dict(code="L1", name="Library smart locker", location="library", free_compartments=1,
              locations=["library", "cafeteria", "student_center"])


class VisualPreview(PreviewHandler):
    def get_current_user(self):
        return dict(id=1, role="admin" if self.path.startswith("/admin") else "owner",
                    display_name="Student", email="student@example.test")

    def get_owner_reports(self):
        return [] if parse_qs(urlsplit(self.path).query).get("empty") else REPORTS

    def proxy_api(self):
        if self.command != "GET":
            self.send_json(405, dict(error=dict(message="Visual preview is read-only.")))
            return
        path = urlsplit(self.path).path
        if path == "/api/ai/status":
            # Uses the normal service-outage UI, without enabling any writes.
            data = dict(provider="mock", available=False, mock_reporting_enabled=False)
        elif path == "/api/claims":
            data = []
        elif path.endswith("/candidates"):
            data = [] if urlsplit(self.headers.get("Referer", "")).path == "/owner" else CANDIDATES
        elif path.startswith("/api/lost-reports/"):
            report_id = path.rsplit("/", 1)[-1]
            data = next((report for report in REPORTS if str(report["id"]) == report_id), None)
            if data is None:
                self.send_json(404, dict(error=dict(message="Report not found.")))
                return
        elif path.startswith("/api/lockers/"):
            data = LOCKER
        elif path == "/api/admin/lockers":
            data = [dict(**{k: LOCKER[k] for k in ("code", "name", "location")},
                         device_id="visual-preview", last_seen_at=None,
                         compartments=[dict(number=1, state="free", active_item_id=None)])]
        elif path.startswith("/api/admin/"):
            data = []
        else:
            self.send_json(404, dict(error=dict(message="Fixture not configured.")))
            return
        self.send_json(200, data)

    def send_json(self, status, value):
        self.send_body(status, json.dumps(value).encode(), [("Content-Type", "application/json")])


def check_templates():
    """Render all routes with populated and empty data before serving fixtures."""
    from html.parser import HTMLParser

    class IDs(HTMLParser):
        def __init__(self):
            super().__init__()
            self.ids = []

        def handle_starttag(self, tag, attrs):
            self.ids.extend(value for key, value in attrs if key == "id")

    count = 0
    for page, (template, active_page) in PAGES.items():
        for reports in (REPORTS, []):
            html = templates.get_template(template).render(
                reports=reports, active_page=active_page,
                role="admin" if page.startswith("/admin") else "owner" if page.startswith("/owner") else "guest",
                account=dict(display_name="Student", email="student@example.test"))
            parsed = IDs()
            parsed.feed(html)
            assert len(parsed.ids) == len(set(parsed.ids)), f"Duplicate IDs in {page}"
            assert 'privatefind-theme.css' in html
            count += 1
    return count


if __name__ == "__main__":
    print(f"Rendered {check_templates()} route/state combinations successfully.", flush=True)
    if "--check" not in sys.argv:
        print("READ-ONLY visual preview: http://127.0.0.1:8003/owner", flush=True)
        ThreadingHTTPServer(("127.0.0.1", 8003), VisualPreview).serve_forever()
