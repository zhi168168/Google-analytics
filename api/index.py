from __future__ import annotations

import json
from http import HTTPStatus
from pathlib import Path
from urllib.parse import parse_qs

from api._shared import add_property, build_report, validate_date, yesterday

INDEX_FILE = Path(__file__).resolve().parents[1] / "index.html"


def _read_json_body(environ) -> dict[str, object]:
    length = int(environ.get("CONTENT_LENGTH") or 0)
    if length <= 0 or length > 10_000:
        raise ValueError("提交内容无效。")
    body = environ["wsgi.input"].read(length).decode("utf-8")
    return json.loads(body)


def _send_response(
    start_response,
    status: HTTPStatus,
    content: bytes,
    content_type: str,
):
    headers = [
        ("Content-Type", content_type),
        ("Content-Length", str(len(content))),
        ("Cache-Control", "no-store"),
    ]
    start_response(f"{status.value} {status.phrase}", headers)
    return [content]


def _api_path(path: str) -> str:
    if path == "/api":
        return "/"
    if path.startswith("/api/"):
        return path[4:]
    return path


def app(environ, start_response):
    method = environ.get("REQUEST_METHOD", "GET").upper()
    raw_path = environ.get("PATH_INFO", "")
    path = _api_path(raw_path)
    query = parse_qs(environ.get("QUERY_STRING", ""))

    status = HTTPStatus.OK
    payload: dict[str, object]

    try:
        if method == "GET" and raw_path in {"", "/"}:
            return _send_response(
                start_response,
                HTTPStatus.OK,
                INDEX_FILE.read_bytes(),
                "text/html; charset=utf-8",
            )
        if method == "GET" and path in {"/config"}:
            payload = {
                "default_date": yesterday(),
                "max_date": yesterday(),
                "timezone": "Asia/Shanghai",
            }
        elif method == "GET" and path == "/report":
            payload = build_report(validate_date(query.get("date", [""])[0]))
        elif method == "POST" and path == "/properties":
            body = _read_json_body(environ)
            payload = add_property(body.get("project_name"), body.get("property_id"))
            status = HTTPStatus.CREATED
        else:
            status = HTTPStatus.NOT_FOUND
            payload = {"error": "Not found"}
    except ValueError as exc:
        status = HTTPStatus.BAD_REQUEST
        payload = {"error": str(exc)}
    except Exception as exc:
        status = HTTPStatus.INTERNAL_SERVER_ERROR
        if method == "GET" and path == "/report":
            payload = {"error": f"查询失败：{exc}"}
        elif method == "POST" and path == "/properties":
            payload = {"error": f"保存项目失败：{exc}"}
        else:
            payload = {"error": str(exc)}

    content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = [
        ("Content-Type", "application/json; charset=utf-8"),
        ("Content-Length", str(len(content))),
        ("Cache-Control", "no-store"),
    ]
    start_response(f"{status.value} {status.phrase}", headers)
    return [content]
