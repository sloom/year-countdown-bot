"""countdown モジュールのテスト。

テストリスト:
- [ ] 残り日数・総日数（当日を含める）
    - 2026-11-12 → 残り50日 / 365日
    - 2026-01-01 → 残り365日
    - 2026-12-31 → 残り1日
    - 2028-02-29, 2028-12-31 → 総日数366日
- [ ] 割合（小数第1位、四捨五入）
    - 2026-11-12 → 13.7 / 2026-01-01 → 100.0 / 2026-12-31 → 0.3
    - ちょうど .x5 になるときに切り上がる（銀行丸めではない）
- [ ] 文面
    - 「2026年11月12日になりました。今年は残り50日です。あと13.7%です。」
    - 月日はゼロ埋めしない
    - 12/31 は末尾に「今年も一年お疲れさまでした。」を足す（うるう年も同じ）
    - 1/1 は日付の直後に「あけましておめでとうございます。」を入れる
- [ ] JST の今日
    - UTC 15:00 は翌日の JST 0:00 になる
    - UTC 14:59 はまだ当日
- [ ] 投稿判定
    - daily は常に投稿 / 空文字は daily 扱い
    - milestones は MILESTONE_DAYS に含まれる日だけ投稿
    - 不正な POST_MODE はエラー
- [ ] MILESTONE_DAYS のパース
    - 「100,50,30,10,1」/ 空白混じり / 空文字は初期値 / 数字以外はエラー
- [ ] Discord ペイロード
    - SILENT=false なら flags なし、true なら flags=4096
- [ ] main
    - 日付指定 + dry-run は投稿せず文面を出力する
    - 節目でない日は milestones モードで投稿しない
    - Webhook URL 未設定で投稿しようとしたらエラー、URL をログに出さない
    - 不正な日付指定はエラー
"""

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime, timezone

from countdown import (
    build_message,
    build_payload,
    main,
    parse_milestones,
    parse_silent,
    remaining_days,
    remaining_percent,
    should_post,
    today_jst,
)


class RemainingDaysTest(unittest.TestCase):
    def test_2026_11_12(self):
        self.assertEqual(remaining_days(date(2026, 11, 12)), (50, 365))

    def test_first_day_of_year(self):
        self.assertEqual(remaining_days(date(2026, 1, 1)), (365, 365))

    def test_last_day_of_year(self):
        self.assertEqual(remaining_days(date(2026, 12, 31)), (1, 365))

    def test_leap_day(self):
        # 2028-02-29 は通算60日目 → 366 - 60 + 1 = 307
        self.assertEqual(remaining_days(date(2028, 2, 29)), (307, 366))

    def test_last_day_of_leap_year(self):
        self.assertEqual(remaining_days(date(2028, 12, 31)), (1, 366))


class RemainingPercentTest(unittest.TestCase):
    def test_2026_11_12(self):
        self.assertEqual(remaining_percent(50, 365), "13.7")

    def test_first_day_of_year(self):
        self.assertEqual(remaining_percent(365, 365), "100.0")

    def test_last_day_of_year(self):
        self.assertEqual(remaining_percent(1, 365), "0.3")

    def test_last_day_of_leap_year(self):
        self.assertEqual(remaining_percent(1, 366), "0.3")

    def test_rounds_half_up_not_to_even(self):
        # 1/16 = 6.25%。銀行丸めだと 6.2 になってしまう
        self.assertEqual(remaining_percent(1, 16), "6.3")


class BuildMessageTest(unittest.TestCase):
    def test_2026_11_12(self):
        self.assertEqual(
            build_message(date(2026, 11, 12)),
            "2026年11月12日になりました。今年は残り50日です。あと13.7%です。",
        )

    def test_month_and_day_are_not_zero_padded(self):
        self.assertEqual(
            build_message(date(2026, 2, 3)),
            "2026年2月3日になりました。今年は残り332日です。あと91.0%です。",
        )

    def test_new_years_eve_adds_closing_greeting(self):
        self.assertEqual(
            build_message(date(2026, 12, 31)),
            "2026年12月31日になりました。今年は残り1日です。あと0.3%です。"
            "今年も一年お疲れさまでした。",
        )

    def test_new_years_eve_in_leap_year(self):
        self.assertEqual(
            build_message(date(2028, 12, 31)),
            "2028年12月31日になりました。今年は残り1日です。あと0.3%です。"
            "今年も一年お疲れさまでした。",
        )

    def test_new_years_day_adds_greeting_after_date(self):
        self.assertEqual(
            build_message(date(2027, 1, 1)),
            "2027年1月1日になりました。あけましておめでとうございます。"
            "今年は残り365日です。あと100.0%です。",
        )

    def test_day_before_new_years_eve_has_no_greeting(self):
        self.assertEqual(
            build_message(date(2026, 12, 30)),
            "2026年12月30日になりました。今年は残り2日です。あと0.5%です。",
        )


class TodayJstTest(unittest.TestCase):
    def test_utc_1500_is_next_day_in_jst(self):
        now = datetime(2026, 11, 11, 15, 0, tzinfo=timezone.utc)
        self.assertEqual(today_jst(now), date(2026, 11, 12))

    def test_utc_1459_is_still_same_day_in_jst(self):
        now = datetime(2026, 11, 11, 14, 59, tzinfo=timezone.utc)
        self.assertEqual(today_jst(now), date(2026, 11, 11))

    def test_new_year_in_jst(self):
        now = datetime(2026, 12, 31, 15, 0, tzinfo=timezone.utc)
        self.assertEqual(today_jst(now), date(2027, 1, 1))


class ParseMilestonesTest(unittest.TestCase):
    def test_comma_separated(self):
        self.assertEqual(parse_milestones("100,50,30,10,1"), {100, 50, 30, 10, 1})

    def test_spaces_are_ignored(self):
        self.assertEqual(parse_milestones(" 100 , 50 ,1 "), {100, 50, 1})

    def test_empty_uses_default(self):
        self.assertEqual(parse_milestones(""), {100, 50, 30, 10, 1})
        self.assertEqual(parse_milestones(None), {100, 50, 30, 10, 1})

    def test_non_number_is_error(self):
        with self.assertRaises(ValueError):
            parse_milestones("100,fifty")


class ShouldPostTest(unittest.TestCase):
    def test_daily_always_posts(self):
        self.assertTrue(should_post(123, "daily", {100}))

    def test_empty_mode_is_daily(self):
        self.assertTrue(should_post(123, "", {100}))
        self.assertTrue(should_post(123, None, {100}))

    def test_milestones_posts_only_on_milestone(self):
        self.assertTrue(should_post(50, "milestones", {100, 50}))
        self.assertFalse(should_post(49, "milestones", {100, 50}))

    def test_unknown_mode_is_error(self):
        with self.assertRaises(ValueError):
            should_post(50, "weekly", {50})


class ParseSilentTest(unittest.TestCase):
    def test_values(self):
        self.assertTrue(parse_silent("true"))
        self.assertTrue(parse_silent("TRUE"))
        self.assertFalse(parse_silent("false"))
        self.assertFalse(parse_silent(""))
        self.assertFalse(parse_silent(None))

    def test_unknown_is_error(self):
        with self.assertRaises(ValueError):
            parse_silent("yes")


class BuildPayloadTest(unittest.TestCase):
    def test_not_silent(self):
        self.assertEqual(build_payload("hi", silent=False), {"content": "hi"})

    def test_silent_adds_suppress_notifications_flag(self):
        self.assertEqual(
            build_payload("hi", silent=True), {"content": "hi", "flags": 4096}
        )


SECRET_URL = "https://discord.com/api/webhooks/123/very-secret-token"
NOW = datetime(2026, 11, 11, 15, 0, tzinfo=timezone.utc)  # JST 2026-11-12 0:00


class MainTest(unittest.TestCase):
    def run_main(self, argv, env):
        sent = []
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(
                argv,
                env=env,
                now=NOW,
                sender=lambda url, payload: sent.append((url, payload)),
            )
        return code, sent, out.getvalue(), err.getvalue()

    def test_posts_today_message_by_default(self):
        code, sent, out, _ = self.run_main([], {"DISCORD_WEBHOOK_URL": SECRET_URL})
        self.assertEqual(code, 0)
        self.assertEqual(
            sent,
            [(SECRET_URL, {"content": "2026年11月12日になりました。今年は残り50日です。あと13.7%です。"})],
        )
        self.assertNotIn(SECRET_URL, out)

    def test_silent_setting_is_applied(self):
        _, sent, _, _ = self.run_main(
            [], {"DISCORD_WEBHOOK_URL": SECRET_URL, "SILENT": "true"}
        )
        self.assertEqual(sent[0][1]["flags"], 4096)

    def test_dry_run_with_date_prints_without_posting(self):
        code, sent, out, _ = self.run_main(["--date", "2028-12-31", "--dry-run"], {})
        self.assertEqual(code, 0)
        self.assertEqual(sent, [])
        self.assertIn("2028年12月31日になりました。今年は残り1日です。あと0.3%です。", out)

    def test_empty_date_argument_means_today(self):
        _, _, out, _ = self.run_main(["--date", "", "--dry-run"], {})
        self.assertIn("2026年11月12日", out)

    def test_milestones_mode_skips_non_milestone_day(self):
        code, sent, out, _ = self.run_main(
            ["--date", "2026-11-13"],
            {"DISCORD_WEBHOOK_URL": SECRET_URL, "POST_MODE": "milestones"},
        )
        self.assertEqual(code, 0)
        self.assertEqual(sent, [])
        self.assertIn("スキップ", out)

    def test_milestones_mode_posts_on_custom_milestone(self):
        _, sent, _, _ = self.run_main(
            ["--date", "2026-11-13"],
            {
                "DISCORD_WEBHOOK_URL": SECRET_URL,
                "POST_MODE": "milestones",
                "MILESTONE_DAYS": "49",
            },
        )
        self.assertEqual(len(sent), 1)

    def test_missing_webhook_url_is_error(self):
        code, sent, _, err = self.run_main([], {})
        self.assertEqual(code, 1)
        self.assertEqual(sent, [])
        self.assertIn("DISCORD_WEBHOOK_URL", err)

    def test_invalid_date_is_error(self):
        code, _, _, err = self.run_main(["--date", "2026-02-30", "--dry-run"], {})
        self.assertEqual(code, 1)
        self.assertIn("2026-02-30", err)

    def test_invalid_setting_is_error(self):
        code, _, _, err = self.run_main(["--dry-run"], {"POST_MODE": "weekly"})
        self.assertEqual(code, 1)
        self.assertIn("POST_MODE", err)

    def test_send_failure_does_not_leak_url(self):
        def failing_sender(url, payload):
            raise RuntimeError(f"failed: {url}")

        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            code = main([], env={"DISCORD_WEBHOOK_URL": SECRET_URL}, now=NOW, sender=failing_sender)
        self.assertEqual(code, 1)
        self.assertNotIn("very-secret-token", err.getvalue())


if __name__ == "__main__":
    unittest.main()
