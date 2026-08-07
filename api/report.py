from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from api._shared import build_report, send_json, validate_date


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        query = parse_qs(urlparse(self.path).query)
        try:
            report = build_report(validate_date(query.get("date", [""])[0]))
            send_json(self, report)
        except ValueError as exc:
            send_json(self, {"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            send_json(
                self,
                {"error": f"查询失败：{exc}"},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def log_message(self, format_string: str, *args: object) -> None:
        return
