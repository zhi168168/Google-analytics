import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler

from api._shared import add_property, send_json


class handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length <= 0 or content_length > 10_000:
                raise ValueError("提交内容无效。")
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            added = add_property(payload.get("project_name"), payload.get("property_id"))
            send_json(self, added, HTTPStatus.CREATED)
        except (ValueError, json.JSONDecodeError) as exc:
            send_json(self, {"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            send_json(
                self,
                {"error": f"保存项目失败：{exc}"},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def log_message(self, format_string: str, *args: object) -> None:
        return
