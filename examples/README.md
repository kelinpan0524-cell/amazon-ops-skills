# examples/ —— 合成数据，用来"装完立刻能看见东西"

这里所有 CSV 都是**脚本生成的假数据**：两家假店铺（`shop_a` / `shop_b`）、三个假 SKU、
2026-08-11 ~ 2026-11-08 共 90 天。没有任何真实经营数据，数字之间也不追求业务合理，
只保证**字段结构和真实数据一致**，够跑通所有分析型技能。

## 怎么用

```bash
cp config/shops.example.json config/shops.json      # 只是为了让店铺组名对得上
AMZ_DATA_DIR=examples python3 skills/amz-store-daily/scripts/run.py
```

`AMZ_DATA_DIR` 指向一个装满 CSV 的目录，技能就不再读 `data/normalized/`。

一次跑完主要报告：

```bash
export AMZ_DATA_DIR=examples
python3 skills/amz-store-daily/scripts/run.py
python3 skills/amz-company-overview/scripts/run.py
python3 skills/amz-sku-daily/scripts/run.py
python3 skills/amz-stock-alert/scripts/run.py
python3 skills/amz-alert-center/scripts/run.py
python3 skills/amz-week-month-review/scripts/run.py --period week --anchor 2026-11-05
python3 skills/amz-profit-review/scripts/run.py --anchor 2026-11-05
```

> 说明两件事：
> 1. 报告默认窗口是"本周/本月"，示例数据截止 2026-11-08，所以要带 `--anchor` 才能落在有数据的那一周。
> 2. 需要联网的技能（`amz-competitor-watch`、`amz-keyword-intel` 等）不在这份清单里——它们要卖家精灵密钥。

产物落在 `data/reports/`（这个目录不进 Git）。

## 表说明

| 文件 | 谁在消费 | 说明 |
| --- | --- | --- |
| `shop_daily.csv` | 单店日报、多店总览、预警中心 | 店铺组 × 天，USD，下单口径 |
| `shop_monthly.csv` | 周月复盘、阈值校准、历史基准 | 店铺组 × 月 |
| `sales_daily.csv` | SKU 日报、Listing 体检 | SKU × 天，含流量 |
| `ads_daily.csv` | 广告诊断 | campaign × 天 |
| `ads_asin_daily.csv` | SKU 日报的广告段 | ASIN × campaign × 天 |
| `inventory_daily.csv` | 断货预警、库存分档 | SKU × 天，仅 FBA 可售 |
| `profit_daily.csv` | 利润复盘 | 只统计 `has_cost=1` 的行 |
| `sku_master.csv` | Listing 体检、适配校验 | 商品主数据（含 OE 号/车型） |
| `listing_current.csv` | Listing 体检 | 手工维护的快照 |

字段定义见 `system/DATA-CONTRACT.md`。

## 换成你自己的数据

两条路：

1. **有领星**：配好 `LINGXING_MCP_URL/KEY`，跑 `scripts/fetch_lingxing.py --days 30`，数据进 `data/normalized/`。
2. **没有领星**：按 `system/DATA-CONTRACT.md` 的表结构自己导 CSV，放进任意目录，用 `AMZ_DATA_DIR` 指过去。
