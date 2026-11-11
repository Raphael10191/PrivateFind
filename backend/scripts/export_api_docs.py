"""Export OpenAPI and a manual Postman collection from the current routes.

Run from backend/: python -m scripts.export_api_docs
The exported OpenAPI adds documentation-only auth/error metadata that FastAPI's
custom dependencies and exception handlers do not automatically describe.
"""

import copy
import json
from pathlib import Path

from app.main import create_app

OUTPUT = Path(__file__).resolve().parents[2] / "docs" / "api"
METHODS = {"get", "post", "put", "patch", "delete"}


def export_openapi() -> dict:
    spec = create_app().openapi()
    spec["info"]["version"] = "1.0.0"
    spec["info"]["description"] = (
        "PrivateFind frontend integration snapshot. Browser auth uses the session cookie; "
        "device keys are for firmware/test tools only. Custom auth/error annotations and "
        "the legacy device alias are added by scripts.export_api_docs; "
        "runtime routes are unchanged."
    )
    spec["servers"] = [{"url": "http://localhost:8000", "description": "Local Docker API"}]
    spec["components"]["securitySchemes"] = {
        "SessionCookie": {"type": "apiKey", "in": "cookie", "name": "session"},
        "DeviceKey": {"type": "apiKey", "in": "header", "name": "X-Device-Key"},
    }
    spec["components"]["schemas"]["ApiError"] = {
        "type": "object",
        "required": ["error"],
        "properties": {
            "error": {
                "type": "object",
                "required": ["code", "message"],
                "properties": {
                    "code": {"type": "string"},
                    "message": {"type": "string"},
                    "fields": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["field", "message"],
                            "properties": {
                                "field": {"type": "string"},
                                "message": {"type": "string"},
                            },
                        },
                    },
                },
            }
        },
    }
    alias = copy.deepcopy(spec["paths"]["/api/device/codes/validate"])
    alias["post"]["operationId"] = "validate_code_legacy_locker_validate_post"
    alias["post"]["summary"] = "Legacy alias of device code validation"
    spec["paths"]["/locker/validate"] = alias
    for path, operations in spec["paths"].items():
        for method, operation in operations.items():
            if method not in METHODS:
                continue
            device = path.startswith("/api/device/") or path == "/locker/validate"
            admin = path.startswith("/api/admin/")
            authenticated = (
                admin
                or path.startswith(("/api/lost-reports", "/api/claims"))
                or path == "/api/auth/me"
            )
            operation["security"] = (
                [{"DeviceKey": []}] if device else [{"SessionCookie": []}] if authenticated else []
            )
            operation["x-role"] = (
                "device"
                if device
                else "admin"
                if admin
                else "account"
                if authenticated
                else "public"
            )
            if device:
                operation["parameters"] = [
                    p for p in operation.get("parameters", []) if p.get("name") != "x-device-key"
                ]
            for status, response in list(operation["responses"].items()):
                if status == "422":
                    response["description"] = (
                        "Validation error; custom ApiError envelope with fields."
                    )
                    response["content"] = {
                        "application/json": {"schema": {"$ref": "#/components/schemas/ApiError"}}
                    }
            # A generic default documents the envelope without promising that every
            # endpoint returns every business status. The guide lists actual codes.
            operation["responses"]["default"] = {
                "description": (
                    "Handled business/auth/HTTP error. See the guide for endpoint-specific codes; "
                    "unexpected 500/network failures may not be JSON."
                ),
                "content": {
                    "application/json": {"schema": {"$ref": "#/components/schemas/ApiError"}}
                },
            }
    spec["paths"]["/api/admin/items/{item_id}/photos/{photo_id}"]["get"]["responses"]["200"] = {
        "description": "JPEG image bytes",
        "content": {"image/jpeg": {"schema": {"type": "string", "format": "binary"}}},
    }
    spec["paths"]["/api/admin/items/{item_id}/retry-ai"]["post"]["responses"]["202"]["content"] = {
        "application/json": {
            "schema": {
                "type": "object",
                "required": ["ok"],
                "properties": {"ok": {"type": "boolean"}},
            }
        },
    }
    spec["paths"]["/api/device/heartbeat"]["post"]["responses"]["200"]["content"] = {
        "application/json": {
            "schema": {
                "type": "object",
                "required": ["ok", "server_time"],
                "properties": {
                    "ok": {"type": "boolean"},
                    "server_time": {"type": "string", "format": "date-time"},
                },
            }
        },
    }
    return spec


def export_postman(spec: dict) -> dict:
    examples = {
        "/api/auth/register": {
            "email": "{{email}}",
            "password": "{{password}}",
            "display_name": "Test owner",
        },
        "/api/auth/login": {"email": "{{email}}", "password": "{{password}}"},
        "/api/lost-reports": {
            "category": "phone",
            "location": "library",
            "lost_at": "{{$isoTimestamp}}",
            "color": "black",
            "brand": "Samsung",
            "description": "Black Samsung phone with a cat sticker",
        },
        "/api/claims": {
            "lost_report_id": "{{report_id}}",
            "found_item_id": "{{item_id}}",
            "evidence": [
                {"type": "serial_suffix", "value": "4821"},
                {"type": "sticker_or_mark", "value": "cat sticker on the back"},
            ],
        },
        "/api/admin/claims/{claim_id}/decision": {
            "decision": "approve",
            "note": "Reviewed ownership evidence.",
        },
        "/api/admin/items/{item_id}/attributes": {
            "category": "phone",
            "public_summary": "Black Samsung phone",
            "attributes": [
                {"name": "color", "value": "black", "visibility": "public"},
                {
                    "name": "serial_suffix",
                    "value": "4821",
                    "visibility": "private",
                    "strength": "strong",
                },
            ],
        },
        "/api/admin/items/{item_id}/retry-ai": None,
        "/api/device/codes/validate": {"device_id": "locker_01", "code": "{{deposit_code}}"},
        "/locker/validate": {"device_id": "locker_01", "code": "{{deposit_code}}"},
        "/api/device/compartments/{number}/state": {"device_id": "locker_01", "occupied": True},
        "/api/device/heartbeat": {"firmware_version": "test-1.0"},
    }
    groups = {}
    for path, operations in spec["paths"].items():
        for method, operation in operations.items():
            if method not in METHODS:
                continue
            group = (
                "Device (not browser code)"
                if operation["x-role"] == "device"
                else operation.get("tags", ["health"])[0]
            )
            url = "{{base_url}}" + path
            for name in ("locker_code", "item_id", "report_id", "claim_id", "photo_id", "number"):
                url = url.replace(
                    "{" + name + "}", "{{" + ("compartment" if name == "number" else name) + "}}"
                )
            request = {
                "method": method.upper(),
                "url": url,
                "header": [],
                "description": (
                    f"Role: {operation['x-role']}. See frontend-integration.md. "
                    "Cookies are managed by Postman after login."
                ),
            }
            if operation["x-role"] == "device":
                request["header"].append({"key": "X-Device-Key", "value": "{{device_key}}"})
            if path == "/api/deposits":
                request["body"] = {
                    "mode": "formdata",
                    "formdata": [
                        {"key": "locker_code", "value": "{{locker_code}}", "type": "text"},
                        {"key": "location", "value": "library", "type": "text"},
                        {
                            "key": "note",
                            "value": "Black Samsung phone, cat sticker, serial ends 4821",
                            "type": "text",
                        },
                        {"key": "photos", "type": "file", "src": ""},
                    ],
                }
            elif method in {"post", "put"} and path in examples and examples[path] is not None:
                raw = json.dumps(examples[path], indent=2)
                for name in ("report_id", "item_id"):
                    raw = raw.replace('"{{' + name + '}}"', "{{" + name + "}}")
                request["header"].append({"key": "Content-Type", "value": "application/json"})
                request["body"] = {
                    "mode": "raw",
                    "raw": raw,
                    "options": {"raw": {"language": "json"}},
                }
            event = [
                {
                    "listen": "test",
                    "script": {
                        "type": "text/javascript",
                        "exec": [
                            "const isJson = pm.response.headers.get('Content-Type')"
                            "?.includes('application/json');",
                            "if (pm.response.code >= 200 && pm.response.code < 300 && isJson) {",
                            "  const b = pm.response.json();",
                            *(
                                [
                                    "  pm.collectionVariables.set('item_id', b.item_id);",
                                    "  pm.collectionVariables.set('deposit_code', b.deposit_code);",
                                    "  pm.collectionVariables.set('compartment', b.compartment);",
                                ]
                                if path == "/api/deposits"
                                else []
                            ),
                            *(
                                ["  pm.collectionVariables.set('report_id', b.id);"]
                                if path == "/api/lost-reports" and method == "post"
                                else []
                            ),
                            *(
                                [
                                    "  if (b.length) pm.collectionVariables.set("
                                    "'item_id', b[0].found_item_id);"
                                ]
                                if path.endswith("/candidates")
                                else []
                            ),
                            *(
                                ["  pm.collectionVariables.set('claim_id', b.id);"]
                                if path == "/api/claims" and method == "post"
                                else []
                            ),
                            "  if (b.pickup_code) pm.collectionVariables.set("
                            "'pickup_code', b.pickup_code);",
                            "}",
                        ],
                    },
                }
            ]
            groups.setdefault(group, []).append(
                {"name": f"{method.upper()} {path}", "request": request, "event": event}
            )
    variables = {
        "base_url": "http://localhost:8000",
        "email": "owner@example.com",
        "password": "secret123",
        "locker_code": "L1",
        "item_id": "1",
        "report_id": "1",
        "claim_id": "1",
        "photo_id": "1",
        "compartment": "1",
        "device_key": "",
        "deposit_code": "",
        "pickup_code": "",
    }
    return {
        "info": {
            "name": "PrivateFind API",
            "description": (
                "Manual integration collection. Select a photo before deposit; "
                "set device_key manually. Change email/password and login as the seeded admin "
                "for admin requests. Device validation defaults to deposit_code; "
                "substitute pickup_code for pickup. State defaults to occupied=true; "
                "send false after pickup. This is not an unattended collection-runner scenario."
            ),
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "variable": [{"key": k, "value": v} for k, v in variables.items()],
        "item": [{"name": k, "item": v} for k, v in groups.items()],
    }


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    spec = export_openapi()
    for name, value in (("openapi.json", spec), ("postman-collection.json", export_postman(spec))):
        (OUTPUT / name).write_text(
            json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    count = sum(method in METHODS for operations in spec["paths"].values() for method in operations)
    print(f"Exported {count} operations to {OUTPUT}")


if __name__ == "__main__":
    main()
