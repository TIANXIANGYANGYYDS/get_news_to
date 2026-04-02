import ast
import json
import re
from typing import Optional, List

from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError

from app.config import settings


SECTOR_WHITELIST = [
    "半导体", "白酒", "白色家电", "保险", "包装印刷", "厨卫电器", "电池", "电机", "电力", "电网设备", "多元金融", "电子化学品",
    "房地产", "风电设备", "非金属材料", "服装家纺", "纺织制造", "工程机械", "光伏设备", "贵金属", "轨交设备", "港口航运", "公路铁路运输", "钢铁", "光学光电子", "工业金属",
    "环保设备", "环境治理", "互联网电商", "黑色家电", "化学纤维", "化学原料", "化学制品", "化学制药", "化学制品", "化学制药", "IT服务", "机场航运", "军工电子", "军工装备", "家居用品", "计算机设备",
    "金属新材料", "教育", "建筑材料", "建筑装饰",
    "零售", "旅游及酒店", "美容护理", "煤炭开采加工", "贸易", "农产品加工", "农化制品", "能源金属",
    "汽车服务及其他", "汽车零部件", "汽车整车", "其他电源设备", "其他电子", "其他社会服务", "软件开发", "燃气", "塑料制品", "食品加工制造", "生物制品", "石油加工贸易",
    "通信服务", "通信设备", "通用设备",
    "文化传媒", "物流", "消费电子", "小家电", "小金属", "橡胶制品", "元件", "医疗服务", "医疗器械", "饮料制造", "油气开采及服务", "影视院线", "游戏", "银行", "医药商业",
    "养殖业", "自动化设备", "综合", "证券", "中药", "专用设备", "造纸", "种植业与林业",
]
SECTOR_WHITELIST = list(dict.fromkeys(SECTOR_WHITELIST))
SECTOR_SET = set(SECTOR_WHITELIST)
SECTOR_WHITELIST_TEXT = "、".join(SECTOR_WHITELIST)

SECTOR_ALIASES = {
    "猪肉": "养殖业",
    "生猪": "养殖业",
    "猪价": "养殖业",
    "猪周期": "养殖业",
    "养猪": "养殖业",
    "养殖": "养殖业",
    "白电": "白色家电",
    "航运": "港口航运",
    "集运": "港口航运",
    "港口": "港口航运",
    "航空": "机场航运",
    "机场": "机场航运",
    "石油石化": "石油加工贸易",
    "炼化": "石油加工贸易",
    "炼油": "石油加工贸易",
    "油气": "油气开采及服务",
    "天然气": "油气开采及服务",
    "煤炭": "煤炭开采加工",
    "券商": "证券",
    "传媒": "文化传媒",
    "影视": "影视院线",
    "白酒": "白酒",
    "消费电子": "消费电子",
    "光伏": "光伏设备",
    "锂电": "电池",
    "半导体": "半导体",
    "芯片": "半导体",
    "汽车零部件": "汽车零部件",
    "整车": "汽车整车",
    "创新药": "化学制药",
    "仿制药": "化学制药",
    "中药": "中药",
    "疫苗": "生物制品",
    "医疗器械": "医疗器械",
    "医药商业": "医药商业",
    "CXO": "医疗服务",
    "cxo": "医疗服务",
    "军工": "军工装备",
    "军工电子": "军工电子",
    "军工装备": "军工装备",
    "稀土": "小金属",
    "黄金": "贵金属",
    "铜": "工业金属",
    "铝": "工业金属",
    "锌": "工业金属",
    "锂": "能源金属",
    "镍": "能源金属",
    "钴": "能源金属",
    "软件": "软件开发",
    "通信": "通信设备",
}

CONTENT_SECTOR_RULES = [
    (r"(冻猪肉|收储|生猪|猪粮比|猪价|母猪)", "养殖业"),
    (r"(券商|证券公司)", "证券"),
    (r"(煤炭|动力煤|焦煤|焦炭)", "煤炭开采加工"),
    (r"(原油|油气|天然气勘探|油田|钻井)", "油气开采及服务"),
    (r"(石化|炼油|成品油)", "石油加工贸易"),
    (r"(白酒|茅台|五粮液)", "白酒"),
    (r"(电影|票房|院线)", "影视院线"),
    (r"(游戏|版号)", "游戏"),
    (r"(航运|集运|港口)", "港口航运"),
    (r"(机场|航空公司|客运航线)", "机场航运"),
    (r"(消费电子|手机|耳机|平板|可穿戴)", "消费电子"),
    (r"(光伏|组件|硅片|电池片)", "光伏设备"),
    (r"(锂电|电芯|储能电池)", "电池"),
    (r"(半导体|芯片|晶圆|封测)", "半导体"),
    (r"(机器人|工业自动化|自动化产线)", "自动化设备"),
    (r"(创新药|新药|药品获批|仿制药)", "化学制药"),
    (r"(中药|中成药)", "中药"),
    (r"(疫苗|血制品|生物制药)", "生物制品"),
    (r"(医疗器械|器械)", "医疗器械"),
    (r"(SaaS|操作系统|数据库|软件)", "软件开发"),
    (r"(通信设备|光模块|基站|交换机)", "通信设备"),
]

STRONG_POSITIVE_KEYWORDS = [
    "收储", "补贴", "回购", "增持", "中标", "签约", "获批", "批准", "订单",
    "提价", "涨价", "上调", "降息", "降准", "减税", "免税", "落地", "正式实施",
    "量产", "突破", "首个", "首次", "扩产", "投产", "并购", "收购", "超预期",
]
STRONG_NEGATIVE_KEYWORDS = [
    "处罚", "立案", "违约", "爆雷", "停产", "召回", "减持", "制裁", "封禁",
    "禁运", "退市", "裁员", "下修", "终止", "取消订单", "砍单", "亏损扩大",
    "暴雷", "调查", "断供", "事故", "停牌",
]
OFFICIAL_KEYWORDS = [
    "国务院", "国家发改委", "发改委", "财政部", "工信部", "商务部",
    "央行", "证监会", "国家能源局", "农业农村部", "卫健委",
]


def _get_setting(*names, required: bool = False, default=None):
    for name in names:
        value = getattr(settings, name, None)
        if value not in (None, ""):
            return value

    if required:
        raise RuntimeError(f"Missing required settings, tried: {names}")

    return default


def _build_client():
    """
    与 analyze_morning_data 保持一致：
    - 只要 settings.api_key 有值就能跑
    - 默认走 DashScope OpenAI 兼容接口
    """
    api_key = _get_setting(
        "api_key",
        "openai_api_key",
        "llm_api_key",
        required=True,
    )

    return OpenAI(
        api_key=api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        timeout=90.0,
    )


class CLSTelegraphLLMAnalysis(BaseModel):
    score: int = Field(..., ge=-100, le=100, description="利好利空分数，范围 -100~100")
    reason: str = Field(..., min_length=1, description="分析理由")
    companies: Optional[List[str]] = Field(default=None, description="涉及公司，没有则为None")
    sectors: Optional[List[str]] = Field(default=None, description="涉及板块，没有则为None")

    def to_mongo_dict(self) -> dict:
        def clean_list(items: Optional[List[str]]) -> Optional[List[str]]:
            if not items:
                return None

            result = []
            seen = set()
            for item in items:
                item = (item or "").strip()
                if item and item not in seen:
                    seen.add(item)
                    result.append(item)

            return result or None

        return {
            "score": int(self.score),
            "reason": self.reason.strip(),
            "companies": clean_list(self.companies),
            "sectors": clean_list(self.sectors),
        }


SYSTEM_PROMPT = f"""
你是一个面向 A 股事件驱动交易与舆情研判的“财联社电报分析助手”。

你的任务不是概括新闻本身，而是判断这条财联社电报在未来 1~3 个交易日内，
是否会推动 A 股相关板块/公司上涨或下跌，以及这种方向判断的把握有多高。

你必须先在内部做尽可能详细、彻底、结构化的分析，再压缩为最终输出。
但最终仍然只能输出一个 JSON 对象，不能输出任何额外说明、不能 markdown、不能代码块。

给你一条财联社电报，请只输出一个 JSON 对象。

输出字段要求：

1. score
- 整数
- 范围必须在 -100 到 100
- 允许使用 1 分档，即任意整数都可以
- 含义不是“新闻重要性”，而是“未来 1~3 个交易日股价方向判断的概率和把握”
- score > 0：上涨概率/把握
- score < 0：下跌概率/把握
- abs(score) 越大，代表方向越明确、交易胜率越高、越容易被盘面交易
- score = 0：仅限完全无明确方向、无法映射到 A 股、或纯噪音信息

你必须按下面语义理解分数：
- +95 ~ +100：极高把握，近乎明牌强催化
- +90 ~ +94：非常高把握，极可能引发强势上涨
- +80 ~ +89：高把握，大概率上涨
- +70 ~ +79：较高把握，较大概率上涨
- +60 ~ +69：中高把握，有明显上涨概率
- +40 ~ +59：中等把握，有交易价值但不是高胜率
- +20 ~ +39：偏弱正向，有一定上涨预期但不强
- +1 ~ +19：仅轻微正向
- 0：无明确方向
- 负分完全对称理解为下跌概率与把握

2. reason
- 简洁说明打分理由
- 不要太长，2~4句以内
- 理由必须体现“事件 -> 传导路径 -> A 股交易方向/确定性”
- 理由里优先写最核心的判断依据，不要写空话，不要只复述新闻

3. companies
- 数组或 null
- 只填写电报中直接提到、或高度明确映射到的相关公司
- 优先填写与 A 股交易相关、映射关系清晰的公司
- 没有就返回 null

4. sectors
- 数组或 null
- 只能从下面这份标准板块名单中选择，必须原词输出
- 不允许输出概念词、题材词、自造组合词、产业链描述
- 最多返回 3 个，按相关性从高到低排序
- 若确实无法映射到标准板块，才返回 null

标准板块名单：
{SECTOR_WHITELIST_TEXT}

你必须遵循以下规则（这些规则只用于内部分析，不要直接原样输出）：

====================
一、总目标
====================
你评估的不是“新闻本身是否重大”，而是：
1. 该消息能否传导到 A 股
2. 这条消息会不会被市场当成短线交易催化
3. 它更像是情绪修复、预期强化、趋势延续，还是趋势破坏、风险释放
4. 最终相关板块/公司在未来 1~3 个交易日上涨或下跌的概率与把握有多高

如果消息能较清晰映射到 A 股标准板块，且方向明确，就不能机械给 0。
只要存在明确政策、价格、供需、技术突破、订单、监管、收储、补贴、涨价、限产、放量、落地执行等直接催化，通常不应给 0。

====================
二、必须先判断方向
====================
先判断净方向，只能三选一：

1. 明确偏多
- 对 A 股某些板块、某些公司形成正向催化
- 最终 score 为正数

2. 明确偏空
- 对 A 股某些板块、某些公司形成负向压制
- 最终 score 为负数

3. 中性 / 方向不清 / 多空抵消
- 无法映射
- 消息偏噪音
- 多空因素大致对冲
- 最终 score 为 0

注意：
- 只有在存在轻微但可识别的方向时，才允许使用 ±1 到 ±9 这类小分值
- 若 sectors 不为 null，且方向明确，原则上不应输出 0
- 若 sectors 不为 null，且方向明确，abs(score) 原则上不低于 15

====================
三、打分偏好
====================
你必须优先从“交易胜率”出发，而不是从“新闻摘要力度”出发。

以下类型事件，若来源可靠、方向清晰、且能直接映射到 A 股标准板块，通常应给予较高分数，不应机械保守：
1. 国家级 / 部委级明确政策落地
2. 收储、收购、补贴、限产、配额、税收优惠、监管落地
3. 明确涨价 / 跌价并可能驱动产业链利润重估
4. 供需拐点被权威数据或政策显著强化
5. 核心技术突破、量产、订单放量、渗透率跃迁
6. 能直接改变市场对相关板块未来 1~3 个交易日定价预期的消息

其中：
- 高确定性、强映射、强交易性的政策或供需拐点事件，通常应进入 80 分以上区间
- 近乎明牌、方向极清晰、板块承接预期极强的消息，可进入 90 分以上区间
- 旧闻、例行表态、缺乏新增细节、映射很弱、短期不可交易的消息，要明显降分

====================
四、板块映射要求
====================
- 你不能输出“机器人、算力、军工、创新药、新能源、AI、科技、有色”等名单外概念词
- 你必须把概念映射到最贴近、最可能承接交易的标准板块
- 例如：
  - 猪价 / 收储 / 养殖利润修复 -> 养殖业
  - 券商利好 -> 证券
  - 原油勘探 / 油服 -> 油气开采及服务
  - 炼化 / 成品油 -> 石油加工贸易
  - 白酒刺激 -> 白酒
- 若某消息只清晰指向一个板块，就只返回一个板块
- 不要为了凑数返回多个板块

====================
五、reason 的写法要求
====================
reason 必须简洁但有信息量，控制在 2~4句以内。
优先包含以下三层意思：
1. 事件核心是什么
2. 它如何传导到 A 股
3. 为什么这个分数不是更高或更低

避免：
- 单纯复述电报
- 空泛形容词堆砌
- 不说明传导逻辑
- 不说明压分或加分原因

====================
六、最终校验规则
====================
输出前必须自检：

1. 是否只输出一个 JSON 对象
2. 字段名是否严格为：score, reason, companies, sectors
3. score 是否为整数，且在 -100 到 100 之间
4. 是否确实站在 A 股未来 1~3 个交易日交易视角，而不是新闻摘要视角
5. companies 和 sectors 没有时是否为 null
6. sectors 是否全部来自标准板块名单
7. 是否避免把能明确映射板块且方向清晰的消息打成 0
8. 是否避免因为“消息看起来大”就直接高分

最终输出要求：
- 只返回 JSON
- 不要输出任何额外文字
- 不要 markdown
- 不要代码块
- 字段名必须是：score, reason, companies, sectors
- score 一定要是整数
- companies 和 sectors 没有时必须返回 null
"""

REPAIR_PROMPT = f"""
你是一个 A 股财联社电报分析结果修正器。

你的任务不是重新写长分析，而是把一份已有的 JSON 结果修正到更符合以下要求：
1. score 代表未来 1~3 个交易日上涨/下跌概率与把握，不是新闻重要性
2. 只要能映射到标准板块且方向明确，就不能机械给 0
3. 直接政策、收储、补贴、涨价、订单、技术突破、量产、明确监管落地这类强催化，不要明显保守
4. sectors 只能从下面的标准板块名单中选，必须原词输出
5. 最终仍然只能输出一个 JSON 对象，字段固定为：score, reason, companies, sectors

标准板块名单：
{SECTOR_WHITELIST_TEXT}
"""


def _dedupe_keep_order(items: List[str]) -> List[str]:
    result = []
    seen = set()
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _clean_text(value) -> str:
    return str(value or "").strip()


def _coerce_int(value, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(round(value))

    text = _clean_text(value)
    m = re.search(r"-?\d+", text)
    if m:
        try:
            return int(m.group())
        except Exception:
            return default
    return default


def _coerce_optional_list(value) -> Optional[List[str]]:
    if value is None:
        return None

    if isinstance(value, list):
        items = [_clean_text(v) for v in value]
        items = [v for v in items if v]
        return items or None

    text = _clean_text(value)
    if not text or text.lower() == "null":
        return None

    # 尽量兼容 "A、B、C" / "A,B,C"
    parts = re.split(r"[、，,;/；\n]+", text)
    parts = [_clean_text(p) for p in parts]
    parts = [p for p in parts if p]
    return parts or None


def _coerce_payload_shape(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError(f"LLM payload is not a dict: {type(payload)}")

    return {
        "score": _coerce_int(payload.get("score"), default=0),
        "reason": _clean_text(payload.get("reason")) or "未返回有效分析理由。",
        "companies": _coerce_optional_list(payload.get("companies")),
        "sectors": _coerce_optional_list(payload.get("sectors")),
    }


def _normalize_company_list(items: Optional[List[str]]) -> Optional[List[str]]:
    if not items:
        return None

    result = []
    for item in items:
        item = _clean_text(item)
        if item:
            result.append(item)

    result = _dedupe_keep_order(result)
    return result or None


def _normalize_sector_name(name: str) -> Optional[str]:
    raw = _clean_text(name)
    if not raw:
        return None

    if raw in SECTOR_SET:
        return raw

    for sector in SECTOR_WHITELIST:
        if sector in raw:
            return sector

    compact = re.sub(r"[\s、，,/；;（）()\-_—]+", "", raw)
    if compact in SECTOR_SET:
        return compact

    if compact in SECTOR_ALIASES:
        return SECTOR_ALIASES[compact]

    for alias, sector in SECTOR_ALIASES.items():
        if alias in raw or alias in compact:
            return sector

    return None


def _infer_sectors_from_text(content: str) -> List[str]:
    result = []
    for pattern, sector in CONTENT_SECTOR_RULES:
        if re.search(pattern, content, flags=re.I):
            result.append(sector)
    return _dedupe_keep_order(result)[:3]


def _normalize_sector_list(
    items: Optional[List[str]],
    *,
    content: str = "",
    subjects: Optional[List[str]] = None,
) -> Optional[List[str]]:
    result = []

    if items:
        for item in items:
            normalized = _normalize_sector_name(item)
            if normalized:
                result.append(normalized)

    if not result and subjects:
        for subject in subjects:
            normalized = _normalize_sector_name(subject)
            if normalized:
                result.append(normalized)

    if not result and content:
        result.extend(_infer_sectors_from_text(content))

    result = _dedupe_keep_order(result)[:3]
    return result or None


def _extract_json_text(text: str) -> str:
    text = (text or "").strip()

    if not text:
        raise ValueError("LLM returned empty content")

    fence_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.S)
    if fence_match:
        return fence_match.group(1).strip()

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start:end + 1].strip()

    raise ValueError(f"Cannot extract JSON from LLM output: {text}")


def _parse_json_payload(json_text: str) -> dict:
    try:
        payload = json.loads(json_text)
    except json.JSONDecodeError:
        # 兼容模型偶发输出 Python 风格字面量：None / True / False
        payload = ast.literal_eval(json_text)

    if not isinstance(payload, dict):
        raise ValueError(f"LLM payload is not a dict: {type(payload)}")

    return payload


def _call_llm_json(client: OpenAI, messages: list, temperature: float = 0.2) -> dict:
    request_kwargs = {
        "model": "qwen-plus",
        "messages": messages,
        "temperature": temperature,
        "extra_body": {"enable_thinking": True},
    }

    try:
        resp = client.chat.completions.create(
            **request_kwargs,
            response_format={"type": "json_object"},
        )
    except Exception:
        resp = client.chat.completions.create(**request_kwargs)

    text = resp.choices[0].message.content
    json_text = _extract_json_text(text)
    payload = _parse_json_payload(json_text)
    return _coerce_payload_shape(payload)


def _infer_direction(content: str) -> int:
    text = content or ""

    pos_count = sum(1 for kw in STRONG_POSITIVE_KEYWORDS if kw in text)
    neg_count = sum(1 for kw in STRONG_NEGATIVE_KEYWORDS if kw in text)

    if pos_count > neg_count:
        return 1
    if neg_count > pos_count:
        return -1
    return 0


def _has_official_source(content: str) -> bool:
    return any(kw in (content or "") for kw in OFFICIAL_KEYWORDS)


def _has_numeric_detail(content: str) -> bool:
    return bool(re.search(r"\d", content or ""))


def _is_strong_event(content: str) -> bool:
    text = content or ""
    strong_pos = any(kw in text for kw in STRONG_POSITIVE_KEYWORDS)
    strong_neg = any(kw in text for kw in STRONG_NEGATIVE_KEYWORDS)

    if strong_pos or strong_neg:
        if _has_official_source(text) or _has_numeric_detail(text):
            return True

    # 少数典型高交易性关键词，单独放宽
    hard_patterns = [
        r"收储", r"中标", r"量产", r"获批", r"回购", r"增持", r"提价", r"涨价",
        r"降息", r"降准", r"停产", r"处罚", r"立案", r"制裁", r"订单", r"断供",
    ]
    return any(re.search(p, text) for p in hard_patterns)


def _needs_repair(
    content: str,
    raw_payload: dict,
    normalized_payload: dict,
) -> bool:
    raw_sectors = raw_payload.get("sectors") or []
    normalized_sectors = normalized_payload.get("sectors") or []
    raw_score = _coerce_int(raw_payload.get("score"), 0)

    # 原始结果给了板块，但映射后全失效，说明板块不规范
    if raw_sectors and not normalized_sectors:
        return True

    # 能映射板块但给 0，触发纠偏
    if normalized_sectors and raw_score == 0:
        return True

    # 明显强事件但分数过于保守，触发纠偏
    if normalized_sectors and _is_strong_event(content) and abs(raw_score) < 45:
        return True

    return False


def _post_process_payload(
    payload: dict,
    *,
    content: str,
    subjects: Optional[List[str]] = None,
) -> dict:
    score = max(-100, min(100, _coerce_int(payload.get("score"), 0)))
    reason = _clean_text(payload.get("reason")) or "未返回有效分析理由。"
    companies = _normalize_company_list(_coerce_optional_list(payload.get("companies")))
    sectors = _normalize_sector_list(
        _coerce_optional_list(payload.get("sectors")),
        content=content,
        subjects=subjects or [],
    )

    # 兜底：只要能明确映射板块且方向清晰，不允许最后还是 0
    if score == 0 and sectors:
        direction = _infer_direction(content)
        if direction != 0:
            score = direction * (35 if _is_strong_event(content) else 15)

    return {
        "score": max(-100, min(100, int(score))),
        "reason": reason,
        "companies": companies,
        "sectors": sectors,
    }


def _repair_analysis(
    client: OpenAI,
    *,
    content: str,
    subjects: Optional[List[str]],
    first_payload: dict,
) -> dict:
    user_content = (
        f"主题标签：{json.dumps(subjects or [], ensure_ascii=False)}\n"
        f"电报内容：{content}\n\n"
        f"上一版结果：{json.dumps(first_payload, ensure_ascii=False)}\n\n"
        "请按修正规则重新输出一个 JSON 结果。"
    )

    repaired_payload = _call_llm_json(
        client=client,
        messages=[
            {"role": "system", "content": REPAIR_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=0.1,
    )
    return repaired_payload


def analyze_cls_telegraph(content: str, subjects: Optional[list[str]] = None) -> dict:
    content = (content or "").strip()
    subjects = subjects or []

    if not content:
        return {
            "score": 0,
            "reason": "电报内容为空，未执行有效分析。",
            "companies": None,
            "sectors": None,
        }

    client = _build_client()

    user_content = (
        f"主题标签：{json.dumps(subjects, ensure_ascii=False)}\n"
        f"电报内容：{content}"
    )

    # 第一轮
    first_payload = _call_llm_json(
        client=client,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=0.15,
    )

    normalized_first = _post_process_payload(
        first_payload,
        content=content,
        subjects=subjects,
    )

    final_payload = normalized_first

    # 必要时二次纠偏
    if _needs_repair(content, first_payload, normalized_first):
        repaired_raw = _repair_analysis(
            client=client,
            content=content,
            subjects=subjects,
            first_payload=normalized_first,
        )
        final_payload = _post_process_payload(
            repaired_raw,
            content=content,
            subjects=subjects,
        )

    # 最终再走一次 Pydantic 兜底校验
    try:
        analysis = CLSTelegraphLLMAnalysis.model_validate(final_payload)
    except ValidationError as e:
        raise ValueError(f"Invalid LLM analysis payload after post-process: {e}") from e

    return analysis.to_mongo_dict()