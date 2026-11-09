#!/usr/bin/env python3
"""近期店级快照刷新与零值跨源防护的回归测试。"""
import datetime as dt
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import check_data_hygiene as hygiene
import fetch_lingxing as fetch


class RecentCompleteDaysTest(unittest.TestCase):
    def test_excludes_today_and_keeps_requested_window(self):
        self.assertEqual(
            fetch.recent_complete_days(dt.date(2026, 11, 8), 3),
            ["2026-11-05", "2026-11-06", "2026-11-07"],
        )

    def test_rejects_empty_window(self):
        with self.assertRaises(ValueError):
            fetch.recent_complete_days(dt.date(2026, 11, 8), 0)


class ShopZeroGuardTest(unittest.TestCase):
    def setUp(self):
        self.row = {
            "shop": "shop_c", "date": "2026-11-07", "units": 0,
            "revenue": 0, "spend": 0, "ad_sales": 0,
        }

    def test_rejects_zero_shop_when_sku_has_sales(self):
        sku = [{"shop": "shop_c", "date": "2026-11-07", "units": 13, "revenue": 830.22}]
        with self.assertRaisesRegex(RuntimeError, "SKU 明细为 13 件"):
            fetch.validate_shop_row(self.row, sku)

    def test_rejects_zero_shop_without_sku_evidence(self):
        with self.assertRaisesRegex(RuntimeError, "没有可证明真实零销售"):
            fetch.validate_shop_row(self.row, [])

    def test_real_zero_can_be_explicitly_allowed(self):
        fetch.validate_shop_row(self.row, [], allow_zero=True)

    def test_nonzero_shop_does_not_require_sku_equality(self):
        self.row.update(units=23, revenue=1709.06)
        fetch.validate_shop_row(self.row, [])


class MergeRowsTest(unittest.TestCase):
    def test_daily_merge_removes_legacy_today_snapshot(self):
        old_data = fetch.m.DATA
        with tempfile.TemporaryDirectory() as tmp:
            fetch.m.DATA = tmp
            try:
                fetch.merge_rows([
                    {"shop": "shop_a", "date": "2026-11-07", "units": 28, "revenue": 3962.01},
                    {"shop": "shop_a", "date": "2026-11-08", "units": 0, "revenue": 0},
                ])
                fetch.merge_rows(
                    [{"shop": "shop_a", "date": "2026-11-07", "units": 28, "revenue": 3962.01}],
                    drop_dates={"2026-11-08"},
                )
                rows = fetch.m.load("shop_daily")
                self.assertEqual([r["date"] for r in rows], ["2026-11-07"])
            finally:
                fetch.m.DATA = old_data


class ShopSkuHygieneTest(unittest.TestCase):
    def test_flags_zero_shop_contradicted_by_sku(self):
        shop = [{"shop": "shop_a", "date": "2026-11-07", "units": 0, "revenue": 0}]
        sku = [{"shop": "shop_a", "date": "2026-11-07", "units": 21, "revenue": 2992.63}]
        issues = hygiene.check_shop_sku_consistency(shop, sku)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0][:2], ("shop-sku-zero-mismatch", "high"))

    def test_flags_recent_zero_without_cross_source_evidence(self):
        shop = [{"shop": "shop_b", "date": "2026-11-07", "units": 0, "revenue": 0}]
        issues = hygiene.check_shop_sku_consistency(shop, [])
        self.assertEqual(issues[0][:2], ("shop-zero-unverified", "medium"))

    def test_nonzero_shop_is_not_an_issue(self):
        shop = [{"shop": "shop_a", "date": "2026-11-07", "units": 28, "revenue": 3962.01}]
        self.assertEqual(hygiene.check_shop_sku_consistency(shop, []), [])


class DailyBriefSkuTest(unittest.TestCase):
    def test_as_of_is_passed_as_day_not_shop(self):
        run_path = (Path(__file__).resolve().parents[1]
                    / "skills" / "amz-sku-daily" / "scripts" / "run.py")
        spec = importlib.util.spec_from_file_location("daily_brief_run", run_path)
        daily = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(daily)
        tables = {
            "shop_daily": [
                {"shop": "shop_c", "date": "2026-11-06", "units": 1, "revenue": 50, "spend": 5},
                {"shop": "shop_c", "date": "2026-11-07", "units": 2, "revenue": 100, "spend": 10},
            ],
            "sales_daily": [
                {"shop": "shop_c", "date": "2026-11-07", "sku": "REG-SKU",
                 "asin": "B000000001", "units": 2, "revenue": 100, "sessions": 8},
            ],
            "inventory_daily": [
                {"shop": "shop_c", "date": "2026-11-07", "sku": "REG-SKU",
                 "asin": "B000000001", "fba_available": 10},
            ],
            "ads_asin_daily": [],
        }
        saved = {}
        with (mock.patch.object(daily.m, "load", side_effect=lambda name: tables.get(name, [])),
              mock.patch.object(daily.sys, "argv", ["run.py", "--date", "2026-11-07"]),
              mock.patch.object(daily.hr, "save",
                                side_effect=lambda html, path: saved.setdefault("html", html) and path)):
            self.assertEqual(daily.main(), 0)
        self.assertIn("REG-SKU", saved["html"])
        self.assertNotIn("当前日期没有可用的 SKU 明细", saved["html"])


class StoreDailyExitCodeTest(unittest.TestCase):
    """缺数据必须返回 2：返回 0 会让定时任务把「没出报告」当成功（SKILL.md 失败降级表已承诺）。"""

    def _load(self, shops):
        run_path = (Path(__file__).resolve().parents[1]
                    / "skills" / "amz-store-daily" / "scripts" / "run.py")
        spec = importlib.util.spec_from_file_location("store_daily_run", run_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        tmp.write(shops)
        tmp.close()
        self.addCleanup(Path(tmp.name).unlink)
        mod.SHOPS_JSON = Path(tmp.name)
        return mod

    def test_missing_data_returns_two(self):
        mod = self._load('{"shops": {"shop_a": {"display": "A", "sites": "US"}}}')
        with (mock.patch.object(mod.m, "load", return_value=[]),
              mock.patch.object(mod.sys, "argv", ["run.py"])):
            self.assertEqual(mod.main(), 2)

    def test_all_shops_missing_data_returns_two(self):
        mod = self._load('{"shops": {"shop_a": {}, "shop_b": {}}}')
        with (mock.patch.object(mod.m, "load", return_value=[]),
              mock.patch.object(mod.sys, "argv", ["run.py"])):
            self.assertEqual(mod.main(), 2)

    def test_unknown_shop_returns_two(self):
        mod = self._load('{"shops": {"shop_a": {}}}')
        with mock.patch.object(mod.sys, "argv", ["run.py", "--shop", "nosuch"]):
            self.assertEqual(mod.main(), 2)




if __name__ == "__main__":
    unittest.main()
