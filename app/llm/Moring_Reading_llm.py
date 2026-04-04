import re
from typing import Any

from openai import OpenAI
from app.config import settings


SECTOR_WHITELIST = [
    "半导体", "白酒", "白色家电", "保险", "包装印刷", "厨卫电器", "电池", "电机", "电力", "电网设备", "多元金融", "电子化学品",
    "房地产", "风电设备", "非金属材料", "服装家纺", "纺织制造", "工程机械", "光伏设备", "贵金属", "轨交设备", "港口航运", "公路铁路运输", "钢铁", "光学光电子", "工业金属",
    "环保设备", "环境治理", "互联网电商", "黑色家电", "化学纤维", "化学原料", "化学制品", "化学制药", "IT服务", "机场航运", "军工电子", "军工装备", "家居用品", "计算机设备",
    "金属新材料", "教育", "建筑材料", "建筑装饰",
    "零售", "旅游及酒店", "美容护理", "煤炭开采加工", "贸易", "农产品加工", "农化制品", "能源金属",
    "汽车服务及其他", "汽车零部件", "汽车整车", "其他电源设备", "其他电子", "其他社会服务", "软件开发", "燃气", "塑料制品", "食品加工制造", "生物制品", "石油加工贸易",
    "通信服务", "通信设备", "通用设备",
    "文化传媒", "物流", "消费电子", "小家电", "小金属", "橡胶制品", "元件", "医疗服务", "医疗器械", "饮料制造", "油气开采及服务", "影视院线", "游戏", "银行", "医药商业",
    "养殖业", "自动化设备", "综合", "证券", "中药", "专用设备", "造纸", "种植业与林业",
]

SECTOR_SET = set(SECTOR_WHITELIST)
SECTOR_TEXT = "、".join(SECTOR_WHITELIST)

MAINLINE_PATTERN = re.compile(r"^(第[一二三四五]主线)：\s*(.+?)\s*$", re.MULTILINE)


PROMPT = f"""
# 角色设定
你是一个A股盘前主线提炼助手。

你的任务不是写研报，不是汇总新闻，也不是罗列受益板块，
而是基于“前一交易日复盘 + 今晨盘前材料”，判断今天A股最可能被资金交易出来的方向，
提炼出最值得关注的 5 条交易主线，并按强弱排序。

你关注的核心不是“谁理论受益”，而是：
“今天A股资金最可能先打哪里、谁最容易形成板块联动、谁更可能成为盘中主攻方向”。

---

# 板块名称硬约束（必须严格遵守）
你输出的“第一主线~第五主线”的主线名称，必须严格从以下标准板块名单中选择，且必须原词输出：

{SECTOR_TEXT}

必须遵守：
1. 主线名称只能是上面名单中的一个标准板块名称。
2. 不得输出名单外名称。
3. 不得输出概念题材、自造词、组合词、行业链描述、缩写、近义替换。
4. 不得写“AI算力 / 机器人 / 创新药 / 有色 / 军工 / 券商+金融 / 新能源 / 科技”等非标准板块名称。
5. 每条主线名称只能写一个标准板块，不得并列两个及以上板块。
6. 若新闻对应的是概念或主题，不是标准板块，你必须把它映射为最适合承接该逻辑、且最可能被A股资金实际交易的那个标准板块。
7. “综合”只能作为极少数兜底项，除非确实无法归入其他标准板块，否则不要使用“综合”。

---

# 工作顺序（必须严格遵守）
你必须先做这 3 步内部判断，再输出结果：

## 第一步：先复盘昨天市场已经交易了什么
你必须优先从“前一交易日复盘”中提炼：
- 昨天真正最强的方向是什么
- 哪些方向只是异动，不算主线
- 市场风格偏进攻还是偏防守
- 资金是在抱团、扩散、轮动还是高低切换
- 哪些方向已经被验证有板块联动、涨停扩散、情绪强化

注意：
昨天“已经被资金打出来”的方向，优先级高于今天“新闻看起来很热”的方向。

## 第二步：再判断今晨消息是在强化、切换还是证伪
结合今晨材料，判断今天更可能属于以下哪一种：
- 延续昨天主线
- 强化昨天主线
- 从旧主线切换到新主线
- 风险偏好下降后的防守承接
- 局部事件刺激下的支线轮动

注意：
今晨消息的作用，不是让你重新从零挑主线，
而是判断它对昨天已形成的交易结构，是强化、扩散、切换，还是干扰。

## 第三步：只输出“今天最可能成交”的方向
你最终输出的，必须是：
- 今天A股最可能承接的方向
- 最容易形成板块联动的方向
- 最符合当天市场风格的方向
- 最可能成为盘中资金共识的方向

禁止输出仅仅“逻辑上说得通”但缺乏盘面承接基础的方向。

---

# 核心原则
你必须严格遵守以下原则：

## 1. 先看“昨日真实交易”，再看“今晨新增催化”
如果昨天某板块已经出现：
- 板块涨幅居前
- 涨停家数多
- 封板效率高
- 中军/弹性票共振
- ETF/指数有明显反馈

则默认它具备更高优先级；
除非今晨出现了足以改变市场风格或切换主线的强催化，否则不能轻易把它降级。

## 2. 区分“全球直接受益”和“A股实际承接”
很多消息先利好某个全球资产，但A股未必直接交易那个方向。
你必须优先判断：
- 全球市场直接受益者是谁
- A股最容易映射和承接的是谁
- 谁更容易形成涨停扩散和短线情绪强化
- 谁虽然逻辑正确，但A股资金未必愿意打

## 3. 必须把逻辑链推演完整
对于地缘冲突、商品涨价、政策催化、产业突破等消息，
禁止停留在“某事件利好某板块”这一层。

你必须在内部完成如下推演：
事件/消息
→ 影响的中间变量（价格、供给、需求、盈利预期、风险偏好、政策预期等）
→ A股受影响行业
→ A股资金最可能优先攻击的细分方向
→ 为什么今天资金更可能打这个方向，而不是其他相近方向

## 4. 必须结合当天市场风格排序
你必须判断今天更接近哪种环境：
- 风险偏好提升 / 成长进攻
- 风险偏好回落 / 红利防守
- 资源涨价驱动
- 权重搭台、题材唱戏
- 普涨轮动
- 高低切换
- 局部抱团

如果某个方向逻辑成立，但与当天风格不匹配，则不能排在前面。

## 5. 必须有“主线 / 支线 / 防守 / 观察”意识
不是所有方向都配叫主线。
如果材料不足以支撑 5 条强主线，后面的方向可以是：
- 防守方向
- 事件支线
- 观察方向

但必须明确说明，不要把观察项伪装成强主线。

## 6. 必须进行相近方向比较与淘汰
你必须在内部比较并筛掉“看起来类似但承接更弱”的方向。

## 7. 不要被“新闻热度”误导
新闻多，不代表资金一定打；
消息大，也不代表A股一定选最直接映射。
你必须优先输出“更容易成交”的方向，而不是“更容易讲故事”的方向。

## 8. 严禁硬凑五条强主线
如果今天真正能称为强主线的只有 2~3 条，
那么第 4、5 条可以写成：
- 防守方向
- 观察方向
- 事件支线

但不要为了凑数，把弱逻辑写成主线。

---

# 输出目标
你只需要输出：
- 第一主线
- 第二主线
- 第三主线
- 第四主线
- 第五主线

每条只包含两项：
1. 主线名称
2. 理由（可写成 2~4 句，要求比原版本更详细，重点解释“为什么今天会被交易、为什么排在这个位置”）

---

# 输出要求
1. 必须按交易强弱排序，强弱要拉开，不要平均分配。
2. 理由必须回答“今天为什么会被交易”，不是长期行业介绍。
3. 理由必须体现盘面思维，明确区分：
   - 最强进攻
   - 次强进攻
   - 事件支线
   - 防守承接
   - 观察方向
4. 如果某个方向只是防守，不是主动进攻主线，要明确写“防守承接”。
5. 如果某个方向只是观察，不宜当作强主线追逐，要明确写“观察方向”或“观察级支线”。
6. 不要写个股，不要写总结。
7. 每条理由可以写成 2~4 句完整分析，允许适度展开，不要只写一句结论。
8. 每条理由需要尽可能说清楚以下几个层次中的大部分内容：
   - 昨日盘面是否已有交易基础
   - 今晨消息属于强化、延续、切换还是局部刺激
   - 资金为什么更可能选择这个板块而不是相近方向
   - 这个方向在今天更像主攻、跟风、支线还是防守
   - 若仅为推测逻辑，必须明确写出“推测逻辑”
9. 不要照抄材料原文，要做提炼、比较和归纳。
10. 如果某条逻辑属于推测，必须在理由中明确写“推测逻辑”。
11. 如果今晨消息与昨日主线不一致，必须优先判断是“强化旧主线”还是“切换新主线”，不能简单并列罗列。
12. 如果昨日最强方向今晨没有被证伪，应优先考虑延续，而不是轻易切换。
13. 如果某方向只有消息催化、没有昨日盘面验证、也缺乏板块联动基础，则最多列为观察方向，不得排入前三。
14. 如果某方向看似最直接受益，但A股历史上更常交易其映射分支，则优先写映射分支。
15. “第一主线：XXX”中的 XXX 必须是标准板块名单中的一个原词。
16. 理由可以适当详细，但仍要聚焦“今天为什么会被交易”，不要写成长篇行业科普。
17. 每条理由都应尽量体现“比较后的结论”，即说明为什么它比相近方向更值得今天优先关注。

---

# 输出格式
严格按照下面格式输出，不要增加其他内容：

第一主线：XXX
理由：XXX

第二主线：XXX
理由：XXX

第三主线：XXX
理由：XXX

第四主线：XXX
理由：XXX

第五主线：XXX
理由：XXX
"""


REMAP_PROMPT = f"""
你是A股主线结果修正器。

你的任务不是重新分析市场，而是把已有结果中的“主线名称”修正为标准板块名称。

# 标准板块名单
{SECTOR_TEXT}

# 修正规则
1. 只允许输出名单中的标准板块名称。
2. 不允许输出任何名单外名称。
3. 主线名称必须原词输出，不得扩写、缩写、近义替换、自造组合。
4. 每条主线只能对应一个标准板块名称。
5. 理由保留原意，尽量不要压缩；如果需要微调，只做板块映射修正，不要把原本较详细的理由改短。
6. 保持原有强弱排序不变，除非原排序明显依赖于一个无法成立的板块映射。
7. “综合”只能极少使用，能映射到具体板块就不要用“综合”。

# 输出格式
严格按照下面格式输出，不要增加其他内容：

第一主线：XXX
理由：XXX

第二主线：XXX
理由：XXX

第三主线：XXX
理由：XXX

第四主线：XXX
理由：XXX

第五主线：XXX
理由：XXX
"""


def _extract_mainline_names(text: str) -> list[str]:
    """
    提取：
    第一主线：XXX
    第二主线：XXX
    ...
    """
    if not text:
        return []
    return [name.strip() for _, name in MAINLINE_PATTERN.findall(text)]


def _all_mainlines_in_whitelist(text: str) -> bool:
    """
    要求：
    1. 正好提取到 5 条主线
    2. 每条主线名称都在白名单内
    """
    names = _extract_mainline_names(text)
    if len(names) != 5:
        return False
    return all(name in SECTOR_SET for name in names)


def _normalize_llm_ranking_rows(ranking_payload: dict | None, top_n: int = 12) -> list[dict[str, Any]]:
    if not isinstance(ranking_payload, dict):
        return []

    rows = ranking_payload.get("sector_rankings")
    if not isinstance(rows, list):
        return []

    normalized: list[dict[str, Any]] = []
    for idx, item in enumerate(rows, start=1):
        if not isinstance(item, dict):
            continue

        sector = str(item.get("sector") or "").strip()
        if not sector:
            continue

        rank = item.get("rank")
        if not isinstance(rank, int) or rank <= 0:
            rank = idx

        final_score = item.get("final_score")
        try:
            final_score = round(float(final_score), 2)
        except (TypeError, ValueError):
            final_score = 0.0

        news_count = item.get("news_count")
        try:
            news_count = int(news_count)
        except (TypeError, ValueError):
            news_count = 0
        news_count = max(news_count, 0)

        normalized.append(
            {
                "sector": sector,
                "rank": rank,
                "final_score": final_score,
                "news_count": news_count,
            }
        )

    normalized.sort(key=lambda x: (x["rank"], -x["final_score"], x["sector"]))
    if top_n > 0:
        return normalized[:top_n]
    return normalized


def _format_ranking_for_prompt(title: str, ranking_payload: dict | None) -> str:
    rows = _normalize_llm_ranking_rows(ranking_payload, top_n=12)
    if not rows:
        return f"【{title}】\n无可用数据"

    lines = [f"【{title}】"]
    for item in rows:
        lines.append(
            f"{item['rank']}. {item['sector']} | score={item['final_score']} | news={item['news_count']}"
        )
    return "\n".join(lines)


def _build_user_prompt(
    morning_data: dict,
    prev_day_review: str = "",
    investment_preference_ranking: dict | None = None,
    market_heat_ranking: dict | None = None,
) -> str:
    date_str = morning_data.get("date", "")
    sections = morning_data.get("sections", {})
    investment_ranking_text = _format_ranking_for_prompt(
        "市场投资倾向排行（近72小时）",
        investment_preference_ranking,
    )
    market_heat_ranking_text = _format_ranking_for_prompt(
        "市场热度排行（近72小时）",
        market_heat_ranking,
    )

    return f"""
以下是 {date_str} 的盘前材料，请只提炼今天最值得关注的 5 条交易主线，按强弱排序输出。
不需要复述新闻，但“理由”请尽可能写得更充分一些。
每条理由优先说明：昨日盘面基础、今晨催化性质、A股映射路径、资金为什么更可能打这个方向、它属于主攻/支线/防守/观察中的哪一类。
只保留“主线 + 理由”，不要写额外总结。
注意：你要判断的是“今天A股资金最可能实际交易的方向”，不是“理论上受益的方向”。
若某事件理论上利好A，但A股更可能去做B，请优先输出B。
请先在内部完成“核心变量提炼、A股映射、强弱比较、主线/支线淘汰”后，再输出最终结果。

特别注意：
- 5条“主线名称”必须严格从标准板块名单中选择；
- 不允许输出名单外名称；
- 不允许输出概念题材词，只能输出标准板块名；
- 每条理由可以适当详细，但重点必须始终围绕“今天为什么会被交易、为什么排在这个位置”。

【结构化排行参考（用于强弱排序）】
{investment_ranking_text}

{market_heat_ranking_text}

【前一交易日复盘】
{prev_day_review}

【头部摘要】
{sections.get("head", "")}

【隔夜海外行情动态】
{sections.get("overseas", "")}

【昨日国内行情回顾】
{sections.get("domestic", "")}

【重大新闻汇总】
{sections.get("major_news", "")}

【公司公告】
{sections.get("company_announcements", "")}

【券商观点】
{sections.get("broker_views", "")}

【今日重点关注的财经数据与事件】
{sections.get("calendar", "")}
"""


def _repair_output_to_whitelist(client: OpenAI, raw_output: str) -> str:
    """
    首轮输出若存在非白名单板块名，则做一次“仅修正主线名称”的二次纠偏。
    """
    repair_user_prompt = f"""
下面是一段已经生成好的主线结果，但其中主线名称可能不是标准板块名。
请你只做“板块名标准化修正”，把主线名称修正成标准板块名单中的名称，并保持整体逻辑和排序尽量不变。
如理由已经较详细，请尽量保留，不要压缩成一句特别短的话。

【待修正结果】
{raw_output}
"""

    resp = client.chat.completions.create(
        model="qwen-plus",
        messages=[
            {"role": "system", "content": REMAP_PROMPT},
            {"role": "user", "content": repair_user_prompt},
        ],
        temperature=0.1,
        extra_body={"enable_thinking": True},
    )
    return resp.choices[0].message.content or raw_output


def analyze_morning_data(
    morning_data: dict,
    prev_day_review: str = "",
    investment_preference_ranking: dict | None = None,
    market_heat_ranking: dict | None = None,
) -> str:
    """
    将早盘分段结果 + 前一交易日复盘，一起交给 LLM 分析。
    增加了：
    1. 标准板块白名单硬约束
    2. 输出后校验
    3. 不合规时自动二次修正
    """
    client = OpenAI(
        api_key=settings.api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        timeout=90.0,
    )

    user_prompt = _build_user_prompt(
        morning_data=morning_data,
        prev_day_review=prev_day_review,
        investment_preference_ranking=investment_preference_ranking,
        market_heat_ranking=market_heat_ranking,
    )

    resp = client.chat.completions.create(
        model="qwen-plus",
        messages=[
            {"role": "system", "content": PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
        extra_body={"enable_thinking": True},
    )

    content = resp.choices[0].message.content or ""

    # 首轮不合规，则做一次板块名修正
    if not _all_mainlines_in_whitelist(content):
        repaired = _repair_output_to_whitelist(client, content)
        if _all_mainlines_in_whitelist(repaired):
            return repaired
        return repaired  # 即使仍不完美，也优先返回纠偏后的版本

    return content
