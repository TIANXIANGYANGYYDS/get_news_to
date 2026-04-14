from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from typing import Any, List, Optional, Literal

from openai import OpenAI
from pydantic import BaseModel, Field, ConfigDict, ValidationError, field_validator

from app.config import settings


SYS = """
你是一个只依据 Price Action 规则工作的 A 股交易分析器。

你的唯一任务是：
判断“**当前是否是买点**”。

你必须严格遵守 Price Action 分析框架，尤其遵守以下原则：
- 先背景，后信号
- 先通道，后形态，最后才看单根K线
- 单根K线不能脱离结构独立判断
- 你不是预测未来走势
- 你不是主观评论员
- 你不是技术指标解说员
- 你只判断：**当前是否满足买入条件**

---

## 一、禁止事项

禁止输出以下内容：
- 任何涨跌预测
- 任何“偏多、偏空、看涨、看跌、可能上涨、可能下跌、后面大概率怎么走”之类表述
- 任何脱离 Price Action 规则的主观猜测
- 任何“看起来很强”“感觉企稳了”“量价不错”之类非结构化表述
- 任何基于单根K线直接下买点结论
- 任何模糊执行建议，例如：
  - “可关注”
  - “可以考虑”
  - “谨慎参与”
  - “适当低吸”
  - “如果激进可以试错”
- 任何不基于结构的止损与卖出位
- 任何长篇教学解释

---

## 二、固定分析顺序（不得省略，不得打乱）

你必须严格按以下顺序输出分析：

1. 通道情况
2. 形态学情况
3. 关键节点K线 / 蜡烛图
4. 最终是否构成买点

---

## 三、买点判定铁律

### 1. 先看背景，后看信号
- 单根K线不能单独决定买点
- 任何买点都必须先服从当前通道背景与整体结构
- 如果背景不支持多头，即使出现强阳线，也不能直接判定为买点

### 2. 买点只允许来自以下三类，不得扩展

#### A. 趋势中的回调买点
只允许以下结构归入此类：
- H2
- 牛旗
- 楔形牛旗
- 首次回调

要求：
- 必须先有明确上行背景或多头控制背景
- 回调必须是趋势中的回调，而不是震荡中部来回波动
- 回调结束必须出现可执行的结构性恢复信号
- 若仍处于下降通道压制下，则不能算趋势回调买点

#### B. 有效突破后的买点
要求：
- 必须先有明确突破
- 必须有 follow-through
- 突破后不能立刻跌回突破位下方
- 若突破质量不足、突破后马上失败、或仍在区间中部，则不算买点

#### C. 有跟随确认的强反转买点
要求：
- 必须同时具备：反转结构 + 强信号K + follow-through
- 只有单根反转K，不构成买点
- 如果仍处于明显下降通道中，且结构未完成扭转，则不能算反转买点

---

## 四、以下情况一律判定为“不买”

出现以下任一情况，必须直接判定为“不买”：
- 处于震荡中部
- 处于下降通道中，且尚未完成有效反转
- 只有单根强阳线，没有 follow-through
- 突破失败
- 突破质量不足
- 形态尚未完成
- 买点类型不属于允许的三类
- 止损位无法清晰定义
- 卖出位无法基于结构清晰定义

---

## 五、止损位与卖出位规则（必须结构化生成）

### 止损位必须基于以下三类之一：
- 关键低点 / 摆动低点
- 形态失效位
- 突破失效位

### 卖出位必须基于以下三类之一：
- 前高 / 关键压力位
- 形态高度测算位
- 区间上沿 / 关键阻力位

禁止输出：
- “止损可适当放宽”
- “卖出可视情况而定”
- “看盘中情况处理”
- “止损自行控制”
- “目标位大概在附近”

如果止损位或卖出位不能依据结构明确给出，则直接判定为“不买”。

---

## 六、A股场景补充约束

在 A 股图表分析中：
- 只基于价格结构、通道、形态、关键K线判断
- 不引入消息面、基本面、题材面、情绪面、成交量故事作为买点依据
- 不因为“涨停板、长阳线、放量阳线”就直接视为买点
- 任何结论都必须回到 Price Action 允许的三类买点中
- 如果图表结构不完整、关键信息不足、关键前高前低不清晰，则按“不买”处理

---

## 七、判断标准

你的任务不是找“看起来还行的机会”，而是只回答：

- 当前是否已经构成**可执行买点**
- 如果没有，则现在就是“不买”
- 只有当背景、形态、信号、follow-through、止损位、卖出位全部满足时，才能输出“买”

标准要严格，不要放宽。

---

## 八、输出要求（这里改成 JSON 输出，但分析逻辑一点不变）

你必须只输出一个 JSON 对象，不能输出任何额外文字、不能 markdown、不能代码块。

JSON 字段必须严格为：

{
  "conclusion": "买 或 不买",
  "current_channel": "字符串",
  "channel_support_buy": "字符串",
  "current_pattern": "字符串",
  "pattern_allowed_type": "字符串",
  "key_candle": "字符串",
  "has_follow_through": "字符串",
  "can_trigger_buy": "字符串",
  "expected_entry": "字符串或null",
  "trigger_condition": "字符串或null",
  "buy_price": "字符串或null",
  "stop_loss": "字符串或null",
  "take_profit": "字符串或null",
  "reason": "字符串"
}

要求：
1. conclusion 只能是 “买” 或 “不买”
2. 如果 conclusion = “不买”，则 expected_entry、trigger_condition 必须尽量给出，buy_price、stop_loss、take_profit 必须为 null
3. 如果 conclusion = “买”，则 buy_price、stop_loss、take_profit 必须给出，expected_entry、trigger_condition 必须为 null
4. 所有字段必须和你的分析一致
5. 不允许输出 JSON 以外的任何内容

---

## 九、输出风格要求

- 简洁
- 确定
- 可执行
- 不教学
- 不展开长篇解释
- 不重复输入条件
- 不输出模糊判断
- 最终只能给出“买”或“不买”

---

## 十、最终裁决规则

只有同时满足以下条件，才允许输出“买”：
1. 通道背景支持
2. 当前形态属于三类允许买点之一
3. 关键K线有效
4. 有明确 follow-through
5. 买入位置可执行
6. 止损位可结构化定义
7. 卖出位可结构化定义

只要有任意一条不满足，必须输出：
- 结论：不买
"""

USER_TEMPLATE = """
请严格按照既定 Price Action 买点规则，判断下面这张 A 股图表 **现在是否是买点**。

你只能判断“当前是否满足买入条件”，不能预测未来走势。

分析对象：
- 标的：{symbol}
- 周期：{period}
- 当前价格：{current_price}
- 最近关键高点：{recent_high}
- 最近关键低点：{recent_low}
- 当前图表描述：
{chart_description}

请严格按以下顺序分析，不得省略：
1. 通道情况
2. 形态学情况
3. 关键节点K线 / 蜡烛图
4. 最终是否构成买点
"""

REPAIR_SYSTEM_PROMPT = """
你是一个 Price Action 买点分析结果修正器。

你的任务不是重做分析，而是把上一版结果修正为一个合法 JSON，且必须满足：
1. 只能输出一个 JSON 对象
2. 字段必须严格为：
   conclusion, current_channel, channel_support_buy, current_pattern,
   pattern_allowed_type, key_candle, has_follow_through, can_trigger_buy,
   expected_entry, trigger_condition, buy_price, stop_loss, take_profit, reason
3. conclusion 只能是 买 或 不买
4. 如果 conclusion = 不买：
   - expected_entry 必须尽量给出
   - trigger_condition 必须尽量给出
   - buy_price, stop_loss, take_profit 必须为 null
5. 如果 conclusion = 买：
   - buy_price, stop_loss, take_profit 必须给出
   - expected_entry, trigger_condition 必须为 null
6. 不要输出任何额外说明，不要 markdown，不要代码块
"""


class KLineBar(BaseModel):
    model_config = ConfigDict(extra="ignore")

    trade_date: str = Field(..., description="交易日期，YYYY-MM-DD")
    open_price: float = Field(..., description="开盘价")
    high_price: float = Field(..., description="最高价")
    low_price: float = Field(..., description="最低价")
    close_price: float = Field(..., description="收盘价")

    @field_validator("high_price")
    @classmethod
    def validate_high_price(cls, v: float, info):
        low_price = info.data.get("low_price")
        open_price = info.data.get("open_price")
        close_price = info.data.get("close_price")
        if low_price is not None and v < low_price:
            raise ValueError("high_price 不能小于 low_price")
        if open_price is not None and v < open_price:
            raise ValueError("high_price 不能小于 open_price")
        if close_price is not None and v < close_price:
            raise ValueError("high_price 不能小于 close_price")
        return v

    @field_validator("low_price")
    @classmethod
    def validate_low_price(cls, v: float, info):
        open_price = info.data.get("open_price")
        close_price = info.data.get("close_price")
        if open_price is not None and v > open_price:
            raise ValueError("low_price 不能大于 open_price")
        if close_price is not None and v > close_price:
            raise ValueError("low_price 不能大于 close_price")
        return v


class PriceActionInput(BaseModel):
    symbol: str = Field(..., description="股票代码或标的名称")
    period: str = Field(default="日线", description="周期，默认日线")
    bars: List[KLineBar] = Field(..., description="按时间升序排列的K线数据，建议约三个月")
    recent_high: Optional[float] = Field(default=None, description="可选，外部显式传入最近关键高点")
    recent_low: Optional[float] = Field(default=None, description="可选，外部显式传入最近关键低点")

    @field_validator("bars")
    @classmethod
    def validate_bars(cls, v: List[KLineBar]):
        if len(v) < 20:
            raise ValueError("bars 至少需要 20 根，建议 40~80 根")
        return v


class PriceActionLLMAnalysis(BaseModel):
    conclusion: Literal["买", "不买"] = Field(..., description="最终结论")
    current_channel: str = Field(..., description="当前通道")
    channel_support_buy: str = Field(..., description="是否支持买入")
    current_pattern: str = Field(..., description="当前形态")
    pattern_allowed_type: str = Field(..., description="是否属于允许的买点类型")
    key_candle: str = Field(..., description="关键K线")
    has_follow_through: str = Field(..., description="是否有 follow-through")
    can_trigger_buy: str = Field(..., description="是否足以触发买点")
    expected_entry: Optional[str] = Field(default=None, description="不买时的预期买入位置")
    trigger_condition: Optional[str] = Field(default=None, description="不买时的触发条件")
    buy_price: Optional[str] = Field(default=None, description="买入位置")
    stop_loss: Optional[str] = Field(default=None, description="止损位")
    take_profit: Optional[str] = Field(default=None, description="卖出位")
    reason: str = Field(..., description="理由")


class PriceActionAnalysisResult(BaseModel):
    input_payload: PriceActionInput
    chart_description: str
    llm_analysis: PriceActionLLMAnalysis
    formatted_markdown: str


def _build_client() -> OpenAI:
    api_key = (settings.api_key or "").strip()
    if not api_key:
        raise RuntimeError("settings.api_key 为空，请检查 .env 中的 API_KEY")

    return OpenAI(
        api_key=api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        timeout=120.0,
    )


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _extract_json_text(text: str) -> str:
    text = (text or "").strip()
    if not text:
        raise ValueError("LLM 返回为空")

    fence_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.S)
    if fence_match:
        return fence_match.group(1).strip()

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start:end + 1].strip()

    raise ValueError(f"无法从输出中提取 JSON: {text}")


def _parse_json_payload(json_text: str) -> dict:
    try:
        payload = json.loads(json_text)
    except json.JSONDecodeError:
        payload = ast.literal_eval(json_text)

    if not isinstance(payload, dict):
        raise ValueError(f"解析结果不是 dict: {type(payload)}")

    return payload


def _normalize_optional_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = _clean_text(value)
    if not text or text.lower() == "null":
        return None
    return text


def _coerce_payload_shape(payload: dict) -> PriceActionLLMAnalysis:
    if not isinstance(payload, dict):
        raise ValueError(f"payload 不是 dict: {type(payload)}")

    conclusion = _clean_text(payload.get("conclusion"))
    if conclusion not in ("买", "不买"):
        conclusion = "不买"

    result = PriceActionLLMAnalysis(
        conclusion=conclusion,
        current_channel=_clean_text(payload.get("current_channel")) or "未明确说明",
        channel_support_buy=_clean_text(payload.get("channel_support_buy")) or "否",
        current_pattern=_clean_text(payload.get("current_pattern")) or "未明确说明",
        pattern_allowed_type=_clean_text(payload.get("pattern_allowed_type")) or "否",
        key_candle=_clean_text(payload.get("key_candle")) or "未明确说明",
        has_follow_through=_clean_text(payload.get("has_follow_through")) or "否",
        can_trigger_buy=_clean_text(payload.get("can_trigger_buy")) or "否",
        expected_entry=_normalize_optional_str(payload.get("expected_entry")),
        trigger_condition=_normalize_optional_str(payload.get("trigger_condition")),
        buy_price=_normalize_optional_str(payload.get("buy_price")),
        stop_loss=_normalize_optional_str(payload.get("stop_loss")),
        take_profit=_normalize_optional_str(payload.get("take_profit")),
        reason=_clean_text(payload.get("reason")) or "未返回有效理由",
    )

    return _post_process_analysis(result)


def _post_process_analysis(analysis: PriceActionLLMAnalysis) -> PriceActionLLMAnalysis:
    data = analysis.model_dump()

    if data["conclusion"] == "买":
        data["expected_entry"] = None
        data["trigger_condition"] = None

        if not data["buy_price"] or not data["stop_loss"] or not data["take_profit"]:
            data["conclusion"] = "不买"

    if data["conclusion"] == "不买":
        data["buy_price"] = None
        data["stop_loss"] = None
        data["take_profit"] = None
        if not data["expected_entry"]:
            data["expected_entry"] = "等待关键位置出现可执行买点后再介入"
        if not data["trigger_condition"]:
            data["trigger_condition"] = "需先完成结构确认并出现有效 follow-through"

    return PriceActionLLMAnalysis(**data)


def _repair_analysis(
    client: OpenAI,
    *,
    model: str,
    raw_text: str,
    error_message: str,
) -> PriceActionLLMAnalysis:
    user_content = (
        f"上一版模型原始输出：\n{raw_text}\n\n"
        f"错误信息：{error_message}\n\n"
        "请修正为合法 JSON。"
    )

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": REPAIR_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=0.0,
    )

    text = resp.choices[0].message.content or ""
    json_text = _extract_json_text(text)
    payload = _parse_json_payload(json_text)
    return _coerce_payload_shape(payload)


def _format_markdown(analysis: PriceActionLLMAnalysis) -> str:
    lines = [
        "# 是否是买点",
        f"- 结论：{analysis.conclusion}",
        "",
        "# 通道情况",
        f"- 当前通道：{analysis.current_channel}",
        f"- 是否支持买入：{analysis.channel_support_buy}",
        "",
        "# 形态学情况",
        f"- 当前形态：{analysis.current_pattern}",
        f"- 是否属于允许的买点类型：{analysis.pattern_allowed_type}",
        "",
        "# 关键节点K线",
        f"- 关键K线：{analysis.key_candle}",
        f"- 是否有 follow-through：{analysis.has_follow_through}",
        f"- 是否足以触发买点：{analysis.can_trigger_buy}",
        "",
        "# 执行结论",
    ]

    if analysis.conclusion == "买":
        lines.extend(
            [
                f"- 买入位置：{analysis.buy_price}",
                f"- 止损位：{analysis.stop_loss}",
                f"- 卖出位：{analysis.take_profit}",
                f"- 理由：{analysis.reason}",
            ]
        )
    else:
        lines.extend(
            [
                f"- 预期买入位置：{analysis.expected_entry}",
                f"- 触发条件：{analysis.trigger_condition}",
                f"- 理由：{analysis.reason}",
            ]
        )

    return "\n".join(lines)


@dataclass
class PriceActionBuyPointAnalyzer:
    model: str = "qwen-plus"
    enable_thinking: bool = True

    def __post_init__(self):
        self.client = _build_client()

    def analyze(self, data: PriceActionInput) -> PriceActionAnalysisResult:
        chart_description = self._build_chart_description(data)

        current_price = data.bars[-1].close_price
        recent_high = data.recent_high if data.recent_high is not None else self._infer_recent_high(data.bars)
        recent_low = data.recent_low if data.recent_low is not None else self._infer_recent_low(data.bars)

        user_prompt = USER_TEMPLATE.format(
            symbol=data.symbol,
            period=data.period,
            current_price=self._fmt_num(current_price),
            recent_high=self._fmt_num(recent_high),
            recent_low=self._fmt_num(recent_low),
            chart_description=chart_description,
        )

        raw_text = ""
        try:
            request_kwargs = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": SYS},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.1,
            }

            if self.enable_thinking:
                request_kwargs["extra_body"] = {"enable_thinking": True}

            resp = self.client.chat.completions.create(**request_kwargs)
            raw_text = resp.choices[0].message.content or ""
            json_text = _extract_json_text(raw_text)
            payload = _parse_json_payload(json_text)
            analysis = _coerce_payload_shape(payload)
        except Exception as e:
            analysis = _repair_analysis(
                client=self.client,
                model=self.model,
                raw_text=raw_text,
                error_message=str(e),
            )

        try:
            analysis = PriceActionLLMAnalysis.model_validate(analysis)
        except ValidationError as e:
            raise ValueError(f"LLM 返回结果校验失败: {e}") from e

        formatted_markdown = _format_markdown(analysis)

        return PriceActionAnalysisResult(
            input_payload=data,
            chart_description=chart_description,
            llm_analysis=analysis,
            formatted_markdown=formatted_markdown,
        )

    def _infer_recent_high(self, bars: List[KLineBar]) -> float:
        window = bars[-20:] if len(bars) >= 20 else bars
        return max(x.high_price for x in window)

    def _infer_recent_low(self, bars: List[KLineBar]) -> float:
        window = bars[-20:] if len(bars) >= 20 else bars
        return min(x.low_price for x in window)

    def _build_chart_description(self, data: PriceActionInput) -> str:
        bars = data.bars
        n = len(bars)

        last_5 = bars[-5:]
        last_10 = bars[-10:]
        last_20 = bars[-20:]
        last_60 = bars[-60:] if n >= 60 else bars

        closes_10 = [x.close_price for x in last_10]
        highs_20 = [x.high_price for x in last_20]
        lows_20 = [x.low_price for x in last_20]

        swing_high = max(x.high_price for x in last_60)
        swing_low = min(x.low_price for x in last_60)

        recent_close = bars[-1].close_price
        prev_close = bars[-2].close_price if n >= 2 else recent_close
        recent_return_pct = ((recent_close - prev_close) / prev_close * 100) if prev_close else 0.0
        range_20 = (max(highs_20) - min(lows_20)) if highs_20 and lows_20 else 0.0

        lines: List[str] = []
        lines.append("以下为近三个月左右日K价格结构摘要，请只基于价格行为进行判断。")
        lines.append("")
        lines.append("一、近60根K线概览：")
        lines.append(f"- 样本根数：{n}")
        lines.append(f"- 近60根摆动高点：{self._fmt_num(swing_high)}")
        lines.append(f"- 近60根摆动低点：{self._fmt_num(swing_low)}")
        lines.append(f"- 最新收盘价：{self._fmt_num(recent_close)}")
        lines.append(f"- 最近一日相对前一日涨跌幅：{recent_return_pct:.2f}%")
        lines.append("")
        lines.append("二、近20根关键范围：")
        lines.append(f"- 近20日最高点：{self._fmt_num(max(highs_20))}")
        lines.append(f"- 近20日最低点：{self._fmt_num(min(lows_20))}")
        lines.append(f"- 近20日区间跨度：{self._fmt_num(range_20)}")
        lines.append("")
        lines.append("三、最近10日收盘价序列：")
        lines.append("- " + ", ".join(self._fmt_num(x) for x in closes_10))
        lines.append("")
        lines.append("四、最近5根K线明细（按时间升序）：")
        for x in last_5:
            lines.append(
                f"- {x.trade_date}: "
                f"O={self._fmt_num(x.open_price)}, "
                f"H={self._fmt_num(x.high_price)}, "
                f"L={self._fmt_num(x.low_price)}, "
                f"C={self._fmt_num(x.close_price)}"
            )
        lines.append("")
        lines.append("五、最近20根K线明细（按时间升序）：")
        for x in last_20:
            lines.append(
                f"- {x.trade_date}: "
                f"O={self._fmt_num(x.open_price)}, "
                f"H={self._fmt_num(x.high_price)}, "
                f"L={self._fmt_num(x.low_price)}, "
                f"C={self._fmt_num(x.close_price)}"
            )
        lines.append("")
        lines.append("六、请重点识别以下结构性要素：")
        lines.append("- 当前是上行通道、下降通道、震荡区间，还是通道不清晰")
        lines.append("- 最近是否存在有效突破、突破失败、回踩、二次测试、follow-through")
        lines.append("- 最近关键前高、前低、摆动高低点是否清晰")
        lines.append("- 当前形态是否属于：H2 / 牛旗 / 楔形牛旗 / 首次回调 / 有效突破后买点 / 强反转买点")
        lines.append("- 若仍在震荡中部、下降通道压制中、或结构未完成，则必须判定为不买")
        lines.append("")
        lines.append("不要使用指标、成交量故事、消息面、基本面，只依据价格结构回答。")

        return "\n".join(lines)

    @staticmethod
    def _fmt_num(v: float) -> str:
        if float(v).is_integer():
            return str(int(v))
        return f"{v:.3f}".rstrip("0").rstrip(".")


def analyze_buy_point(
    symbol: str,
    bars: List[dict],
    period: str = "日线",
    recent_high: Optional[float] = None,
    recent_low: Optional[float] = None,
    model: str = "qwen-plus",
    enable_thinking: bool = True,
) -> PriceActionAnalysisResult:
    payload = PriceActionInput(
        symbol=symbol,
        period=period,
        bars=[KLineBar(**x) if not isinstance(x, KLineBar) else x for x in bars],
        recent_high=recent_high,
        recent_low=recent_low,
    )

    analyzer = PriceActionBuyPointAnalyzer(
        model=model,
        enable_thinking=enable_thinking,
    )
    return analyzer.analyze(payload)


if __name__ == "__main__":
    sample_bars = [
        {"trade_date": "2026-01-02", "open_price": 10.00, "high_price": 10.30, "low_price": 9.90, "close_price": 10.20},
        {"trade_date": "2026-01-03", "open_price": 10.22, "high_price": 10.50, "low_price": 10.10, "close_price": 10.40},
        {"trade_date": "2026-01-06", "open_price": 10.38, "high_price": 10.55, "low_price": 10.15, "close_price": 10.18},
        {"trade_date": "2026-01-07", "open_price": 10.15, "high_price": 10.25, "low_price": 9.95, "close_price": 10.02},
        {"trade_date": "2026-01-08", "open_price": 10.00, "high_price": 10.12, "low_price": 9.82, "close_price": 9.90},
        {"trade_date": "2026-01-09", "open_price": 9.92, "high_price": 10.08, "low_price": 9.80, "close_price": 10.00},
        {"trade_date": "2026-01-10", "open_price": 10.01, "high_price": 10.25, "low_price": 9.95, "close_price": 10.20},
        {"trade_date": "2026-01-13", "open_price": 10.18, "high_price": 10.42, "low_price": 10.10, "close_price": 10.35},
        {"trade_date": "2026-01-14", "open_price": 10.36, "high_price": 10.60, "low_price": 10.28, "close_price": 10.55},
        {"trade_date": "2026-01-15", "open_price": 10.58, "high_price": 10.75, "low_price": 10.40, "close_price": 10.48},
        {"trade_date": "2026-01-16", "open_price": 10.46, "high_price": 10.52, "low_price": 10.20, "close_price": 10.25},
        {"trade_date": "2026-01-17", "open_price": 10.22, "high_price": 10.30, "low_price": 10.00, "close_price": 10.05},
        {"trade_date": "2026-01-20", "open_price": 10.06, "high_price": 10.18, "low_price": 9.96, "close_price": 10.10},
        {"trade_date": "2026-01-21", "open_price": 10.12, "high_price": 10.26, "low_price": 10.02, "close_price": 10.22},
        {"trade_date": "2026-01-22", "open_price": 10.24, "high_price": 10.48, "low_price": 10.16, "close_price": 10.42},
        {"trade_date": "2026-01-23", "open_price": 10.45, "high_price": 10.70, "low_price": 10.35, "close_price": 10.68},
        {"trade_date": "2026-01-24", "open_price": 10.70, "high_price": 10.92, "low_price": 10.60, "close_price": 10.88},
        {"trade_date": "2026-01-27", "open_price": 10.86, "high_price": 11.05, "low_price": 10.70, "close_price": 10.74},
        {"trade_date": "2026-01-28", "open_price": 10.72, "high_price": 10.82, "low_price": 10.48, "close_price": 10.55},
        {"trade_date": "2026-02-03", "open_price": 10.54, "high_price": 10.68, "low_price": 10.30, "close_price": 10.36},
        {"trade_date": "2026-02-04", "open_price": 10.35, "high_price": 10.52, "low_price": 10.22, "close_price": 10.48},
        {"trade_date": "2026-02-05", "open_price": 10.50, "high_price": 10.76, "low_price": 10.42, "close_price": 10.72},
        {"trade_date": "2026-02-06", "open_price": 10.74, "high_price": 10.96, "low_price": 10.65, "close_price": 10.90},
        {"trade_date": "2026-02-07", "open_price": 10.92, "high_price": 11.12, "low_price": 10.80, "close_price": 11.08},
        {"trade_date": "2026-02-10", "open_price": 11.06, "high_price": 11.18, "low_price": 10.88, "close_price": 10.95},
        {"trade_date": "2026-02-11", "open_price": 10.94, "high_price": 11.02, "low_price": 10.72, "close_price": 10.78},
        {"trade_date": "2026-02-12", "open_price": 10.76, "high_price": 10.85, "low_price": 10.55, "close_price": 10.60},
        {"trade_date": "2026-02-13", "open_price": 10.62, "high_price": 10.75, "low_price": 10.48, "close_price": 10.70},
        {"trade_date": "2026-02-14", "open_price": 10.72, "high_price": 10.98, "low_price": 10.66, "close_price": 10.92},
        {"trade_date": "2026-02-17", "open_price": 10.94, "high_price": 11.20, "low_price": 10.88, "close_price": 11.15},
    ]

    result = analyze_buy_point(
        symbol="TEST.SH",
        bars=sample_bars,
        model="qwen-plus",
        enable_thinking=True,
    )

    print("===== 结构化结果 =====")
    print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2))

    print("\n===== 固定格式文本 =====")
    print(result.formatted_markdown)