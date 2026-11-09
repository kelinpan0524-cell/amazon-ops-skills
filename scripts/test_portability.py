#!/usr/bin/env python3
"""任意 Agent 克隆后可配置的契约测试；不联网、不写外部系统。"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import os

import public_boundary_check as boundary  # noqa: E402
import setup_local as sl  # noqa: E402

sys.path.insert(0, str(ROOT / "skills" / "_shared"))
import mcp_client as mc  # noqa: E402


class CredentialSourceTests(unittest.TestCase):
    """换客户端（Trae / WorkBuddy 等 GUI）拿不到 shell 变量时，靠 config/mcp.local.json 兜底。

    优先级必须固定：环境变量 > 本机文件，否则设了全局变量的机器会被一份旧文件悄悄覆盖。
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(setattr, mc, "_secrets_cache", None)
        self.file = Path(self.tmp.name) / "mcp.local.json"

    def _use_file(self, data):
        self.file.write_text(json.dumps(data), encoding="utf-8")
        mc.LOCAL_SECRETS = self.file
        mc._secrets_cache = None

    def test_env_wins_over_local_file(self):
        self._use_file({"lingxing": {"url": "https://file.example", "key": "file-key"}})
        with mock.patch.dict(os.environ, {"LINGXING_MCP_URL": "https://env.example",
                                          "LINGXING_MCP_KEY": "env-key"}):
            self.assertEqual(mc.credential("lingxing", "LINGXING_MCP_URL", "LINGXING_MCP_KEY"),
                             ("https://env.example", "env-key"))

    def test_falls_back_to_local_file(self):
        self._use_file({"lingxing": {"url": "https://file.example", "key": "file-key"}})
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(mc.credential("lingxing", "LINGXING_MCP_URL", "LINGXING_MCP_KEY"),
                             ("https://file.example", "file-key"))

    def test_missing_everything_is_empty_not_crash(self):
        mc.LOCAL_SECRETS = self.file          # 文件不存在
        mc._secrets_cache = None
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(mc.credential("lingxing", "LINGXING_MCP_URL", "LINGXING_MCP_KEY"),
                             ("", ""))

    def test_broken_json_does_not_break_everything(self):
        self.file.write_text("{ not json", encoding="utf-8")
        mc.LOCAL_SECRETS = self.file
        mc._secrets_cache = None
        with mock.patch.dict(os.environ, {"LINGXING_MCP_KEY": "env-key"}):
            url, key = mc.credential("lingxing", "LINGXING_MCP_URL", "LINGXING_MCP_KEY")
        self.assertEqual(key, "env-key")
        self.assertEqual(url, "")              # 领星没默认 url，宁缺勿猜

    def test_sellersprite_keeps_public_default_url(self):
        mc.LOCAL_SECRETS = self.file
        mc._secrets_cache = None
        with mock.patch.dict(os.environ, {"SELLERSPRITE_MCP_KEY": "k"}, clear=True):
            url, key = mc.credential("sellersprite", "SELLERSPRITE_MCP_URL", "SELLERSPRITE_MCP_KEY",
                                     default_url="https://mcp.sellersprite.com/v2/mcp")
        self.assertEqual((url, key), ("https://mcp.sellersprite.com/v2/mcp", "k"))


class LocalBootstrapTests(unittest.TestCase):
    def test_bootstrap_covers_every_private_config_and_preserves_existing(self):
        with tempfile.TemporaryDirectory() as td:
            config = Path(td) / "config"
            config.mkdir()
            for src in (ROOT / "config").glob("*.example.json"):
                shutil.copyfile(src, config / src.name)
            existing = config / "targets.json"
            existing.write_text('{"company": {"acos_target": 0.15}}\n', encoding="utf-8")
            with mock.patch.object(sl, "CONFIG", config), mock.patch("sys.stdout"):
                sl.TODO.clear()
                sl.ensure_config()
            for name in ("shops", "targets", "competitors", "mcp.local"):
                self.assertTrue((config / (name + ".json")).is_file(), name)
            self.assertEqual(json.loads(existing.read_text(encoding="utf-8"))["company"]["acos_target"],
                             0.15)

    def test_allow_incomplete_is_automation_friendly(self):
        with tempfile.TemporaryDirectory() as td:
            config = Path(td) / "config"
            config.mkdir()
            for src in (ROOT / "config").glob("*.example.json"):
                shutil.copyfile(src, config / src.name)
            with mock.patch.object(sl, "CONFIG", config), mock.patch.object(
                    sys, "argv", ["setup_local.py", "--allow-incomplete"]), mock.patch("sys.stdout"):
                sl.TODO.clear()
                rc = sl.main()
            self.assertEqual(rc, 0)



class PortableInstallTests(unittest.TestCase):


    def test_archive_helpers_do_not_bind_a_machine_home(self):
        rels = ("archive/2026-11-04-feishu-kb-scripts/build_knowledge_tree.py",
                "archive/2026-11-04-feishu-kb-scripts/fetch_feishu_kb.py")
        # archive/ 是内部留档，package_release 会排除；发给同事的 zip 里没有它。
        # 整目录都不在就跳过（分发包装机后的首跑验收），在就照样逐个校验。
        if not (ROOT / "archive").is_dir():
            self.skipTest("无 archive/（分发安装包），跳过留档脚本检查")
        for rel in rels:
            text = (ROOT / rel).read_text(encoding="utf-8")
            self.assertNotIn("/" + "Users/", text, rel)
            self.assertNotIn("/" + "home/", text, rel)

    def test_public_boundary_rejects_machine_specific_paths(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bad = root / "scripts"
            bad.mkdir()
            (bad / "bad.py").write_text('ROOT = "/' + 'Users/example/checkout"\n', encoding="utf-8")
            with mock.patch.object(boundary, "ROOT", root), mock.patch.object(
                    boundary.subprocess, "check_output", return_value="scripts/bad.py\n"), mock.patch("sys.stdout"):
                self.assertEqual(boundary.main(), 1)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print("全部通过" if result.wasSuccessful() else "存在失败用例")
    sys.exit(0 if result.wasSuccessful() else 1)
