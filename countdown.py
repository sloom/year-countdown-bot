"""今年の残り日数と割合を計算し、Discord の Webhook に投稿する。

標準ライブラリだけで動く。日付はすべて日本時間（Asia/Tokyo）で扱う。
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Callable, Mapping

# 日本は夏時間がないので UTC+9 固定でよい（zoneinfo/tzdata に依存しない）
JST = timezone(timedelta(hours=9), "JST")

DEFAULT_MILESTONES = "100,50,30,10,1"
# Discord のメッセージフラグ SUPPRESS_NOTIFICATIONS（通知を鳴らさない）
SUPPRESS_NOTIFICATIONS = 1 << 12
USER_AGENT = "DiscordBot (https://github.com/sloom/year-countdown-bot, 1.0)"


def today_jst(now: datetime | None = None) -> date:
    """日本時間での今日の日付を返す。実行環境のタイムゾーンには依存しない。"""
    if now is None:
        now = datetime.now(timezone.utc)
    return now.astimezone(JST).date()


def remaining_days(d: date) -> tuple[int, int]:
    """(残り日数, 年の総日数) を返す。残り日数は当日を含めて数える。"""
    total = (date(d.year + 1, 1, 1) - date(d.year, 1, 1)).days
    day_of_year = d.timetuple().tm_yday
    return total - day_of_year + 1, total


def remaining_percent(remaining: int, total: int) -> str:
    """残り日数 ÷ 総日数 を百分率にし、小数第1位まで四捨五入した文字列を返す。"""
    ratio = Decimal(remaining * 100) / Decimal(total)
    return str(ratio.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def build_message(d: date) -> str:
    """投稿する文面を組み立てる。"""
    remaining, total = remaining_days(d)
    percent = remaining_percent(remaining, total)
    return (
        f"{d.year}年{d.month}月{d.day}日になりました。"
        f"今年は残り{remaining}日です。あと{percent}%です。"
    )


def parse_milestones(value: str | None) -> set[int]:
    """MILESTONE_DAYS（カンマ区切り）をパースする。空なら初期値を使う。"""
    if not value or not value.strip():
        value = DEFAULT_MILESTONES
    try:
        return {int(x) for x in value.split(",") if x.strip()}
    except ValueError:
        raise ValueError(
            f"MILESTONE_DAYS は数値のカンマ区切りで指定してください: {value!r}"
        ) from None


def should_post(remaining: int, mode: str | None, milestones: set[int]) -> bool:
    """POST_MODE に応じて、この残り日数で投稿するかを判定する。"""
    mode = (mode or "daily").strip().lower()
    if mode == "daily":
        return True
    if mode == "milestones":
        return remaining in milestones
    raise ValueError(
        f"POST_MODE は daily か milestones を指定してください: {mode!r}"
    )


def parse_silent(value: str | None) -> bool:
    """SILENT をパースする。空なら false。"""
    v = (value or "false").strip().lower()
    if v in ("true", "false"):
        return v == "true"
    raise ValueError(f"SILENT は true か false を指定してください: {value!r}")


def build_payload(message: str, silent: bool) -> dict:
    """Discord Webhook に送る JSON を組み立てる。"""
    payload: dict = {"content": message}
    if silent:
        payload["flags"] = SUPPRESS_NOTIFICATIONS
    return payload


def post_to_discord(url: str, payload: dict) -> None:
    """Discord Webhook に投稿する。失敗時は例外を送出する。"""
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30):
        pass


def _describe_error(e: Exception) -> str:
    """Webhook URL を含みうる例外メッセージは出さず、安全な情報だけを返す。"""
    if isinstance(e, urllib.error.HTTPError):
        return f"HTTP {e.code}"
    return type(e).__name__


def main(
    argv: list[str] | None = None,
    env: Mapping[str, str] | None = None,
    now: datetime | None = None,
    sender: Callable[[str, dict], None] = post_to_discord,
) -> int:
    parser = argparse.ArgumentParser(description="今年の残り日数を Discord に投稿する")
    parser.add_argument("--date", default="", help="対象日 YYYY-MM-DD（省略時は日本時間の今日）")
    parser.add_argument("--dry-run", action="store_true", help="投稿せず文面を表示する")
    args = parser.parse_args(argv)
    if env is None:
        env = os.environ

    try:
        if args.date.strip():
            try:
                target = date.fromisoformat(args.date.strip())
            except ValueError:
                raise ValueError(
                    f"日付は YYYY-MM-DD 形式で指定してください: {args.date!r}"
                ) from None
        else:
            target = today_jst(now)
        milestones = parse_milestones(env.get("MILESTONE_DAYS"))
        silent = parse_silent(env.get("SILENT"))
        remaining, _ = remaining_days(target)
        post = should_post(remaining, env.get("POST_MODE"), milestones)
    except ValueError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1

    message = build_message(target)
    print(message)
    if not post:
        print(f"残り{remaining}日は節目ではないため、投稿をスキップしました。")
        return 0
    if args.dry_run:
        print(f"確認モードのため投稿しませんでした。（SILENT={str(silent).lower()}）")
        return 0

    url = (env.get("DISCORD_WEBHOOK_URL") or "").strip()
    if not url:
        print("エラー: DISCORD_WEBHOOK_URL が設定されていません。", file=sys.stderr)
        return 1
    try:
        sender(url, build_payload(message, silent))
    except Exception as e:  # noqa: BLE001 - 原因を問わず URL を漏らさず失敗させる
        print(f"エラー: Discord への投稿に失敗しました（{_describe_error(e)}）。", file=sys.stderr)
        return 1
    print("Discord に投稿しました。")
    return 0


if __name__ == "__main__":
    # Windows のコンソールでも文字化けしないよう UTF-8 で出力する
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
