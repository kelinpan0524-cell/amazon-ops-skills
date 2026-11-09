#!/usr/bin/env python3
"""外部副作用与部分失败的回归测试；全部使用假命令/假客户端，不触网。"""
import csv
import json
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "_shared"))
sys.path.insert(0, str(ROOT / "scripts"))

import metrics as shared_metrics
import package_release as package






class FreshnessTests(unittest.TestCase):
    def test_success_detail_is_not_recorded_as_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_root = shared_metrics.ROOT
            shared_metrics.ROOT = tmp
            try:
                shared_metrics.write_fetch_status(
                    "lingxing", True, "shop_daily 最新 2026-11-05",
                    rows=3, min_date="2026-11-03", max_date="2026-11-04")
                payload = json.loads((Path(tmp) / "data/logs/fetch_status.json").read_text())
            finally:
                shared_metrics.ROOT = old_root
        row = payload["sources"]["lingxing"]
        self.assertEqual(row["error"], "")
        self.assertEqual(row["last_success_date"], "2026-11-04")
        self.assertEqual(row["rows"], 3)

    def test_yesterday_is_normal_without_fetch_status(self):
        result = shared_metrics.data_freshness(1, None)
        self.assertEqual(result["state"], "normal")

    def test_two_day_lag_after_success_is_official_delay(self):
        result = shared_metrics.data_freshness(2, {"status": "success", "attempted_at": "2026-11-04T06:00:00"})
        self.assertEqual(result["state"], "official_delay")
        self.assertEqual(result["level"], "low")

    def test_failed_fetch_is_explicit_even_when_lag_is_one(self):
        result = shared_metrics.data_freshness(1, {
            "status": "failed", "consecutive_failures": 2, "error": "401 unauthorized"
        })
        self.assertEqual(result["state"], "fetch_failed")
        self.assertEqual(result["level"], "high")
        self.assertIn("连续 2 次", result["message"])

    def test_old_lag_with_success_points_to_upstream(self):
        result = shared_metrics.data_freshness(4, {"status": "success", "attempted_at": "2026-11-04T06:00:00"})
        self.assertEqual(result["state"], "official_stale")
        self.assertEqual(result["level"], "high")

    def test_failure_counter_survives_across_attempts(self):
        previous = {"sources": {"lingxing": {
            "status": "failed", "consecutive_failures": 1,
            "last_success_at": "2026-11-03T06:00:00", "last_success_date": "2026-11-02"
        }}}
        result = shared_metrics.next_fetch_status(previous, "lingxing", ok=False, error="timeout")
        row = result["sources"]["lingxing"]
        self.assertEqual(row["consecutive_failures"], 2)
        self.assertEqual(row["last_success_date"], "2026-11-02")




class BusinessPolicyTests(unittest.TestCase):
    def test_sku_and_store_stock_scopes_are_explicit(self):
        cfg = {"stockout": {"sales_window_days": 28, "days_of_supply_critical": 10,
                            "days_of_supply_alert": 21, "low_stock_ratio_vs_28d": 28},
               "store_stock": {"sales_window_days": 7, "days_of_supply_alert": 14}}
        sku = shared_metrics.inventory_policy("sku", cfg)
        store = shared_metrics.inventory_policy("store", cfg)
        self.assertEqual((sku["window"], sku["critical"], sku["watch"], sku["candidate"]), (28, 10, 21, 28))
        self.assertEqual((store["window"], store["risk"]), (7, 14))

    def test_competitor_thresholds_are_config_driven(self):
        cfg = {"competitor": {"price_change_ratio": 0.05, "bsr_change_ratio": 0.4,
                              "rating_drop": 0.3, "gap_widen_usd": 6.0,
                              "gap_widen_ratio": 0.08}}
        self.assertEqual(shared_metrics.competitor_policy(cfg),
                         {"price": 0.05, "bsr": 0.4, "rating": 0.3,
                          "gap_usd": 6.0, "gap_ratio": 0.08})













    def test_stock_business_state_does_not_turn_zero_sales_into_purchase_task(self):
        self.assertEqual(shared_metrics.stock_business_state(0, 5), "已断货")
        self.assertEqual(shared_metrics.stock_business_state(10, 5), "在库将断货")
        self.assertEqual(shared_metrics.stock_business_state(100, 0), "无近28天销量（新品/停售待确认）")



    def test_company_overview_subtitle_comes_from_shop_config(self):
        import importlib.util
        path = Path(__file__).parents[1] / "skills/amz-company-overview/scripts/run.py"
        spec = importlib.util.spec_from_file_location("company_overview_config_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "shops.json"
            cfg.write_text(json.dumps({"shops": {
                "a": {"display": "甲店"}, "b": {"display": "乙店"}}}, ensure_ascii=False), encoding="utf-8")
            module.SHOPS_JSON = cfg
            self.assertEqual(module.shop_subtitle(), "甲店 · 乙店")




    def test_stock_report_uses_only_latest_inventory_snapshot(self):
        import contextlib
        import datetime as dt
        import importlib.util
        import io
        path = Path(__file__).parents[1] / "skills/amz-stock-alert/scripts/run.py"
        spec = importlib.util.spec_from_file_location("stock_report_test", path)
        stock = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(stock)
        today = dt.date.today()
        inv = [
            {"date": (today - dt.timedelta(days=1)).isoformat(), "sku": "SKU1", "asin": "B0TEST", "fba_available": "5"},
            {"date": today.isoformat(), "sku": "SKU1", "asin": "B0TEST", "fba_available": "5"},
        ]
        sales = [{"date": (today - dt.timedelta(days=1)).isoformat(), "sku": "SKU1", "units": "28"}]
        old_load, old_render = stock.m.load, stock.render_html
        stock.m.load = lambda name: inv if name == "inventory_daily" else sales
        stock.render_html = lambda *args: ""
        try:
            with contextlib.redirect_stdout(io.StringIO()) as output:
                rc = stock.main()
        finally:
            stock.m.load, stock.render_html = old_load, old_render
        self.assertEqual(rc, 1)
        self.assertIn("1 个 SKU 需处理", output.getvalue())


class ReleaseBoundaryTests(unittest.TestCase):
    def test_distribution_never_contains_internal_exports(self):
        files = [f.relative_to(package.ROOT).as_posix() for f in package.collect()]
        self.assertFalse(any(p.startswith(("knowledge/", "profiles/", "notes/feishu-kb/")) for p in files))

    def test_examples_csv_ships_but_real_data_does_not(self):
        """examples/ 的合成 CSV 要进包（否则 zip 用户第一条命令就跑不通）；data/ 一律不进。"""
        self.assertFalse(package.should_skip(package.ROOT / "examples" / "shop_daily.csv"))
        self.assertFalse(package.should_skip(package.ROOT / "examples" / "README.md"))
        self.assertTrue(package.should_skip(package.ROOT / "data" / "normalized" / "shop_daily.csv"))
        self.assertTrue(package.should_skip(package.ROOT / "data" / "reports" / "x.html"))

    def test_packager_rejects_internal_cloud_ids_instead_of_masking_them(self):
        import sys
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            secret = root / "docs" / "secret.md"
            secret.parent.mkdir()
            secret.write_text("https://example" + ".feishu.cn/base/" + "ExampleToken1234567890", encoding="utf-8")
            argv = ["package_release.py", "--dry-run", "--out", str(root / "out")]
            with patch.object(package, "ROOT", root), patch.object(package, "collect", return_value=[secret]), patch.object(sys, "argv", argv):
                self.assertEqual(package.main(), 1)
            self.assertFalse((root / "out").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
