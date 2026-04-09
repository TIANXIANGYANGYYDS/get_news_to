import ast
import json
import re
from typing import Optional, List, Any

from openai import OpenAI
from pydantic import ValidationError

from app.model import CLSTelegraphLLMAnalysis, CLSTelegraphSectorAnalysis
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
    "消费电子": "消费电子",
    "光伏": "光伏设备",
    "锂电": "电池",
    "芯片": "半导体",
    "整车": "汽车整车",
    "创新药": "化学制药",
    "仿制药": "化学制药",
    "疫苗": "生物制品",
    "CXO": "医疗服务",
    "cxo": "医疗服务",
    "军工": "军工装备",
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


def _get_setting(*names, required: bool = False, default=None):
    for name in names:
        value = getattr(settings, name, None)
        if value not in (None, ""):
            return value

    if required:
        raise RuntimeError(f"Missing required settings, tried: {names}")

    return default


def _build_client() -> OpenAI:
    api_key = _get_setting("api_key", "openai_api_key", "llm_api_key", required=True)
    return OpenAI(
        api_key=api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        timeout=90.0,
    )


SYSTEM_PROMPT = f"""
你是一个A股电报分析助手。请把新闻拆分为“逐行业板块分析”。

只输出一个JSON对象，结构必须为：
{{
  "sector_analyses": [
    {{
      "sector": "标准行业板块名称",
      "score": -100到100之间的整数,
      "reason": "必须紧扣本条新闻",
      "companies": ["公司A", "公司B"] 或 null
    }}
  ] 或 null
}}

约束：
1) 一条新闻可命中0~N个板块；只输出真正受影响板块。
2) 同一板块不能重复输出。
3) sector必须从下面名单中选择：{SECTOR_WHITELIST_TEXT}
4) score必须为[-100, 100]整数。
5) reason必须体现“事件->传导路径->交易方向”。
6) companies仅填被新闻直接涉及公司，没有就返回null。
7) 如果新闻无法形成明确板块影响，返回sector_analyses为null。
"""

REPAIR_PROMPT = f"""
你是A股电报分析结果修正器。
请把已有输出修正成目标结构：
{{"sector_analyses": [{{"sector": "...", "score": 10, "reason": "...", "companies": null}}] 或 null}}

修正规则：
- sector必须来自标准名单：{SECTOR_WHITELIST_TEXT}
- 去掉重复sector
- score必须是-100到100整数
- reason不能为空且必须紧扣新闻
- 无明确板块影响时返回sector_analyses为null
"""


def _dedupe_keep_order(items: List[str]) -> List[str]:
    result: List[str] = []
    seen = set()
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _coerce_int(value: Any, default: int = 0) -> int:
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


def _coerce_optional_list(value: Any) -> Optional[List[str]]:
    if value is None:
        return None
    if isinstance(value, list):
        cleaned = [_clean_text(v) for v in value]
        cleaned = [v for v in cleaned if v]
        return cleaned or None
    text = _clean_text(value)
    if not text or text.lower() == "null":
        return None
    parts = re.split(r"[、，,;/；\n]+", text)
    cleaned = [_clean_text(p) for p in parts]
    cleaned = [p for p in cleaned if p]
    return cleaned or None


def _normalize_sector_name(name: str) -> Optional[str]:
    raw = _clean_text(name)
    if not raw:
        return None
    if raw in SECTOR_SET:
        return raw
    if raw in SECTOR_ALIASES:
        return SECTOR_ALIASES[raw]
    compact = re.sub(r"[\s、，,/；;（）()\\\-_—]+", "", raw)
    if compact in SECTOR_SET:
        return compact
    if compact in SECTOR_ALIASES:
        return SECTOR_ALIASES[compact]
    for alias, sector in SECTOR_ALIASES.items():
        if alias in raw or alias in compact:
            return sector
    for sector in SECTOR_WHITELIST:
        if sector in raw:
            return sector
    return None


def _infer_sectors_from_text(content: str) -> List[str]:
    result: List[str] = []
    for pattern, sector in CONTENT_SECTOR_RULES:
        if re.search(pattern, content, flags=re.I):
            result.append(sector)
    return _dedupe_keep_order(result)


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
        payload = ast.literal_eval(json_text)

    if not isinstance(payload, dict):
        raise ValueError(f"LLM payload is not a dict: {type(payload)}")

    return payload


def _infer_direction(content: str) -> int:
    pos_count = sum(1 for kw in STRONG_POSITIVE_KEYWORDS if kw in (content or ""))
    neg_count = sum(1 for kw in STRONG_NEGATIVE_KEYWORDS if kw in (content or ""))
    if pos_count > neg_count:
        return 1
    if neg_count > pos_count:
        return -1
    return 0


def _normalize_companies(companies: Any) -> Optional[List[str]]:
    values = _coerce_optional_list(companies)
    if not values:
        return None
    return _dedupe_keep_order(values)


def _coerce_sector_item(item: Any, *, content: str) -> Optional[CLSTelegraphSectorAnalysis]:
    if not isinstance(item, dict):
        return None

    sector = _normalize_sector_name(item.get("sector"))
    if not sector:
        return None

    score = max(-100, min(100, _coerce_int(item.get("score"), 0)))
    if score == 0:
        direction = _infer_direction(content)
        if direction != 0:
            score = direction * 20

    reason = _clean_text(item.get("reason")) or "未返回有效板块分析理由。"
    companies = _normalize_companies(item.get("companies"))

    return CLSTelegraphSectorAnalysis(
        sector=sector,
        score=score,
        reason=reason,
        companies=companies,
    )


def _coerce_payload_shape(payload: dict, *, content: str, subjects: Optional[List[str]] = None) -> CLSTelegraphLLMAnalysis:
    if not isinstance(payload, dict):
        raise ValueError(f"LLM payload is not a dict: {type(payload)}")

    raw_items = payload.get("sector_analyses")

    # 历史兼容：若模型仍偶发旧结构，自动转为新结构
    if raw_items is None and any(k in payload for k in ("sectors", "score", "reason", "companies")):
        legacy_sectors = _coerce_optional_list(payload.get("sectors"))
        if not legacy_sectors:
            legacy_sectors = []
            for value in subjects or []:
                normalized = _normalize_sector_name(value)
                if normalized:
                    legacy_sectors.append(normalized)
            if not legacy_sectors:
                legacy_sectors = _infer_sectors_from_text(content)

        base_score = max(-100, min(100, _coerce_int(payload.get("score"), 0)))
        base_reason = _clean_text(payload.get("reason")) or "未返回有效板块分析理由。"
        base_companies = _normalize_companies(payload.get("companies"))

        raw_items = [
            {
                "sector": sector,
                "score": base_score,
                "reason": base_reason,
                "companies": base_companies,
            }
            for sector in _dedupe_keep_order(legacy_sectors)
        ] or None

    if raw_items is None:
        inferred = _infer_sectors_from_text(content)
        if inferred:
            direction = _infer_direction(content)
            fallback_score = 20 * direction if direction != 0 else 0
            raw_items = [
                {
                    "sector": sector,
                    "score": fallback_score,
                    "reason": "未命中可靠结构化输出，按内容规则兜底映射板块。",
                    "companies": None,
                }
                for sector in inferred
            ]

    if not isinstance(raw_items, list):
        raw_items = []

    normalized_items: list[CLSTelegraphSectorAnalysis] = []
    seen_sectors = set()
    for item in raw_items:
        normalized_item = _coerce_sector_item(item, content=content)
        if not normalized_item:
            continue
        if normalized_item.sector in seen_sectors:
            continue
        seen_sectors.add(normalized_item.sector)
        normalized_items.append(normalized_item)

    return CLSTelegraphLLMAnalysis(
        sector_analyses=normalized_items or None,
    )


def _call_llm_json(client: OpenAI, messages: list, *, content: str, subjects: Optional[List[str]] = None, temperature: float = 0.2) -> CLSTelegraphLLMAnalysis:
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

    text = resp.choices[0].message.content or ""
    json_text = _extract_json_text(text)
    payload = _parse_json_payload(json_text)
    return _coerce_payload_shape(payload, content=content, subjects=subjects)


def _needs_repair(content: str, payload: CLSTelegraphLLMAnalysis) -> bool:
    items = payload.sector_analyses or []
    if not items:
        return False

    if any(not _clean_text(item.reason) for item in items):
        return True

    if any(item.score == 0 for item in items) and _infer_direction(content) != 0:
        return True

    return False


def _repair_analysis(
    client: OpenAI,
    *,
    content: str,
    subjects: Optional[List[str]],
    first_payload: CLSTelegraphLLMAnalysis,
) -> CLSTelegraphLLMAnalysis:
    user_content = (
        f"主题标签：{json.dumps(subjects or [], ensure_ascii=False)}\\n"
        f"电报内容：{content}\\n\\n"
        f"上一版结果：{json.dumps(first_payload.model_dump(), ensure_ascii=False)}\\n\\n"
        "请按修正规则重新输出一个 JSON 结果。"
    )

    return _call_llm_json(
        client=client,
        messages=[
            {"role": "system", "content": REPAIR_PROMPT},
            {"role": "user", "content": user_content},
        ],
        content=content,
        subjects=subjects,
        temperature=0.1,
    )


def _normalize_analysis_for_output(analysis: CLSTelegraphLLMAnalysis) -> CLSTelegraphLLMAnalysis:
    cleaned: list[CLSTelegraphSectorAnalysis] = []
    seen = set()
    for item in analysis.sector_analyses or []:
        sector = _clean_text(item.sector)
        if not sector or sector in seen:
            continue
        seen.add(sector)
        cleaned.append(
            CLSTelegraphSectorAnalysis(
                sector=sector,
                score=max(-100, min(100, _coerce_int(item.score, 0))),
                reason=_clean_text(item.reason) or "未返回有效板块分析理由。",
                companies=_normalize_companies(item.companies),
            )
        )

    return CLSTelegraphLLMAnalysis(sector_analyses=cleaned or None)


def analyze_cls_telegraph(content: str, subjects: Optional[list[str]] = None) -> CLSTelegraphLLMAnalysis:
    content = (content or "").strip()
    subjects = subjects or []

    if not content:
        return CLSTelegraphLLMAnalysis(sector_analyses=None)

    client = _build_client()
    user_content = f"主题标签：{json.dumps(subjects, ensure_ascii=False)}\\n电报内容：{content}"

    first_analysis = _call_llm_json(
        client=client,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        content=content,
        subjects=subjects,
        temperature=0.15,
    )

    final_analysis = first_analysis
    if _needs_repair(content, first_analysis):
        final_analysis = _repair_analysis(
            client=client,
            content=content,
            subjects=subjects,
            first_payload=first_analysis,
        )

    try:
        analysis = CLSTelegraphLLMAnalysis.model_validate(final_analysis)
    except ValidationError as e:
        raise ValueError(f"Invalid LLM analysis payload after post-process: {e}") from e

    return _normalize_analysis_for_output(analysis)
