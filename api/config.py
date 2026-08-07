from http.server import BaseHTTPRequestHandler

from api._shared import TIMEZONE, send_json, yesterday


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        report_date = yesterday()
        send_json(
            self,
            {
                "default_date": report_date,
                "max_date": report_date,
                "timezone": TIMEZONE,
            },
        )

    def log_message(self, format_string: str, *args: object) -> None:
        return
