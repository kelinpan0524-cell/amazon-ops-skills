# 上手：从装好到出第一份报告

> 这份文档回答「装完之后要不要配、配什么、怎么配」。具体任务怎么做看 [`WORKFLOWS.md`](WORKFLOWS.md)，
> 换客户端看 [`CLIENTS.md`](CLIENTS.md)，改代码看 [CONTRIBUTING.md](../CONTRIBUTING.md)。

---

## 第 0 步：你是哪种人（决定后面配什么）

| 你是谁 | 你要什么 | 需要配 | 不用配 |
| --- | --- | --- | --- |
| **只想看看** | 试试这东西长什么样 | **什么都不用配** | 密钥、数据源、定时任务 |
| **运营（个人电脑）** | 自己店的日报、Listing 体检、关键词 | 一份自己的数据（CSV 或领星密钥） | 定时任务、汇总机 |
| **多店 / 公司** | 多店总览、周月复盘、统一预警 | 一台固定机器 + 全量店铺权限 | 每台电脑都配 |

**一句话原则**：看自己的店 → 自己电脑 + 自己的数据；看全公司 → 一台固定机器跑汇总
（汇总要全量店铺权限，笔记本合盖就停，不适合）。

---

## 第 1 步：拉下来 + 空跑一遍（所有人，2 分钟）

```bash
git clone <this-repo> && cd amazon-ops-skills
cp config/shops.example.json config/shops.json     # 只是让店铺组名对得上
AMZ_DATA_DIR=examples python3 skills/amz-store-daily/scripts/run.py
```

看到一行 `✓ shop_a → ...html`，就可以用浏览器打开那个文件了。

再跑一次全量自检（合成数据，不碰你的真实数据，约 2 秒）：

```bash
python3 scripts/setup_local.py --allow-incomplete
python3 scripts/selftest.py
```

最后一行是 `全部通过` 才继续。看到 `✗`：先单独跑 `python3 skills/_shared/test_metrics.py`（公式）
和 `python3 scripts/test_import_lingxing.py`（导入），定位是哪一层。

**依赖**：

| 依赖 | 什么时候需要 |
| --- | --- |
| `python3` ≥ 3.9 | 必需（纯标准库，不用装任何包） |
| 领星 / 卖家精灵 密钥 | 只有要自动拉数时才需要；用 CSV 的话完全不用 |
| `openpyxl` | 仅导入 `.xlsx` 时（否则在领星里另存 CSV） |
| `numpy` + `Pillow` | 仅 `amz-listing-images` 的像素校验 |

---

## 第 2 步：三个问题，逐个答

### 问题 1：数据从哪来？

| 选择 | 适合谁 | 怎么做 |
| --- | --- | --- |
| **自己的 CSV** | 没有领星，或想先试 | 按 [`../system/DATA-CONTRACT.md`](../system/DATA-CONTRACT.md) 准备，`AMZ_DATA_DIR` 指过去 |
| **领星 ERP** | 已经在用领星 | 配两个环境变量，跑 `scripts/fetch_lingxing.py --days 30` |
| **卖家精灵** | 要做选品/关键词/竞品调研 | 配密钥，4 个调研技能才会出数 |

配置步骤见 [`DATA-SOURCES.md`](DATA-SOURCES.md)。最短版：

```bash
export LINGXING_MCP_URL="https://openmcp.lingxing.com/mcp-servers/lingxing-mcp"
export LINGXING_MCP_KEY="<你的只读账号密钥>"
python3 scripts/fetch_lingxing.py --days 1 --shops shop_a    # 换成你的店铺组
```

GUI 客户端（Trae / WorkBuddy / 豆包桌面版）拿不到 shell 变量时，把密钥写进
`config/mcp.local.json`（环境变量优先，这个是兜底）。

### 问题 2：要不要配定时任务？

**先不要。** 先用 3 天，每天手工跑一次：

```bash
python3 scripts/fetch_lingxing.py --days 3
python3 skills/amz-alert-center/scripts/run.py
```

觉得「每天都想要」，再用系统的 cron / 计划任务自己排。仓库不替你装 crontab，示例：

```cron
40 5 * * *  cd /path/to/amazon-ops-skills && python3 scripts/fetch_lingxing.py --days 3
15 6 * * *  cd /path/to/amazon-ops-skills && python3 skills/amz-store-daily/scripts/run.py
35 6 * * *  cd /path/to/amazon-ops-skills && python3 skills/amz-alert-center/scripts/run.py
```

预警类脚本退出码 1 = 有 critical/high 要人看，可以据此决定要不要发通知。

### 问题 3：要不要一台汇总机？

只有当「多店汇总」时才有意义：汇总要全量店铺权限，而且必须每天开机。
个人电脑看自己店不需要。

---

## 第 3 步：按角色的最短路径

### 只看看（3 分钟）

1. 跑第 1 步的命令；
2. 打开 `data/reports/shop/shop_a/*.html`；
3. 想换数据就按 [examples/README.md](../examples/README.md) 准备 CSV。

### 运营（30 分钟）

1. 拿自己的领星只读密钥（或导出 CSV）；
2. `python3 scripts/fetch_lingxing.py --days 30`；
3. 把 [CLIENTS.md](CLIENTS.md) 里对应客户端的技能目录指过来，之后直接跟 Agent 说
   「看下昨天怎么样」「哪些 SKU 要补货」。

### 多店 / 公司（半天）

1. 找一台常开的机器（云端或办公室主机）；
2. 配好全量店铺权限的密钥；
3. 排 cron（见问题 2），先只排「拉数 + 预警」，稳定一周再加报告。

---

## 常见坑

| 症状 | 原因 | 怎么办 |
| --- | --- | --- |
| 提示「缺领星凭证」 | GUI 客户端没继承 shell 变量 | 填 `config/mcp.local.json` |
| 「MCP Key无效或已失效」 | 密钥过期/复制不全 | 后台重生成 |
| 报告里「没有数据」 | 没拉数，或 `AMZ_DATA_DIR` 指错了 | 先跑 `fetch_lingxing.py`，或检查目录 |
| `--shop` 报「未知店铺组」 | 名字和 `config/shops.json` 不一致 | 打开 config 看有哪些 key |
| 周报/月报「本期没有数据」 | 默认窗口是本周/本月，而数据只到上周 | 加 `--anchor 2026-11-05` 落在有数据的那一周 |
