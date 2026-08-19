#!/usr/bin/env python3
"""Meraki Scanning API v3に近いWi-Fi Payloadを生成・送信する検証ツール。"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# scripts直下から実行した場合も、プロジェクトのappパッケージを読み込めるようにする。
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.scanning_mock_service import (  # noqa: E402
    MockDataError, MockRoute, RoutePosition, ScanningMockService,
    load_access_points, load_route,
)

DEFAULT_DATA_DIR = Path(__file__).resolve().parent / "mock_data"


def position_stream(route: MockRoute, scenario: str, loop: bool) -> Iterator[RoutePosition]:
    """シナリオに応じた位置列を返す。"""
    positions = route.positions if scenario != "stationary" else [route.positions[0]] * len(route.positions)
    while True:
        yield from positions
        if not loop:
            break


def send_payload(endpoint: str, payload: dict[str, Any], timeout: float = 10) -> tuple[int, str]:
    """Payloadを最大3回送信し、一時的な通信エラーから復旧する。"""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    for attempt in range(1, 4):
        request = Request(endpoint, data=data, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(request, timeout=timeout) as response:
                response.read()
                return response.status, str(response.reason or "")
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            # 4xxは再送しても改善しないため、その場で内容を表示して終了する。
            if 400 <= exc.code < 500:
                raise RuntimeError(f"HTTP {exc.code}: {body}") from exc
            if attempt == 3:
                raise RuntimeError(f"HTTP {exc.code}: {body}") from exc
        except (URLError, TimeoutError) as exc:
            if attempt == 3:
                raise RuntimeError(f"送信先へ接続できません: {endpoint}: {exc}") from exc
        print(f"送信失敗。再試行します ({attempt}/3)", file=sys.stderr)
        time.sleep(attempt)
    raise RuntimeError("Payloadを送信できませんでした")


def build_parser() -> argparse.ArgumentParser:
    """コマンドライン引数を定義する。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default="http://127.0.0.1:8000/api/scanning")
    parser.add_argument(
        "--client-id", "--client-mac", dest="client_mac",
        default=os.getenv("MERAKI_MOCK_CLIENT_MAC", "mock-user-01"),
        help="clientMacへ設定するAndroidと共通のクライアントID（--client-macも利用可能）",
    )
    parser.add_argument("--network-id", default=os.getenv("MERAKI_MOCK_NETWORK_ID", "L_MOCK_NETWORK"))
    parser.add_argument("--secret", default=os.getenv("MERAKI_MOCK_SECRET", "mock-secret"))
    parser.add_argument("--interval", type=float, default=None, help="経路JSONの待機秒数を上書き")
    parser.add_argument("--route-file", type=Path, default=DEFAULT_DATA_DIR / "floor_1_route.json")
    parser.add_argument("--ap-file", type=Path, default=DEFAULT_DATA_DIR / "ap_positions.json")
    parser.add_argument(
        "--scenario", choices=["normal", "stationary", "location-unavailable", "noisy"], default="normal"
    )
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main() -> int:
    """座標列からPayloadを生成し、指定された受信APIへ順次送信する。"""
    args = build_parser().parse_args()
    if args.interval is not None and args.interval < 0:
        print("--intervalには0以上を指定してください", file=sys.stderr)
        return 2
    try:
        route = load_route(args.route_file)
        service = ScanningMockService(load_access_points(args.ap_file), seed=args.seed)
        for index, position in enumerate(position_stream(route, args.scenario, args.loop)):
            now = datetime.now(timezone.utc)
            payload = service.build_payload(
                route=route, position=position, observed_at=now, client_mac=args.client_mac,
                network_id=args.network_id, secret=args.secret, scenario=args.scenario,
            )
            location = payload["data"]["observations"][0]["locations"]
            x = location[0]["x"] if location else "unavailable"
            y = location[0]["y"] if location else "unavailable"
            if args.dry_run:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
                status = "dry-run"
            else:
                status_code, reason = send_payload(args.endpoint, payload)
                status = f"{status_code} {reason}"
            print(
                f"[{now.astimezone().strftime('%H:%M:%S')}] {args.client_mac} "
                f"-> ({x}, {y}) {status}", file=sys.stderr,
            )
            wait_seconds = 0 if args.dry_run else (args.interval if args.interval is not None else position.wait_seconds)
            # 最終送信後は不要に待たない。ループ時だけ次の周回へ備えて待機する。
            is_last = not args.loop and index == len(route.positions) - 1
            if not is_last and wait_seconds:
                time.sleep(wait_seconds)
    except (MockDataError, RuntimeError) as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nモック送信を終了しました", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
