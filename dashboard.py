#!/usr/bin/env python3
"""Local web dashboard for GA4 active-user reports."""

from __future__ import annotations

import argparse
import csv
import json
import threading
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.api_core.exceptions import GoogleAPICallError
from google.oauth2 import service_account

from ga4_yesterday_users import (
    DEFAULT_PROPERTIES_FILE,
    DEFAULT_TIMEZONE,
    fetch_users,
    find_key_file,
    load_properties,
)


APP_DIR = Path(__file__).parent
INDEX_FILE = APP_DIR / "index.html"
_thread_local = threading.local()
_properties_lock = threading.Lock()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="启动 GA4 用户数可视化仪表盘。")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    return parser.parse_args()


def get_client(key_path: Path) -> BetaAnalyticsDataClient:
    client = getattr(_thread_local, "client", None)
    if client is None:
        credentials = service_account.Credentials.from_service_account_file(
            str(key_path)
        )
        client = BetaAnalyticsDataClient(credentials=credentials, transport="rest")
        _thread_local.client = client
    return client


def validate_date(date_text: str) -> str:
    try:
        requested = datetime.strptime(date_text, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("日期格式必须为 YYYY-MM-DD。") from exc

    yesterday = datetime.now(ZoneInfo(DEFAULT_TIMEZONE)).date() - timedelta(days=1)
    if requested > yesterday:
        raise ValueError(f"最多只能查询到 {yesterday.isoformat()}。")
    return requested.isoformat()


def query_property(
    key_path: Path, item: dict[str, str], report_date: str
) -> dict[str, object]:
    try:
        users = int(fetch_users(get_client(key_path), item["property_id"], report_date))
        return {
            "project_name": item["project_name"],
            "property_id": item["property_id"],
            "active_users": users,
            "status": "success",
            "error": "",
        }
    except GoogleAPICallError as exc:
        message = exc.message or str(exc)
    except Exception as exc:
        message = str(exc)

    return {
        "project_name": item["project_name"],
        "property_id": item["property_id"],
        "active_users": None,
        "status": "error",
        "error": message,
    }


def build_report(key_path: Path, report_date: str) -> dict[str, object]:
    properties = load_properties(DEFAULT_PROPERTIES_FILE)
    results: list[dict[str, object]] = []

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [
            executor.submit(query_property, key_path, item, report_date)
            for item in properties
        ]
        for future in as_completed(futures):
            results.append(future.result())

    order = {
        item["property_id"]: index
        for index, item in enumerate(properties)
    }
    results.sort(key=lambda row: order[str(row["property_id"])])

    successful = [row for row in results if row["status"] == "success"]
    total_users = sum(int(row["active_users"] or 0) for row in successful)
    active_projects = sum(1 for row in successful if int(row["active_users"] or 0) > 0)
    top_project = max(
        successful,
        key=lambda row: int(row["active_users"] or 0),
        default=None,
    )

    return {
        "date": report_date,
        "timezone": DEFAULT_TIMEZONE,
        "generated_at": datetime.now(ZoneInfo(DEFAULT_TIMEZONE)).isoformat(),
        "summary": {
            "total_users": total_users,
            "active_projects": active_projects,
            "project_count": len(properties),
            "top_project": top_project["project_name"] if top_project else "-",
            "top_project_users": top_project["active_users"] if top_project else 0,
            "failed_projects": len(results) - len(successful),
        },
        "projects": results,
    }


def add_property(project_name: object, property_id: object) -> dict[str, str]:
    name = str(project_name or "").strip()
    identifier = str(property_id or "").strip()

    if not name:
        raise ValueError("请填写项目名称。")
    if len(name) > 120:
        raise ValueError("项目名称不能超过 120 个字符。")
    if not identifier.isdigit():
        raise ValueError("GA4 Property ID 必须是一串数字。")

    with _properties_lock:
        properties = load_properties(DEFAULT_PROPERTIES_FILE)
        if any(item["property_id"] == identifier for item in properties):
            raise ValueError("这个 GA4 Property ID 已在项目列表中。")

        with DEFAULT_PROPERTIES_FILE.open("a", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=["project_name", "property_id"])
            writer.writerow({"project_name": name, "property_id": identifier})

    return {"project_name": name, "property_id": identifier}


class DashboardHandler(BaseHTTPRequestHandler):
    key_path: Path

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_file(INDEX_FILE, "text/html; charset=utf-8")
            return

        if parsed.path == "/api/report":
            query = parse_qs(parsed.query)
            date_text = query.get("date", [""])[0]
            try:
                report_date = validate_date(date_text)
                report = build_report(self.key_path, report_date)
                self.send_json(report)
            except ValueError as exc:
                self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            except Exception as exc:
                self.send_json(
                    {"error": f"查询失败：{exc}"},
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            return

        if parsed.path == "/api/config":
            yesterday = (
                datetime.now(ZoneInfo(DEFAULT_TIMEZONE)).date() - timedelta(days=1)
            )
            self.send_json(
                {
                    "default_date": yesterday.isoformat(),
                    "max_date": yesterday.isoformat(),
                    "timezone": DEFAULT_TIMEZONE,
                }
            )
            return

        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/properties":
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length <= 0 or content_length > 10_000:
                raise ValueError("提交内容无效。")
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            property_data = add_property(
                payload.get("project_name"), payload.get("property_id")
            )
            self.send_json(property_data, HTTPStatus.CREATED)
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self.send_json(
                {"error": f"保存项目失败：{exc}"},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def send_file(self, path: Path, content_type: str) -> None:
        if not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def send_json(
        self, payload: dict[str, object], status: HTTPStatus = HTTPStatus.OK
    ) -> None:
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format_string: str, *args: object) -> None:
        return


def main() -> int:
    args = parse_args()
    key_path = find_key_file(None)
    if key_path is None:
        print("没有找到服务账号 JSON。请确保文件夹中只有一个 JSON 文件。")
        return 2
    if not INDEX_FILE.is_file():
        print(f"找不到页面文件：{INDEX_FILE}")
        return 2

    DashboardHandler.key_path = key_path
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    url = f"http://{args.host}:{args.port}"
    print(f"GA4 仪表盘已启动：{url}")
    print("关闭此窗口即可停止服务。")

    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
