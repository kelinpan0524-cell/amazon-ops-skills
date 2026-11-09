"""合规扫描：报告生成时自动过一遍，命中就挂警告。

**为什么放在报告层而不是技能层**：每个技能各写一份检查，改规则要改 17 处；
挂到 html_report.render() 上，所有报告自动受检，漏不掉。

**检查什么**（只查"写出来的文字"，不替人判断业务合规）：
1. 绝对化用语（best / 100% / guaranteed…）—— 亚马逊会下架、广告会拒登
2. 医疗/功效宣称（cure / treat / FDA approved…）—— 汽配类目基本不该出现
3. 车标品牌名 —— **文字里允许**（fitment 必需），**图片里严禁**；
   这里只标注"出现了品牌名，确认是用在适配说明里"，不当违规
4. 价格承诺（lowest price / price match guarantee）—— 容易被投诉

**不检查**：五点写得对不对、图片里有没有车标（那是 amz-listing-images 的活）、
税务/认证（那是 amz-compliance-tax-logistics 的活）。

用法：
    from compliance import scan
    hits = scan(html_text)      # [{"kind","word","context"}]
"""
from __future__ import annotations

import re

# 绝对化用语：亚马逊 listing 与广告都不允许
# 注意：裸的 "100%" 不算违规——报告里"转化率 100%""完成率 100%"是业务数字。
# 违规的是营销语境：「100% guaranteed」这种承诺，由下面的短语覆盖。
ABSOLUTE = ("best seller", "best-selling", "best selling", "no.1", "number one",
            "#1 ", "100% guaranteed", "100% satisfaction", "guaranteed", "guarantee",
            "perfect fit guarantee", "miraculous", "top rated", "world's best",
            "cheapest", "lowest price")
# 功效/医疗宣称
MEDICAL = ("cure", "treat disease", "fda approved", "medical grade",
           "heal", "therapeutic", "clinically proven")
# 价格承诺
PRICE_PROMISE = ("price match", "lowest price guaranteed", "we beat any price")
# 车标品牌（文字允许，但要确认用在适配说明里）
CAR_BRANDS = ("nissan", "toyota", "honda", "ford", "chevrolet", "chevy", "bmw",
              "audi", "volkswagen", "subaru", "mazda", "hyundai", "kia", "jeep",
              "dodge", "gmc", "buick", "cadillac", "lexus", "infiniti", "acura",
              "mercedes", "porsche", "tesla", "volvo", "mitsubishi")

_TAG_RE = re.compile(r"<[^>]+>")


def _plain(html: str) -> str:
    """去掉标签和脚本，只留人读的文字（脚本里的字符串不该触发合规告警）。"""
    s = re.sub(r"<script[^>]*>.*?</script>", " ", html or "", flags=re.S | re.I)
    s = re.sub(r"<style[^>]*>.*?</style>", " ", s, flags=re.S | re.I)
    return _TAG_RE.sub(" ", s)


def scan(html: str) -> list[dict]:
    """扫一段报告 HTML，返回命中清单。空列表 = 没查出问题。"""
    text = _plain(html)
    low = text.lower()
    hits = []
    for kind, words in (("绝对化用语", ABSOLUTE), ("功效宣称", MEDICAL),
                        ("价格承诺", PRICE_PROMISE)):
        for w in words:
            i = low.find(w)
            if i >= 0:
                hits.append({"kind": kind, "word": w,
                             "context": text[max(0, i - 30):i + len(w) + 30].strip()})
    brands = sorted({b for b in CAR_BRANDS if b in low})
    if brands:
        hits.append({"kind": "车标品牌名（文字允许）", "word": "、".join(brands[:5]),
                     "context": "文字里出现品牌名是 fitment 必需的；"
                                "确认没有把它当创意元素（车标贴纸/logo 风格）即可"})
    return hits


def banner_html(hits: list[dict]) -> str:
    """把命中结果渲染成报告顶部的一条警告。没命中返回空串。"""
    if not hits:
        return ""
    real = [h for h in hits if not h["kind"].startswith("车标品牌名")]
    rows = "".join(
        "<li><b>%s</b>：<code>%s</code> —— …%s…</li>"
        % (h["kind"], h["word"], h["context"][:80]) for h in hits[:6])
    lv = "bad" if real else "warn"
    head = ("合规扫描：%d 处需要注意" % len(hits)) if real else "合规扫描：只命中品牌名（正常）"
    return ('<div class="banner %s" style="margin-bottom:14px">'
            '<b>%s</b><ul class="plain" style="margin:6px 0 0;font-size:12.5px">%s</ul>'
            '<p style="font-size:11.5px;color:#6b7280;margin:6px 0 0">'
            '这是自动扫文字的结果，不是合规结论；图片里的车标/认证/税务问题要另查。</p></div>'
            % (lv, head, rows))
