#!/usr/bin/env python3
"""从 Muse 侧查实时额度，写成本仓库的 quota.json。

只在 Muse agent 所在的机器上运行：它依赖 `subscription-status` 这条
agent 侧通道，桌面 exe 本身是调不到的。脚本本身不联网、不推送、
不含任何凭证，只做一件事：解析命令输出并更新 quota.json。

用法（在仓库根目录）：
    python3 tools/update-quota.py

定时任务（由 agent 的 cron 做，不是由本脚本做）再判断文件有变化
才 git commit + push，这样悬浮窗从 GitHub 拉到的就是近实时的快照。
"""
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

CST = timezone(timedelta(hours=8))
REPO_ROOT = Path(__file__).resolve().parent.parent
QUOTA_PATH = REPO_ROOT / "src" / "MuseQuotaWidget" / "quota.json"


def parse_status(text: str) -> dict:
    """解析 `subscription-status status` 的纯文本输出。"""
    result: dict = {}

    if "does not have a subscription" in text:
        result["plan"] = "免费版（无订阅）"

    m = re.search(r"Usage:\s*([\d.]+)%", text)
    if m:
        used = float(m.group(1))
        result["usedPercent"] = used
        result["remainingPercent"] = round(100 - used, 2)

    m = re.search(
        r"resets\s+([A-Z][a-z]{2})\s+(\d+)\s+at\s+(\d+):(\d+)\s+([AP]M)",
        text,
    )
    if m:
        month = datetime.strptime(m.group(1), "%b").month
        day = int(m.group(2))
        hour = int(m.group(3))
        minute = int(m.group(4))
        if m.group(5) == "PM" and hour != 12:
            hour += 12
        if m.group(5) == "AM" and hour == 12:
            hour = 0
        now = datetime.now(CST)
        reset = datetime(now.year, month, day, hour, minute, tzinfo=CST)
        # 输出给的是“下一次重置”，若算出来已过去，按周额度节奏往后顺延。
        while reset <= now:
            reset += timedelta(days=7)
        result["weeklyResetAt"] = reset.isoformat(timespec="seconds")

    m = re.search(r"Additional tokens:\s*([\d.]+)% used \((.+?) tokens left\)", text)
    if m:
        result["additionalTokensUsedPercent"] = float(m.group(1))
        result["additionalTokensLeft"] = m.group(2).strip()

    result["updatedAt"] = datetime.now(CST).isoformat(timespec="seconds")
    return result


def main() -> int:
    proc = subprocess.run(
        ["subscription-status", "status"],
        capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        print(f"subscription-status 失败：{proc.stderr.strip()}", file=sys.stderr)
        return 1

    parsed = parse_status(proc.stdout)
    if "usedPercent" not in parsed:
        print(f"无法解析额度输出：\n{proc.stdout}", file=sys.stderr)
        return 1

    old = {}
    if QUOTA_PATH.exists():
        try:
            old = json.loads(QUOTA_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            old = {}
    merged = {**old, **parsed}
    # plan 若这次没解析到（例如已订阅后的输出格式变了），保留旧值，不瞎猜。
    if "plan" not in merged:
        merged["plan"] = "免费版（无订阅）"

    QUOTA_PATH.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    changed = merged != old
    print(json.dumps(merged, ensure_ascii=False))
    print("changed" if changed else "unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
