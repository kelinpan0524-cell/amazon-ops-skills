# 换客户端也能跑：Codex / Claude Code / Trae / WorkBuddy / 豆包 / ZCode

> 一句话：**这些技能不挑客户端，也不依赖客户端的 MCP 配置。**
> 技能里的脚本自己用 HTTP 连领星/卖家精灵，客户端只要"能读 SKILL.md、能跑 python3"就行。
> 唯一要按客户端区别处理的，是**技能放哪**和**密钥放哪**。

---

## 1. 为什么不依赖客户端的 MCP 配置

很多人以为"用不了是因为我的 MCP 没配好"。实际不是：

| 你以为的链路 | 实际链路 |
| --- | --- |
| 客户端 MCP → 模型调用 MCP 工具 → 出数据 | `python3 skills/amz-xxx/scripts/run.py` → 脚本自己发 HTTP 到领星/卖家精灵 → 出报告 |

证据：凭证只在 3 个地方被读取，全是 `os.environ` 或本机文件，跟客户端无关——
`skills/_shared/mcp_client.py`、`scripts/fetch_lingxing.py`、`scripts/setup_local.py`。

所以：
- 你在 Codex 里配了领星 MCP，技能**不会**因此变快，也不会因此才能用；
- 你没在 Trae 里配任何 MCP，只要环境里能跑 python3 + 有密钥，技能**照样能用**；
- 反过来，客户端**没有** terminal / code execution，脚本类技能就**真的跑不了**（见第 3 节）。

---

## 2. 按客户端装（三步：放技能 → 给密钥 → 自检）

### 2.1 通用做法

```bash
# ① 放技能：软链进客户端的技能目录（改仓库即生效，不用重装）
python3 scripts/install_skills.py --list          # 看能挂到哪
python3 scripts/install_skills.py --target agents,claude

# ② 给密钥：环境变量或本机文件，二选一（详见第 4 节）
export LINGXING_MCP_URL="https://openmcp.lingxing.com/mcp-servers/lingxing-mcp"
export LINGXING_MCP_KEY="<你的 X-Mcp-Key>"
export SELLERSPRITE_MCP_KEY="<你的 secret-key>"

# ③ 自检：不联网也能过
python3 scripts/setup_local.py
python3 scripts/selftest.py                       # 合成数据跑 10 个技能，约 2 秒
```

### 2.2 各客户端对照

| 客户端 | 技能放哪 | 怎么装 | 能跑脚本吗 | 能用几个技能 |
| --- | --- | --- | --- | --- |
| **ZCode** | `~/.zcode/skills` 或 `~/.agents/skills` | `--target agents` | 能 | 30 个全能用 |
| **Claude Code** | `~/.claude/skills` | `--target claude` | 能 | 30 个全能用 |
| **Codex** | `~/.agents/skills` | `--target agents` | 能 | 30 个全能用 |
| **Trae** | 设置里指定目录 | 指向本仓库 `skills/`，或先 `--target agents` 再指过去 | 能（有终端） | 30 个全能用 |
| **WorkBuddy** | 市场/导入包 | `--pack ~/Desktop/amz-skills.zip` 再导入 | 视版本而定 | 能跑脚本=30 个；没有终端=4 个 |
| **豆包（桌面）** | 拖文件夹导入 | 同上，用 `--pack` | 视版本而定 | 同上 |
| **飞书机器人（示例同学这类）** | 该机器人自己的 skills 目录 | 拷目录 | **不能**（无 terminal/file） | 只有 4 个纯 MCP 技能 + 插件工具 |

> 「4 个纯 MCP 技能」= `amz-brand-analytics`、`amz-keyword-intel`、`amz-product-research`、`amz-review-insight`。
> 它们没有 `scripts/`，全靠客户端自己的 MCP 能力取数——**只有这种客户端才真的需要配 MCP**。

### 2.3 客户端各自的注意点

- **Codex**：技能目录是 `~/.agents/skills`；也可以显式点名 `$amz-ads-diagnose`。Codex 的 MCP 配在 `config.toml`，跟本仓库无关，不配也能跑脚本。
- **Claude Code**：`~/.claude/skills`；项目内也可以放 `.claude/skills`。同名技能会被更靠前的目录遮蔽，改完没效果先查这个。
- **Trae**：没有自动扫描的技能目录，要在设置里手动指一个目录。指到 `<仓库>/skills` 最省事（软链也行）。
- **WorkBuddy / 豆包**：只吃包（zip / 文件夹导入），要用 `--pack`，脚本里会自动带上 `skills/_shared`（少了它所有技能都 import 失败）。
- **软链安装的前提**：仓库目录**不能挪走**。脚本用「自身位置」定位仓库（`Path(__file__).resolve()`），所以软链和任意 cwd 都没问题，但仓库一挪就全断。

---

## 3. 没有 terminal 的客户端怎么办

判断方法：让它在项目里跑一句 `python3 -c "print(1)"`。

- **能跑** → 30 个技能全可用，按第 2 节装。
- **不能跑** → 只剩两条路：
  1. 用 4 个纯 MCP 技能（需要把领星/卖家精灵配进**那个客户端**的 MCP）；
  2. 用它的插件/工具能力（例如飞书机器人侧的 `shop_a_market` 工具），技能只当"口径说明书"用。

技能文档里凡是写「在仓库根执行…」的，都只对**能跑脚本**的客户端有效。

---

## 4. 密钥放哪（两条路，任选）

### 路一：环境变量（推荐给 Shell / cron / CI）

```bash
export LINGXING_MCP_URL="https://openmcp.lingxing.com/mcp-servers/lingxing-mcp"
export LINGXING_MCP_KEY="..."
export SELLERSPRITE_MCP_KEY="..."
```

写进 `~/.zshrc` 后，**终端里**启动的客户端能继承；但 **macOS 上双击启动的 GUI 应用（Trae / WorkBuddy / 豆包桌面版）通常继承不到**——这是最常见的"我明明导出了却提示缺密钥"。

### 路二：本机文件（推荐给 GUI 客户端）

```bash
cp config/mcp.local.example.json config/mcp.local.json
# 编辑 lingxing.key / sellersprite.key
```

```json
{
  "lingxing":     {"url": "https://openmcp.lingxing.com/mcp-servers/lingxing-mcp", "key": "..."},
  "sellersprite": {"url": "https://mcp.sellersprite.com/v2/mcp",                "key": "..."}
}
```

规则：
- **环境变量优先**，文件是兜底；两个都有就用环境变量；
- `config/mcp.local.json` 已进 `.gitignore`，`public_boundary_check` 和 `package_release` 都会拦住它，**不会进 Git、不会进发给同事的 zip**；
- 改完不用重启任何东西，脚本每次现读。

---

## 5. 出问题先看这三条

```bash
python3 scripts/setup_local.py            # ① 它会直说：缺什么、凭证来源是环境变量还是文件
python3 scripts/selftest.py               # ② 合成数据跑一遍，不碰你的真实数据
python3 scripts/fetch_lingxing.py --days 1  # ③ 真连一次（有网才跑）
```

| 症状 | 多半是 | 怎么办 |
| --- | --- | --- |
| 提示「缺领星凭证」 | GUI 客户端没继承 shell 变量 | 走路二，填 `config/mcp.local.json` |
| 提示「MCP Key无效或已失效」 | 密钥过期/复制不全 | 去领星后台重生成，更新环境变量或文件 |
| 技能根本不出现 | 目录不是客户端认的那个 / 同名被遮蔽 | `install_skills.py --list` 对照，或换 `--pack` 导入 |
| 脚本报找不到 `_shared` | 只拷了单个技能目录 | 用 `--pack`（自动带 `_shared`），或整目录软链 |
| 跑出来「没有数据」 | 没拉数 | `python3 scripts/fetch_lingxing.py --days 7` |
