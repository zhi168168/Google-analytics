"""Shared GA4 report helpers for Vercel Python functions."""

from __future__ import annotations

import base64
import csv
import io
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import DateRange, Metric, RunReportRequest
from google.api_core.exceptions import GoogleAPICallError
from google.oauth2 import service_account


TIMEZONE = "Asia/Shanghai"
ROOT_DIR = Path(__file__).resolve().parents[1]
PROPERTIES_FILE = ROOT_DIR / "properties.csv"
GITHUB_REPOSITORY = os.environ.get(
    "GITHUB_REPOSITORY", "zhi168168/Google-analytics"
)
_thread_local = threading.local()
_properties_lock = threading.Lock()


def send_json(handler, payload: dict[str, object], status: int = 200) -> None:
    content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(content)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(content)


def yesterday() -> str:
    return (datetime.now(ZoneInfo(TIMEZONE)).date() - timedelta(days=1)).isoformat()


def validate_date(date_text: str) -> str:
    try:
        requested = datetime.strptime(date_text, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("日期格式必须为 YYYY-MM-DD。") from exc

    if requested.isoformat() > yesterday():
        raise ValueError(f"最多只能查询到 {yesterday()}。")
    return requested.isoformat()


def parse_properties(content: str) -> list[dict[str, str]]:
    rows = list(csv.DictReader(io.StringIO(content.lstrip("\ufeff"))))
    properties = [
        {
            "project_name": (row.get("project_name") or "").strip(),
            "property_id": (row.get("property_id") or "").strip(),
        }
        for row in rows
    ]
    properties = [
        item
        for item in properties
        if item["project_name"] and item["property_id"]
    ]
    if not properties:
        raise ValueError("项目列表为空或格式无效。")
    return properties


def properties_to_csv(properties: list[dict[str, str]]) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=["project_name", "property_id"])
    writer.writeheader()
    writer.writerows(properties)
    return output.getvalue()


def github_request(method: str, body: dict[str, object] | None = None) -> dict[str, object]:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise ValueError(
            "线上添加项目需要配置 Vercel 环境变量 GITHUB_TOKEN。"
        )

    url = (
        "https://api.github.com/repos/"
        f"{GITHUB_REPOSITORY}/contents/properties.csv"
    )
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ga4-project-analytics",
    }
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = Request(url, data=data, method=method, headers=headers)
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise ValueError(f"GitHub 项目列表更新失败：{message}") from exc


def load_properties() -> list[dict[str, str]]:
    if os.environ.get("VERCEL") == "1" and os.environ.get("GITHUB_TOKEN"):
        remote_file = github_request("GET")
        content = base64.b64decode(str(remote_file["content"])).decode("utf-8")
        return parse_properties(content)
    return parse_properties(PROPERTIES_FILE.read_text(encoding="utf-8-sig"))


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
        properties = load_properties()
        if any(item["property_id"] == identifier for item in properties):
            raise ValueError("这个 GA4 Property ID 已在项目列表中。")
        new_item = {"project_name": name, "property_id": identifier}
        properties.append(new_item)

        if os.environ.get("VERCEL") == "1":
            remote_file = github_request("GET")
            github_request(
                "PUT",
                {
                    "message": f"Add GA4 property: {name}",
                    "content": base64.b64encode(
                        properties_to_csv(properties).encode("utf-8")
                    ).decode("ascii"),
                    "sha": remote_file["sha"],
                },
            )
        else:
            PROPERTIES_FILE.write_text(
                properties_to_csv(properties), encoding="utf-8", newline=""
            )

    return new_item


def get_client() -> BetaAnalyticsDataClient:
    client = getattr(_thread_local, "client", None)
    if client is None:
        credentials_json = os.environ.get("GA4_SERVICE_ACCOUNT_JSON")
        if not credentials_json:
            raise ValueError(
                "缺少 GA4_SERVICE_ACCOUNT_JSON 环境变量。"
            )
        credentials = service_account.Credentials.from_service_account_info(
            json.loads(credentials_json)
        )
        client = BetaAnalyticsDataClient(credentials=credentials, transport="rest")
        _thread_local.client = client
    return client


def query_property(item: dict[str, str], report_date: str) -> dict[str, object]:
    try:
        response = get_client().run_report(
            RunReportRequest(
            property=f"properties/{item['property_id']}",
            date_ranges=[DateRange(start_date=report_date, end_date=report_date)],
            metrics=[Metric(name="activeUsers")],
            )
        )
        active_users = int(response.rows[0].metric_values[0].value) if response.rows else 0
        return {
            **item,
            "active_users": active_users,
            "status": "success",
            "error": "",
        }
    except GoogleAPICallError as exc:
        message = exc.message or str(exc)
    except Exception as exc:
        message = str(exc)
    return {
        **item,
        "active_users": None,
        "status": "error",
        "error": message,
    }


def build_report(report_date: str) -> dict[str, object]:
    properties = load_properties()
    results: list[dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [
            executor.submit(query_property, item, report_date) for item in properties
        ]
        for future in as_completed(futures):
            results.append(future.result())

    order = {item["property_id"]: index for index, item in enumerate(properties)}
    results.sort(key=lambda row: order[str(row["property_id"])])
    successful = [row for row in results if row["status"] == "success"]
    total_users = sum(int(row["active_users"] or 0) for row in successful)
    active_projects = sum(1 for row in successful if int(row["active_users"] or 0) > 0)
    top_project = max(
        successful, key=lambda row: int(row["active_users"] or 0), default=None
    )

    return {
        "date": report_date,
        "timezone": TIMEZONE,
        "generated_at": datetime.now(ZoneInfo(TIMEZONE)).isoformat(),
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
