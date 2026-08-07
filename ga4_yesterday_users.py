#!/usr/bin/env python3
"""Fetch yesterday's GA4 active users for a list of properties."""

from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import DateRange, Metric, RunReportRequest
from google.api_core.exceptions import GoogleAPICallError
from google.oauth2 import service_account


DEFAULT_PROPERTIES_FILE = Path(__file__).with_name("properties.csv")
DEFAULT_OUTPUT_FILE = Path(__file__).with_name("yesterday_users.csv")
DEFAULT_TIMEZONE = "Asia/Shanghai"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="查询多个 GA4 Property 昨天的活跃用户数。"
    )
    parser.add_argument(
        "--key",
        default=os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"),
        help="服务账号 JSON 文件路径，也可通过 GOOGLE_APPLICATION_CREDENTIALS 设置。",
    )
    parser.add_argument(
        "--properties",
        default=str(DEFAULT_PROPERTIES_FILE),
        help=f"Property 列表 CSV，默认：{DEFAULT_PROPERTIES_FILE}",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_FILE),
        help=f"输出 CSV，默认：{DEFAULT_OUTPUT_FILE}",
    )
    parser.add_argument(
        "--date",
        help="查询指定日期，格式 YYYY-MM-DD；不填则查询昨天。",
    )
    parser.add_argument(
        "--timezone",
        default=DEFAULT_TIMEZONE,
        help=f"日期时区，默认：{DEFAULT_TIMEZONE}",
    )
    return parser.parse_args()


def find_key_file(key_argument: str | None) -> Path | None:
    if key_argument:
        return Path(key_argument).expanduser().resolve()

    candidates = sorted(Path(__file__).parent.glob("*.json"))
    if len(candidates) == 1:
        return candidates[0].resolve()
    return None


def get_report_date(date_text: str | None, timezone_name: str) -> date:
    if date_text:
        try:
            return datetime.strptime(date_text, "%Y-%m-%d").date()
        except ValueError as exc:
            raise ValueError("日期必须是 YYYY-MM-DD 格式，例如 2026-08-06") from exc

    return datetime.now(ZoneInfo(timezone_name)).date() - timedelta(days=1)


def load_properties(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))

    if not rows or "project_name" not in rows[0] or "property_id" not in rows[0]:
        raise ValueError("Property CSV 必须包含 project_name 和 property_id 两列。")

    properties = []
    for row in rows:
        name = (row.get("project_name") or "").strip()
        property_id = (row.get("property_id") or "").strip()
        if name and property_id:
            properties.append({"project_name": name, "property_id": property_id})

    if not properties:
        raise ValueError("Property CSV 中没有有效的项目。")
    return properties


def fetch_users(client: BetaAnalyticsDataClient, property_id: str, report_date: str) -> str:
    request = RunReportRequest(
        property=f"properties/{property_id}",
        date_ranges=[DateRange(start_date=report_date, end_date=report_date)],
        metrics=[Metric(name="activeUsers")],
    )
    response = client.run_report(request)
    if not response.rows:
        return "0"
    return response.rows[0].metric_values[0].value


def main() -> int:
    args = parse_args()
    key_path = find_key_file(args.key)

    if key_path is None:
        print(
            "没有找到服务账号 JSON。请把下载的 JSON 放到脚本所在文件夹；"
            "如果文件夹里有多个 JSON，请使用 --key 指定。",
            file=sys.stderr,
        )
        return 2

    properties_path = Path(args.properties).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()

    if not key_path.is_file():
        print(f"找不到服务账号 JSON：{key_path}", file=sys.stderr)
        return 2
    if not properties_path.is_file():
        print(f"找不到 Property 列表：{properties_path}", file=sys.stderr)
        return 2

    try:
        report_date = get_report_date(args.date, args.timezone)
        properties = load_properties(properties_path)
        credentials = service_account.Credentials.from_service_account_file(
            str(key_path)
        )
        # REST works more reliably than gRPC on networks that proxy Google traffic.
        client = BetaAnalyticsDataClient(credentials=credentials, transport="rest")
    except Exception as exc:
        print(f"初始化失败：{exc}", file=sys.stderr)
        return 1

    results: list[dict[str, str]] = []
    print(f"查询日期：{report_date}（{args.timezone}）")
    print(f"共 {len(properties)} 个 Property\n")

    for item in properties:
        name = item["project_name"]
        property_id = item["property_id"]
        try:
            users = fetch_users(client, property_id, report_date.isoformat())
            status = "成功"
        except GoogleAPICallError as exc:
            users = ""
            status = f"失败：{exc.message or exc}"
        except Exception as exc:
            users = ""
            status = f"失败：{exc}"

        results.append(
            {
                "date": report_date.isoformat(),
                "project_name": name,
                "property_id": property_id,
                "active_users": users,
                "status": status,
            }
        )
        display_users = users if users else "-"
        print(f"{name}: {display_users}（{status}）")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "date",
                "project_name",
                "property_id",
                "active_users",
                "status",
            ],
        )
        writer.writeheader()
        writer.writerows(results)

    print(f"\n结果已保存：{output_path}")
    return 0 if all(row["status"] == "成功" for row in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
