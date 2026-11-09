#!/usr/bin/env python3
"""第三轮自审：用合成数据把每个技能真跑一遍，断言输出里有该有的东西。

它不碰真实数据（通过 AMZ_DATA_DIR 指向临时目录），跑完自动清理。
跑法：python3 scripts/selftest.py
"""
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FIXTURES = {
    "sales_daily.csv": (
        "date,marketplace,asin,sku,title,sessions,page_views,units,unit_session_pct,revenue,currency\n"
        "2026-11-01,US,B0A,S1,Control Arm,500,700,25,5,1000.00,USD\n"
        "2026-11-02,US,B0A,S1,Control Arm,600,800,30,5,1200.00,USD\n"
        "2026-11-01,US,B0B,S2,Bushing,100,150,2,2,60.00,USD\n"
    ),
    "ads_daily.csv": (
        "date,marketplace,campaign,ad_group,targeting,match_type,impressions,clicks,spend,sales,orders,acos,roas\n"
        "2026-11-01,US,Brand-Auto,ag1,control arm,auto,1000,40,20.00,0.00,0,, \n"
        "2026-11-01,US,Manual-Exact,ag2,control arm for 2015 accord,exact,800,30,15.00,150.00,3,0.10,10\n"
    ),
    "inventory_daily.csv": (
        "date,asin,sku,fba_available,fba_inbound,days_of_supply,sell_through,replenish_suggestion,unit_cost\n"
        "2026-11-02,B0A,S1,15,0,,,,12.5\n"
        "2026-11-02,B0B,S2,5,0,,,,3.0\n"
    ),
    "shop_daily.csv": (
        "shop,date,units,revenue,net_revenue,orders,sessions,page_views,spend,ad_sales,acos,return_rate,fba_available,available_inventory,units_yoy_ratio,fetched_at\n"
        "shop_a,2026-11-02,10,10000,9800,10,120,200,300,1500,0.20,0.05,5000,6000,0.10,2026-11-04 07:00\n"
        "shop_a,2026-11-03,12,12000,11800,12,130,210,320,1600,0.19,0.05,5100,6100,0.10,2026-11-04 07:00\n"
        "shop_b,2026-11-02,20,8000,7900,20,200,300,250,1200,0.21,0.03,1500,1600,0.50,2026-11-04 07:00\n"
        "shop_b,2026-11-03,22,9000,8900,22,210,320,260,1300,0.20,0.03,1600,1700,0.50,2026-11-04 07:00\n"
        "shop_c,2026-11-02,9,5000,4900,9,90,150,180,900,0.20,0.05,1000,1100,0.03,2026-11-04 07:00\n"
        "shop_c,2026-11-03,11,6000,5900,11,100,160,190,1000,0.19,0.05,1100,1200,0.03,2026-11-04 07:00\n"
    ),
    "sku_master.csv": (
        "sku,asin,oe_number,vehicle_make,vehicle_model,year_from,year_to,position,material,cost,list_price,weight_g,certifications,hs_code\n"
        "S1,B0A,51360-TVA-A00,Honda,Accord,2015,2018,Front Left Lower,Aluminum,12.5,30,,IATF,8708999990\n"
        "S2,B0B,,Honda,Civic,,,Front,,3.0,9,,,8708999990\n"
    ),
    "listing_current.csv": (
        "asin,title,bullets_count,description_len,has_a_plus,main_image_path\n"
        "B0A,Short title,3,120,0,/tmp/does-not-exist.jpg\n"
    ),
}

def configured_shop_ids():
    """自测店铺跟随当前配置，兼容分发包的 shop_a/shop_b 占位配置。"""
    try:
        with open(os.path.join(ROOT, "config", "shops.json"), encoding="utf-8") as f:
            ids = list((json.load(f).get("shops") or {}).keys())
            if ids:
                return ids
    except (OSError, json.JSONDecodeError):
        pass
    return ["shop_a", "shop_b"]


def shop_daily_fixture(shop_ids):
    header = ("shop,date,units,revenue,net_revenue,orders,sessions,page_views,spend,ad_sales,"
              "acos,return_rate,fba_available,available_inventory,units_yoy_ratio,fetched_at\n")
    rows = []
    for i, shop in enumerate(shop_ids):
        units = 10 + i * 5
        revenue = 10000 - i * 1000
        for day, delta in (("2026-11-02", 0), ("2026-11-03", 1)):
            u = units + delta * 2
            rev = revenue + delta * 1000
            rows.append("%s,%s,%d,%d,%d,%d,120,200,300,1500,0.20,0.05,5000,6000,0.10,2026-11-04 07:00"
                        % (shop, day, u, rev, rev - 200, u))
    return header + "\n".join(rows) + "\n"


CASES = [
    ("amz-sku-daily", ["daily.html"]),
    ("amz-stock-alert", ["可售", "急（<10 天）", "候选预警", "低库存费"], (0, 1)),
    ("amz-listing-audit", ["Listing 体检", "ASIN"], (0, 1, 2)),
    ("amz-sku-monthly", ["【卖什么】", "【压在哪儿】", "广告花费占销售额"]),
    ("amz-calibration", ["到期待复核", "命中率", "J-20261101-01"]),
    ("amz-store-daily --shop shop_a", ["shop_a"]),
    ("amz-company-overview", ["多店总览"]),
    ("amz-week-month-review --period week --anchor 2026-W45", ["复盘"]),
    # 这三条是预警类：退出码 1 = 扫出了要人处理的项，属于正常工作结果
    ("amz-inventory-alert --format text", ["库存"], (0, 1)),
    ("amz-alert-center --format text", ["经营预警"], (0, 1)),
]


def main():
    tmp = tempfile.mkdtemp(prefix="amz_selftest_")
    data_dir = os.path.join(tmp, "normalized")
    os.makedirs(data_dir)
    shop_ids = configured_shop_ids()
    FIXTURES["shop_daily.csv"] = shop_daily_fixture(shop_ids)
    cases = [(skill.replace("shop_a", shop_ids[0]), [x.replace("shop_a", shop_ids[0]) for x in must])
             if len(case) == 2 else
             (skill.replace("shop_a", shop_ids[0]), [x.replace("shop_a", shop_ids[0]) for x in must], case[2])
             for case in CASES for skill, must in [case[:2]]]
    for name, body in FIXTURES.items():
        with open(os.path.join(data_dir, name), "w") as f:
            f.write(body)

    judge_dir = os.path.join(tmp, "judgements")
    os.makedirs(judge_dir)
    with open(os.path.join(judge_dir, "2026-11-01-ads.md"), "w") as f:
        f.write("---\nid: J-20261101-01\nskill: amz-ads-diagnose\nstatus: open\n"
                "expected: \"否掉高花费词后花费降 20%\"\nreview_on: 2026-01-01\n---\n")
    with open(os.path.join(judge_dir, "2026-10-20-listing.md"), "w") as f:
        f.write("---\nid: J-20261020-01\nskill: amz-listing-audit\nstatus: confirmed\n"
                "expected: \"补 OE 号后转化提升\"\nreview_on: 2026-10-30\n---\n")

    # 自检期间物理禁止写多维表格（防单测往生产表插假记录）
    env = dict(os.environ, AMZ_DATA_DIR=data_dir, AMZ_JUDGE_DIR=judge_dir,
               AMZ_NO_BASE_WRITE="1")
    failed = 0
    for case in cases:
        skill, must = case[0], case[1]
        ok_codes = case[2] if len(case) > 2 else (0,)
        parts = skill.split()  # 支持带参数的 case，如 "amz-store-daily --shop shop_a"
        path = os.path.join(ROOT, "skills", parts[0], "scripts", "run.py")
        if not os.path.exists(path):
            print("✗ %s：没有脚本 %s" % (skill, path))
            failed += 1
            continue
        r = subprocess.run([sys.executable, path] + parts[1:], capture_output=True, text=True, env=env, timeout=60)
        out = r.stdout + r.stderr
        if r.returncode not in ok_codes:
            print("✗ %s：退出码 %d（允许 %s）\n%s" % (
                skill, r.returncode, ok_codes, out[:400]))
            failed += 1
            continue
        missing = [k for k in must if k not in out]
        if missing:
            print("✗ %s：输出缺关键内容 %s\n%s" % (skill, missing, out[:400]))
            failed += 1
        else:
            print("✓ %s（%d 行输出）" % (skill, len(out.splitlines())))

    # 报告内容验证：占位符/空表格/KPI 全 0/合规（排在排版检查之后）
    vr = subprocess.run([sys.executable, os.path.join(ROOT, "scripts/verify_reports.py")],
                        capture_output=True, text=True, env=env, timeout=180)
    vr_lines = [l for l in (vr.stdout or "").splitlines() if l.startswith("合计：")]
    if vr.returncode == 0:
        print("✓ 报告内容自检（%s）" % (vr_lines[0] if vr_lines else "通过"))
    else:
        print("✗ 报告内容自检：%s" % ((vr_lines[0] if vr_lines else (vr.stdout or "")[-200:])))
        failed += 1

    # 算式库单测
    # 文档链接自检：重构后不留死链
    links = subprocess.run([sys.executable, os.path.join(ROOT, "scripts/check_doc_links.py")],
                           capture_output=True, text=True, env=env, timeout=60)
    if links.returncode != 0:
        print("✗ 文档链接自检：有死链\n%s" % (links.stdout[-600:]))
        failed += 1
    else:
        print("✓ 文档链接自检（%s）" % links.stdout.strip().splitlines()[-1])

    # 排版自检：图表文字溢出/重叠（静态估算，防止长数字冲出画布）
    layout = subprocess.run([sys.executable, os.path.join(ROOT, "scripts/check_report_layout.py"), "--strict"],
                            capture_output=True, text=True, env=env, timeout=60)
    if layout.returncode != 0:
        print("✗ 报告排版自检：有文字溢出/重叠\n%s" % (layout.stdout[-800:]))
        failed += 1
    else:
        tail_line = [ln for ln in layout.stdout.splitlines() if ln.startswith("合计")]
        print("✓ 报告排版自检（%s）" % (tail_line[0] if tail_line else "0 问题"))



    # 阈值校准：只在有月度历史时跑（没拉过历史就跳过，不算失败）
    months_csv = os.path.join(ROOT, "data", "normalized", "shop_monthly.csv")
    if os.path.exists(months_csv):
        cal = subprocess.run([sys.executable, os.path.join(ROOT, "scripts/calibrate_thresholds.py")],
                             capture_output=True, text=True, env=env, timeout=60)
        if cal.returncode == 0:
            dist = [ln for ln in cal.stdout.splitlines() if "ACOS   P50" in ln]
            print("✓ 阈值校准自检（%s）" % (dist[0].strip() if dist else "通过"))
        else:
            print("✗ 阈值校准脚本失败\n%s" % (cal.stdout + cal.stderr)[-400:])
            failed += 1
    else:
        print("– 阈值校准：无 shop_monthly（跳过，先跑 fetch_lingxing.py --mode monthly）")

    # 自动发现并跑全部 test_*.py（此前只跑 test_metrics，其余靠人记得手动跑——
    # 等于 thresholds.yaml 改坏了 selftest 还是绿的）
    test_files = sorted(
        set(glob.glob(os.path.join(ROOT, "skills/_shared/test_*.py")))
        | set(glob.glob(os.path.join(ROOT, "scripts/test_*.py")))
        | set(glob.glob(os.path.join(ROOT, "skills/*/scripts/test_*.py"))))
    for tf in test_files:
        rel = os.path.relpath(tf, ROOT)
        try:
            r = subprocess.run([sys.executable, tf], capture_output=True, text=True,
                               timeout=180, env=env, cwd=ROOT)
        except subprocess.TimeoutExpired:
            print("✗ %s 超时" % rel)
            failed += 1
            continue
        out = (r.stdout or "") + (r.stderr or "")
        if r.returncode == 0:
            last = out.strip().splitlines()[-1] if out.strip() else "通过"
            print("✓ %-42s %s" % (rel, last[:56]))
        else:
            print("✗ %s 失败\n%s" % (rel, out[-500:]))
            failed += 1

    shutil.rmtree(tmp, ignore_errors=True)
    print("\n%s" % ("全部通过" if not failed else "%d 项失败" % failed))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
