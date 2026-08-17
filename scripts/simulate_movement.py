#!/usr/bin/env python3
"""設定可能なモック座標列を、起動中のAPIへ順番に送信する。"""

import argparse
import json
import time
from datetime import datetime, timezone
from urllib.request import Request, urlopen

DEFAULT_POINTS = [(0.0, 0.0), (2.0, 0.0), (4.0, 0.0), (5.0, 2.0)]


def main() -> None:
    """コマンドライン引数を読み込み、移動を模した位置情報を送信する。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--client-id", default="mock-user-01")
    parser.add_argument("--floor-id", default="floor-1")
    args = parser.parse_args()
    for index, (x, y) in enumerate(DEFAULT_POINTS):
        # 各送信時点を観測日時として設定し、Meraki受信時と同じ形式へ寄せる。
        payload = json.dumps({
            "client_id": args.client_id, "floor_id": args.floor_id, "x": x, "y": y,
            "variance": 1.5, "observed_at": datetime.now(timezone.utc).isoformat(),
        }).encode()
        request = Request(
            f"{args.base_url.rstrip('/')}/api/mock/positions", data=payload,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urlopen(request, timeout=10) as response:
            print(response.read().decode())
        if index < len(DEFAULT_POINTS) - 1:
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
