
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, List, Optional, Literal

from openai import OpenAI
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator

from app.config import settings


SYS = """
你是一个只依据 Price Action 规则工作的 A 股交易分析器。

你的唯一任务是：
判断“当前是否是买点”。

必须严格遵守 https://priceactions.forecho.com/ 的 Price Action 规则，尤其是：
1. 背景永远大于单根K线
2. 市场只有趋势或震荡区间两种状态
3. 趋势会演变为通道，通道最终常演变为震荡区间
4. EMA20 是结构分析的一部分，不是额外指标故事
5. 回调持续过久（通常超过20根K线）应按震荡区间处理
6. H1/H2、首次回调、牛旗、楔形牛旗、有效突破、强反转都必须放在背景中判断
7. 强突破可以同K入场；弱突破或区间突破必须看 follow-through
8. 顺势交易的初始止损应放在主要拐点之外；利润目标必须基于前高、区间边缘、测量移动或实际风险逻辑
9. 如果结构模糊、位于震荡区间中部、或买点不清晰，必须输出“不买”

你必须只输出一个 JSON 对象，不要输出任何额外解释。
"""

USER_TEMPLATE = """
请严格按照既定 Price Action 买点规则，判断下面这张 A 股图表现在是否是买点。

分析对象：
- 标的：{symbol}
- 周期：{period}
- 当前价格：{current_price}
- 最近关键高点：{recent_high}
- 最近关键低点：{recent_low}
- 当前图表描述：
{chart_description}

输出必须严格是 JSON，字段必须为：
conclusion, current_channel, channel_support_buy, current_pattern,
pattern_allowed_type, key_candle, has_follow_through, can_trigger_buy,
expected_entry, trigger_condition, buy_price, stop_loss, take_profit, reason
"""

# ---------- internal constants ----------
ALWAYS_IN_LOOKBACK = 10
EMA_PERIOD = 20
RANGE_MIDDLE_LOW = 0.33
RANGE_MIDDLE_HIGH = 0.67

TREND_BAR_BODY_RATIO = 0.50
TREND_BAR_MAX_TAIL_RATIO = 0.25
STRONG_BREAKOUT_BODY_RATIO = 0.55
STRONG_CLOSE_NEAR_EXTREME = 0.25
MIN_SWING_BARS_FOR_MTR = 20
TBTL_MIN_BARS = 10
TBTL_MIN_LEGS = 2
MIN_BARS_FOR_ANALYSIS = 30


class KLineBar(BaseModel):
    model_config = ConfigDict(extra="ignore")

    trade_date: str = Field(..., description="交易日期，YYYY-MM-DD")
    open_price: float = Field(..., description="开盘价")
    high_price: float = Field(..., description="最高价")
    low_price: float = Field(..., description="最低价")
    close_price: float = Field(..., description="收盘价")

    @model_validator(mode="after")
    def validate_prices(self):
        if self.high_price < max(self.open_price, self.close_price, self.low_price):
            raise ValueError("high_price 必须不小于 open/close/low")
        if self.low_price > min(self.open_price, self.close_price, self.high_price):
            raise ValueError("low_price 必须不大于 open/close/high")
        return self


class PriceActionInput(BaseModel):
    symbol: str = Field(..., description="股票代码或标的名称")
    period: str = Field(default="日线", description="周期，默认日线")
    bars: List[KLineBar] = Field(..., description="按时间升序排列的K线数据，建议约三个月")
    recent_high: Optional[float] = Field(default=None, description="可选，外部显式传入最近关键高点")
    recent_low: Optional[float] = Field(default=None, description="可选，外部显式传入最近关键低点")

    @field_validator("bars")
    @classmethod
    def validate_bars(cls, v: List[KLineBar]):
        if len(v) < MIN_BARS_FOR_ANALYSIS:
            raise ValueError("bars 至少需要 30 根，建议 90 根")
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


@dataclass
class PivotPoint:
    index: int
    price: float
    kind: Literal["high", "low"]
    strength: Literal["major", "minor"]


@dataclass
class PriceActionDecision:
    conclusion: Literal["买", "不买"]
    current_channel: str
    channel_support_buy: str
    current_pattern: str
    pattern_allowed_type: str
    key_candle: str
    has_follow_through: str
    can_trigger_buy: str
    expected_entry: Optional[str]
    trigger_condition: Optional[str]
    buy_price: Optional[str]
    stop_loss: Optional[str]
    take_profit: Optional[str]
    reason: str


def _build_client() -> Optional[OpenAI]:
    api_key = (getattr(settings, "api_key", "") or "").strip()
    if not api_key:
        return None

    return OpenAI(
        api_key=api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        timeout=120.0,
    )


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
        decision = self._rule_based_analysis(data)
        analysis = PriceActionLLMAnalysis.model_validate(decision.__dict__)
        formatted_markdown = _format_markdown(analysis)
        return PriceActionAnalysisResult(
            input_payload=data,
            chart_description=chart_description,
            llm_analysis=analysis,
            formatted_markdown=formatted_markdown,
        )

    # ---------- main decision engine ----------
    def _rule_based_analysis(self, data: PriceActionInput) -> PriceActionDecision:
        bars = data.bars
        closes = [x.close_price for x in bars]
        highs = [x.high_price for x in bars]
        lows = [x.low_price for x in bars]

        ema20 = self._ema(closes, EMA_PERIOD)
        pivots = self._extract_pivots(bars)

        recent_high = data.recent_high if data.recent_high is not None else self._infer_recent_high(bars)
        recent_low = data.recent_low if data.recent_low is not None else self._infer_recent_low(bars)

        ctx = self._assess_market_context(bars, ema20, pivots)
        last_bar = bars[-1]
        key_candle = self._describe_signal_bar(last_bar, bars[-2] if len(bars) >= 2 else None, self._avg_range(bars[-10:]))

        current_pattern = "未形成允许的买点结构"
        pattern_allowed_type = "否"
        has_follow_through = "否"
        can_trigger_buy = "否"
        expected_entry = "等待更清晰的趋势背景、边缘位置或确认后的突破单机会"
        trigger_condition = "必须先满足正期望值、明确方向门和有效入场信号"
        buy_price = None
        stop_loss = None
        take_profit = None
        reasons: list[str] = []

        if ctx["state"] == "trading_range":
            channel_name = "震荡区间 / 双向交易环境"
            channel_support_buy = "否，除非在下沿附近出现高质量反转"
        elif ctx["state"] == "bull_trend":
            channel_name = "多头趋势 / 偏单边上涨"
            channel_support_buy = "是，优先顺势做多"
        elif ctx["state"] == "bear_trend":
            channel_name = "空头趋势 / 偏单边下跌"
            channel_support_buy = "否，除非形成大反转"
        else:
            channel_name = "方向不清 / 默认按震荡区间处理"
            channel_support_buy = "否"
            ctx["state"] = "trading_range"

        # hard filters from site logic
        if ctx["state"] == "trading_range" and ctx["in_middle"]:
            reasons.append("当前处于震荡区间中部。站点逻辑要求区间中部避免追单，优先等待边缘位置。")
            return self._build_not_buy(
                channel_name, channel_support_buy, "震荡区间中部", "否", key_candle, "否", "否",
                expected_entry="等待接近区间下沿的反转做多，或等待区间真正向上突破并出现跟随。",
                trigger_condition="边缘反转或明确突破+跟随确认后再考虑突破单。",
                reason=" ".join(reasons),
            )

        if ctx["always_in"] == "short" and ctx["state"] != "trading_range":
            reasons.append("当前处于单边下跌 / 空头优势背景。按 Always In 逻辑，不应主动寻找普通做多。")

        trend_setup = self._detect_trend_pullback_buy(bars, ema20, pivots, ctx)
        breakout_setup = self._detect_breakout_buy(bars, ema20, pivots, ctx, recent_high)
        mtr_setup = self._detect_major_reversal_buy(bars, ema20, pivots, ctx, recent_high)

        chosen = None
        if trend_setup["qualified"]:
            chosen = trend_setup
        elif breakout_setup["qualified"]:
            chosen = breakout_setup
        elif mtr_setup["qualified"]:
            chosen = mtr_setup

        if chosen is None:
            reasons.extend([
                ctx["summary"],
                trend_setup.get("why_not", ""),
                breakout_setup.get("why_not", ""),
                mtr_setup.get("why_not", ""),
            ])
            reason = " ".join(x for x in reasons if x).strip()
            if not reason:
                reason = "当前图表未形成符合 Price Action 规则的可执行买点。"
            return self._build_not_buy(
                channel_name,
                channel_support_buy,
                current_pattern,
                pattern_allowed_type,
                key_candle,
                has_follow_through,
                can_trigger_buy,
                expected_entry=expected_entry,
                trigger_condition=trigger_condition,
                reason=reason,
            )

        current_pattern = chosen["pattern_name"]
        pattern_allowed_type = chosen["pattern_type"]
        key_candle = chosen["signal_text"]
        has_follow_through = "是" if chosen["has_follow_through"] else "否"
        can_trigger_buy = "是" if chosen["signal_ready"] else "否"

        entry = chosen["entry"]
        stop = chosen["stop"]
        target = chosen["target"]

        if not self._passes_traders_equation(entry, stop, target, chosen["success_probability"]):
            reasons.extend([ctx["summary"], chosen["why_not"], "该交易未通过交易者方程：盈亏空间不足以覆盖结构概率。"])
            return self._build_not_buy(
                channel_name,
                channel_support_buy,
                current_pattern,
                pattern_allowed_type,
                key_candle,
                has_follow_through,
                "否",
                expected_entry=chosen["expected_entry"],
                trigger_condition=chosen["trigger_condition"],
                reason=" ".join(x for x in reasons if x).strip(),
            )

        buy_price = f"突破 {self._fmt_num(entry)} 上方的突破单入场"
        stop_loss = f"{self._fmt_num(stop)} 下方（保护性止损 / 结构失效位）"
        take_profit = f"先看 {self._fmt_num(target)}；若继续单边，可移动保护止损管理盈利"

        reasons.extend([
            ctx["summary"],
            chosen["why_yes"],
            f"按交易者方程估算，该交易的潜在利润相对风险具备正期望值。",
        ])
        return PriceActionDecision(
            conclusion="买",
            current_channel=channel_name,
            channel_support_buy=channel_support_buy,
            current_pattern=current_pattern,
            pattern_allowed_type=pattern_allowed_type,
            key_candle=key_candle,
            has_follow_through=has_follow_through,
            can_trigger_buy=can_trigger_buy,
            expected_entry=None,
            trigger_condition=None,
            buy_price=buy_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            reason=" ".join(x for x in reasons if x).strip(),
        )

    # ---------- decision helpers ----------
    def _build_not_buy(
        self,
        channel_name: str,
        channel_support_buy: str,
        current_pattern: str,
        pattern_allowed_type: str,
        key_candle: str,
        has_follow_through: str,
        can_trigger_buy: str,
        expected_entry: str,
        trigger_condition: str,
        reason: str,
    ) -> PriceActionDecision:
        return PriceActionDecision(
            conclusion="不买",
            current_channel=channel_name,
            channel_support_buy=channel_support_buy,
            current_pattern=current_pattern,
            pattern_allowed_type=pattern_allowed_type,
            key_candle=key_candle,
            has_follow_through=has_follow_through,
            can_trigger_buy=can_trigger_buy,
            expected_entry=expected_entry,
            trigger_condition=trigger_condition,
            buy_price=None,
            stop_loss=None,
            take_profit=None,
            reason=reason or "当前图表未形成符合 Price Action 规则的可执行买点。",
        )

    def _assess_market_context(self, bars: List[KLineBar], ema20: List[float], pivots: List[PivotPoint]) -> dict[str, Any]:
        last20 = bars[-20:]
        avg_range_20 = self._avg_range(last20)
        bull_trend = sum(1 for b in last20 if self._bar_kind(b) == "bull_trend")
        bear_trend = sum(1 for b in last20 if self._bar_kind(b) == "bear_trend")
        tr_bars = sum(1 for b in last20 if self._bar_kind(b) == "tr_bar")
        overlap_count = sum(1 for i in range(1, len(last20)) if self._is_overlap(last20[i - 1], last20[i]))
        inside_count = sum(1 for i in range(1, len(last20)) if self._classify_bar_shape(last20[i - 1], last20[i])["inside"])
        outside_count = sum(1 for i in range(1, len(last20)) if self._classify_bar_shape(last20[i - 1], last20[i])["outside"])
        tails_heavy = sum(1 for b in last20 if self._tail_heavy(b))
        bull_micro = self._bull_micro_channel_len(bars)
        bear_micro = self._bear_micro_channel_len(bars)
        range_high = max(b.high_price for b in last20)
        range_low = min(b.low_price for b in last20)
        current_close = bars[-1].close_price
        range_pos = (current_close - range_low) / max(range_high - range_low, 1e-9)
        in_middle = RANGE_MIDDLE_LOW <= range_pos <= RANGE_MIDDLE_HIGH

        tbtl = self._detect_tbtl(bars, pivots)
        always_in = self._detect_always_in_state(bars, ema20)

        confusion = (
            tr_bars >= 9
            or overlap_count >= 10
            or inside_count >= 4
            or tails_heavy >= 9
            or abs(bull_trend - bear_trend) <= 2
        )
        disappointment = self._detect_disappointment(bars)
        strong_bull = (
            current_close > ema20[-1]
            and ema20[-1] >= ema20[-6] if len(ema20) >= 6 else current_close > ema20[-1]
        )
        strong_bull = bool(strong_bull) and bull_trend >= bear_trend + 3 and bull_micro >= 3 and overlap_count <= 8
        strong_bear = (
            current_close < ema20[-1]
            and (ema20[-1] <= ema20[-6] if len(ema20) >= 6 else current_close < ema20[-1])
            and bear_trend >= bull_trend + 3
            and bear_micro >= 3
            and overlap_count <= 8
        )

        state: Literal["bull_trend", "bear_trend", "trading_range"]
        if confusion or disappointment or tbtl["qualified"] or in_middle:
            if strong_bull and not disappointment and not tbtl["qualified"] and not in_middle:
                state = "bull_trend"
            elif strong_bear and not disappointment and not tbtl["qualified"] and not in_middle:
                state = "bear_trend"
            else:
                state = "trading_range"
        elif strong_bull:
            state = "bull_trend"
        elif strong_bear:
            state = "bear_trend"
        else:
            state = "trading_range"

        summary = (
            f"背景判断：当前更接近{'多头趋势' if state == 'bull_trend' else '空头趋势' if state == 'bear_trend' else '震荡区间'}；"
            f"Always In 状态为 {always_in}；近20根 bull/bear/tr={bull_trend}/{bear_trend}/{tr_bars}，"
            f"重叠数={overlap_count}，TBTL={'是' if tbtl['qualified'] else '否'}。"
        )

        return {
            "state": state,
            "always_in": always_in,
            "avg_range_20": avg_range_20,
            "range_high": range_high,
            "range_low": range_low,
            "range_position": range_pos,
            "in_middle": in_middle,
            "bull_trend_bars": bull_trend,
            "bear_trend_bars": bear_trend,
            "tr_bars": tr_bars,
            "overlap_count": overlap_count,
            "inside_count": inside_count,
            "outside_count": outside_count,
            "confusion": confusion,
            "disappointment": disappointment,
            "tbtl": tbtl,
            "summary": summary,
        }

    def _detect_trend_pullback_buy(self, bars: List[KLineBar], ema20: List[float], pivots: List[PivotPoint], ctx: dict[str, Any]) -> dict[str, Any]:
        if ctx["state"] != "bull_trend" or ctx["always_in"] == "short":
            return {"qualified": False, "why_not": "不满足顺势做多背景。"}

        pullback = self._detect_pullback_structure(bars, ema20, pivots)
        if pullback["degraded_to_range"]:
            return {"qualified": False, "why_not": "当前回调已演变为震荡区间/TBTL，不按简单顺势回调处理。"}
        if not pullback["signal_ready"]:
            return {
                "qualified": False,
                "why_not": "顺势回调背景存在，但最后一根尚未形成合格的做多信号K。",
                "expected_entry": f"等待突破 {self._fmt_num(pullback['entry'])} 上方的突破单。",
                "trigger_condition": "出现合格信号K并触发突破单后再考虑买入。",
            }

        pattern_name = pullback["pattern_name"]
        pattern_type = "是，属于趋势中的回调买点"
        signal_text = pullback["signal_text"]
        has_follow = pullback["has_follow_through"]
        entry = pullback["entry"]
        stop = pullback["stop"]
        target = max(pullback["prior_high"], entry + 2.0 * max(entry - stop, 1e-9))
        success_probability = 0.58 if "首次回调" in pattern_name else 0.55 if "H2" in pattern_name else 0.52

        return {
            "qualified": True,
            "pattern_name": pattern_name,
            "pattern_type": pattern_type,
            "signal_text": signal_text,
            "signal_ready": True,
            "has_follow_through": has_follow,
            "entry": entry,
            "stop": stop,
            "target": target,
            "success_probability": success_probability,
            "expected_entry": None,
            "trigger_condition": None,
            "why_yes": "当前处于趋势背景，且信号来自顺势回调后的突破单入场，符合站点对 H1/H2/牛旗/楔形牛旗的处理方式。",
            "why_not": "",
        }

    def _detect_breakout_buy(self, bars: List[KLineBar], ema20: List[float], pivots: List[PivotPoint], ctx: dict[str, Any], recent_high: float) -> dict[str, Any]:
        last_bar = bars[-1]
        prev_bar = bars[-2] if len(bars) >= 2 else bars[-1]
        breakout = self._detect_breakout_structure(bars, ema20, pivots)

        if not breakout["is_breakout"]:
            return {"qualified": False, "why_not": "当前未形成强势突破结构。"}
        if ctx["state"] == "trading_range" and ctx["in_middle"]:
            return {"qualified": False, "why_not": "区间中部的突破信号不交易，优先等待边缘突破+跟随。"}
        if breakout["needs_follow_through"] and not breakout["has_follow_through"]:
            return {
                "qualified": False,
                "why_not": "当前突破尚未获得足够跟随确认。",
                "expected_entry": f"等待突破后出现跟随K，再以突破单跟进。",
                "trigger_condition": "至少一根同向跟随K确认突破成功。",
            }

        entry = breakout["entry"]
        stop = breakout["stop"]
        target = max(recent_high, breakout["measured_move_target"], entry + 1.8 * max(entry - stop, 1e-9))
        success_probability = 0.56 if ctx["state"] == "bull_trend" else 0.50

        return {
            "qualified": True,
            "pattern_name": "有效向上突破",
            "pattern_type": "是，属于有效突破后的买点",
            "signal_text": breakout["signal_text"],
            "signal_ready": True,
            "has_follow_through": breakout["has_follow_through"],
            "entry": entry,
            "stop": stop,
            "target": target,
            "success_probability": success_probability,
            "expected_entry": None,
            "trigger_condition": None,
            "why_yes": "当前价格以趋势K线突破关键阻力，并具备跟随确认或强势单边背景，符合站点对突破的处理逻辑。",
            "why_not": "",
        }

    def _detect_major_reversal_buy(self, bars: List[KLineBar], ema20: List[float], pivots: List[PivotPoint], ctx: dict[str, Any], recent_high: float) -> dict[str, Any]:
        mtr = self._detect_major_reversal_structure(bars, ema20, pivots)
        if not mtr["candidate"]:
            return {"qualified": False, "why_not": "当前未形成大反转候选。"}
        if not mtr["signal_ready"]:
            return {
                "qualified": False,
                "why_not": "大反转候选存在，但信号K或触发条件尚未完成。",
                "expected_entry": f"等待突破 {self._fmt_num(mtr['entry'])} 上方的突破单。",
                "trigger_condition": "大反转信号K触发并尽量伴随跟随K确认后再进场。",
            }

        entry = mtr["entry"]
        stop = mtr["stop"]
        target = max(recent_high, mtr["first_target"], entry + 2.0 * max(entry - stop, 1e-9))
        success_probability = 0.40

        return {
            "qualified": True,
            "pattern_name": mtr["pattern_name"],
            "pattern_type": "是，属于强反转买点",
            "signal_text": mtr["signal_text"],
            "signal_ready": True,
            "has_follow_through": mtr["has_follow_through"],
            "entry": entry,
            "stop": stop,
            "target": target,
            "success_probability": success_probability,
            "expected_entry": None,
            "trigger_condition": None,
            "why_yes": "当前满足大反转的关键条件：先有趋势线/均线破坏，再有原趋势恢复失败，并出现高盈亏比的突破单信号。",
            "why_not": "",
        }

    def _passes_traders_equation(self, entry: float, stop: float, target: float, success_probability: float) -> bool:
        risk = max(entry - stop, 1e-9)
        reward = max(target - entry, 0.0)
        fail_probability = 1.0 - success_probability
        return reward > 0 and (success_probability * reward) > (fail_probability * risk)

    # ---------- structure detectors ----------
    def _detect_pullback_structure(self, bars: List[KLineBar], ema20: List[float], pivots: List[PivotPoint]) -> dict[str, Any]:
        n = len(bars)
        avg_range = self._avg_range(bars[-20:])
        highs = [b.high_price for b in bars]
        lows = [b.low_price for b in bars]

        # locate latest swing high that started the pullback
        pullback_start = n - 1
        highest_seen = bars[-1].high_price
        for i in range(n - 2, max(-1, n - 15), -1):
            if bars[i].high_price >= highest_seen:
                highest_seen = bars[i].high_price
                pullback_start = i
            else:
                break

        duration = n - 1 - pullback_start
        swing_high = max(x.high_price for x in bars[max(0, pullback_start - 2):pullback_start + 1])
        swing_low = min(x.low_price for x in bars[pullback_start:])
        prior_high = max(highs[-20:])

        attempts = 0
        low_pivots = [p for p in pivots if p.kind == "low" and p.index >= pullback_start]
        legs = len(low_pivots)
        for i in range(max(1, pullback_start + 1), n):
            prev_bar, bar = bars[i - 1], bars[i]
            shape = self._classify_bar_shape(prev_bar, bar)
            bull_signal_bar = (
                bar.close_price > bar.open_price
                and bar.close_price >= bar.high_price - 0.25 * max(bar.high_price - bar.low_price, 1e-9)
                and bar.high_price >= prev_bar.high_price
                and not shape["outside"]
            )
            if bull_signal_bar:
                attempts += 1

        bull_micro_before = self._bull_micro_channel_len(bars[:pullback_start + 1]) if pullback_start >= 2 else 1
        first_pullback = bull_micro_before >= 3 and duration <= 10 and attempts <= 1
        h2 = attempts >= 2
        wedge = self._detect_wedge_bull_flag(bars, pivots)

        last_bar = bars[-1]
        prev_bar = bars[-2] if len(bars) >= 2 else bars[-1]
        signal_ready = (
            last_bar.close_price > last_bar.open_price
            and last_bar.close_price >= last_bar.high_price - 0.25 * max(last_bar.high_price - last_bar.low_price, 1e-9)
            and last_bar.high_price >= prev_bar.high_price
        )
        has_follow_through = (
            len(bars) >= 2
            and bars[-1].close_price > bars[-1].open_price
            and bars[-2].close_price > bars[-2].open_price
            and bars[-1].close_price >= bars[-2].close_price
        )

        major_low = self._infer_recent_low(bars[:-1] if len(bars) > 1 else bars)
        held_above_major_low = swing_low >= major_low - 0.3 * avg_range
        degraded_to_range = duration >= 20 or self._detect_tbtl(bars, pivots)["qualified"]

        if wedge["qualified"]:
            pattern_name = "楔形牛旗 / 三推回调"
        elif h2:
            pattern_name = "H2 / 二次顺势恢复"
        elif first_pullback:
            pattern_name = "首次回调 / H1 候选"
        else:
            pattern_name = "普通回调"

        return {
            "duration": duration,
            "legs": legs,
            "attempts": attempts,
            "pattern_name": pattern_name,
            "signal_ready": signal_ready and held_above_major_low,
            "signal_text": self._describe_signal_bar(last_bar, prev_bar, avg_range),
            "has_follow_through": has_follow_through,
            "entry": max(last_bar.high_price, prev_bar.high_price),
            "stop": min(swing_low, major_low),
            "prior_high": prior_high,
            "degraded_to_range": degraded_to_range,
            "held_above_major_low": held_above_major_low,
            "wedge": wedge["qualified"],
        }

    def _detect_breakout_structure(self, bars: List[KLineBar], ema20: List[float], pivots: List[PivotPoint]) -> dict[str, Any]:
        last_bar = bars[-1]
        prev_bar = bars[-2] if len(bars) >= 2 else bars[-1]
        prev_high_20 = max(x.high_price for x in bars[-21:-1]) if len(bars) >= 21 else max(x.high_price for x in bars[:-1])
        range20_high = max(x.high_price for x in bars[-20:])
        range20_low = min(x.low_price for x in bars[-20:])
        avg_body = self._avg_body(bars[-20:])
        bar_range = max(last_bar.high_price - last_bar.low_price, 1e-9)
        body = abs(last_bar.close_price - last_bar.open_price)

        strong_bar = (
            last_bar.close_price > last_bar.open_price
            and body >= max(avg_body * 1.2, bar_range * STRONG_BREAKOUT_BODY_RATIO)
            and last_bar.close_price >= last_bar.high_price - STRONG_CLOSE_NEAR_EXTREME * bar_range
            and last_bar.close_price > ema20[-1]
        )
        broke_level = last_bar.high_price > prev_high_20 or last_bar.close_price > prev_high_20
        has_follow_through = (
            len(bars) >= 2
            and prev_bar.close_price > prev_bar.open_price
            and last_bar.close_price > last_bar.open_price
            and last_bar.close_price >= prev_bar.close_price
        )
        needs_follow_through = not strong_bar
        measured_move_target = prev_high_20 + (range20_high - range20_low)

        return {
            "is_breakout": broke_level and strong_bar,
            "has_follow_through": has_follow_through,
            "needs_follow_through": needs_follow_through,
            "entry": max(last_bar.high_price, prev_high_20),
            "stop": min(last_bar.low_price, prev_bar.low_price, prev_high_20),
            "measured_move_target": measured_move_target,
            "signal_text": self._describe_signal_bar(last_bar, prev_bar, self._avg_range(bars[-10:])) + f"，并突破 {self._fmt_num(prev_high_20)}",
        }

    def _detect_major_reversal_structure(self, bars: List[KLineBar], ema20: List[float], pivots: List[PivotPoint]) -> dict[str, Any]:
        n = len(bars)
        if n < MIN_SWING_BARS_FOR_MTR:
            return {
                "candidate": False,
                "signal_ready": False,
                "entry": bars[-1].high_price,
                "stop": bars[-1].low_price,
                "first_target": bars[-1].high_price,
                "pattern_name": "未形成大反转",
                "signal_text": self._describe_signal_bar(bars[-1], bars[-2] if len(bars) >= 2 else None, self._avg_range(bars[-10:])),
                "has_follow_through": False,
            }

        last20 = bars[-20:]
        bear_pressure = sum(1 for x in last20 if self._bar_kind(x) == "bear_trend")
        bull_pressure = sum(1 for x in last20 if self._bar_kind(x) == "bull_trend")
        prior_bearish = bear_pressure >= bull_pressure and bars[-6].close_price < ema20[-6]

        low_pivots = [p for p in pivots if p.kind == "low"]
        double_bottom = False
        bottom_low = min(x.low_price for x in bars[-20:])
        if len(low_pivots) >= 2:
            a, b = low_pivots[-2], low_pivots[-1]
            double_bottom = abs(a.price - b.price) <= self._avg_range(bars[-20:]) * 0.8
            bottom_low = min(a.price, b.price)

        wedge = self._detect_wedge_bottom(bars, pivots)["qualified"]
        trendline_break = bars[-1].close_price > ema20[-1] and max(x.high_price for x in bars[-3:]) > max(x.high_price for x in bars[-8:-3])

        last_bar = bars[-1]
        prev_bar = bars[-2] if len(bars) >= 2 else bars[-1]
        strong_signal = (
            last_bar.close_price > last_bar.open_price
            and (last_bar.close_price - last_bar.open_price) >= 0.5 * max(last_bar.high_price - last_bar.low_price, 1e-9)
            and last_bar.close_price >= last_bar.high_price - 0.25 * max(last_bar.high_price - last_bar.low_price, 1e-9)
        )
        has_follow_through = (
            len(bars) >= 2
            and (
                (bars[-1].close_price > bars[-1].open_price and bars[-2].close_price > bars[-2].open_price)
                or (bars[-1].close_price > bars[-2].high_price)
            )
        )
        candidate = prior_bearish and trendline_break and (double_bottom or wedge)
        first_target = max(x.high_price for x in bars[-20:-5]) if n >= 25 else max(x.high_price for x in bars[-10:])
        pattern_name = "双底 / 大反转买点" if double_bottom else "楔形底 / 大反转买点"

        return {
            "candidate": candidate,
            "signal_ready": candidate and strong_signal and has_follow_through,
            "entry": max(last_bar.high_price, prev_bar.high_price),
            "stop": bottom_low,
            "first_target": first_target,
            "pattern_name": pattern_name,
            "signal_text": self._describe_signal_bar(last_bar, prev_bar, self._avg_range(bars[-10:])),
            "has_follow_through": has_follow_through,
        }

    def _detect_wedge_bull_flag(self, bars: List[KLineBar], pivots: List[PivotPoint]) -> dict[str, Any]:
        low_pivots = [p for p in pivots if p.kind == "low"]
        if len(low_pivots) < 3:
            return {"qualified": False}
        last3 = low_pivots[-3:]
        spacing_ok = (last3[1].index - last3[0].index >= 2) and (last3[2].index - last3[1].index >= 2)
        descending = last3[0].price >= last3[1].price >= last3[2].price
        compressing = (max(p.price for p in last3) - min(p.price for p in last3)) <= self._avg_range(bars[-20:]) * 3.0
        return {"qualified": spacing_ok and (descending or compressing)}

    def _detect_wedge_bottom(self, bars: List[KLineBar], pivots: List[PivotPoint]) -> dict[str, Any]:
        low_pivots = [p for p in pivots if p.kind == "low"]
        if len(low_pivots) < 3:
            return {"qualified": False}
        last3 = low_pivots[-3:]
        spacing_ok = (last3[1].index - last3[0].index >= 2) and (last3[2].index - last3[1].index >= 2)
        flattening = (max(p.price for p in last3) - min(p.price for p in last3)) <= self._avg_range(bars[-20:]) * 3.0
        return {"qualified": spacing_ok and flattening}

    # ---------- lower-level helpers ----------
    def _classify_bar_shape(self, prev_bar: KLineBar, bar: KLineBar) -> dict[str, bool]:
        inside = bar.high_price <= prev_bar.high_price and bar.low_price >= prev_bar.low_price
        outside = bar.high_price >= prev_bar.high_price and bar.low_price <= prev_bar.low_price
        bull_close_near_high = (
            bar.close_price > bar.open_price
            and bar.close_price >= bar.high_price - 0.25 * max(bar.high_price - bar.low_price, 1e-9)
        )
        bear_close_near_low = (
            bar.close_price < bar.open_price
            and bar.close_price <= bar.low_price + 0.25 * max(bar.high_price - bar.low_price, 1e-9)
        )
        return {
            "inside": inside,
            "outside": outside,
            "bull_close_near_high": bull_close_near_high,
            "bear_close_near_low": bear_close_near_low,
        }

    def _detect_always_in_state(self, bars: List[KLineBar], ema20: List[float]) -> Literal["long", "short", "neutral"]:
        if len(bars) < 6:
            return "neutral"

        last_n = min(ALWAYS_IN_LOOKBACK, len(bars))
        sample = bars[-last_n:]
        bull_bars = 0
        bear_bars = 0
        closes_above_ema = 0
        closes_below_ema = 0
        higher_lows = 0
        lower_highs = 0

        for i, bar in enumerate(sample):
            kind = self._bar_kind(bar)
            if kind == "bull_trend":
                bull_bars += 1
            elif kind == "bear_trend":
                bear_bars += 1

            ema_idx = len(ema20) - last_n + i
            if bar.close_price >= ema20[ema_idx]:
                closes_above_ema += 1
            else:
                closes_below_ema += 1

            if i >= 1:
                if sample[i].low_price >= sample[i - 1].low_price:
                    higher_lows += 1
                if sample[i].high_price <= sample[i - 1].high_price:
                    lower_highs += 1

        if bull_bars >= bear_bars + 2 and closes_above_ema >= last_n - 2 and higher_lows >= max(2, last_n // 2):
            return "long"
        if bear_bars >= bull_bars + 2 and closes_below_ema >= last_n - 2 and lower_highs >= max(2, last_n // 2):
            return "short"
        return "neutral"

    def _detect_tbtl(self, bars: List[KLineBar], pivots: List[PivotPoint]) -> dict[str, Any]:
        if len(bars) < TBTL_MIN_BARS:
            return {"qualified": False, "bars": len(bars), "legs": 0}

        lookback = bars[-20:]
        start_idx = len(bars) - len(lookback)
        local_pivots = [p for p in pivots if p.index >= start_idx]
        if len(local_pivots) < 3:
            return {"qualified": False, "bars": len(lookback), "legs": 0}

        legs = 0
        prev_kind = None
        for p in local_pivots:
            if prev_kind is None:
                prev_kind = p.kind
                continue
            if p.kind != prev_kind:
                legs += 1
                prev_kind = p.kind

        qualified = len(lookback) >= TBTL_MIN_BARS and legs >= TBTL_MIN_LEGS
        return {"qualified": qualified, "bars": len(lookback), "legs": legs}

    def _detect_disappointment(self, bars: List[KLineBar]) -> bool:
        if len(bars) < 4:
            return False
        recent = bars[-4:]
        failed_breakouts = 0
        for i in range(1, len(recent)):
            prev_bar, bar = recent[i - 1], recent[i]
            strong_prev = self._bar_kind(prev_bar) in {"bull_trend", "bear_trend"}
            immediate_failure = (
                (prev_bar.close_price > prev_bar.open_price and bar.close_price < bar.open_price and bar.close_price <= prev_bar.open_price)
                or (prev_bar.close_price < prev_bar.open_price and bar.close_price > bar.open_price and bar.close_price >= prev_bar.open_price)
            )
            if strong_prev and immediate_failure:
                failed_breakouts += 1
        return failed_breakouts >= 2

    def _extract_pivots(self, bars: List[KLineBar]) -> List[PivotPoint]:
        n = len(bars)
        avg_range = self._avg_range(bars[-20:])
        pivots: List[PivotPoint] = []
        for i in range(2, n - 2):
            is_high = (
                bars[i].high_price >= bars[i - 1].high_price
                and bars[i].high_price >= bars[i - 2].high_price
                and bars[i].high_price >= bars[i + 1].high_price
                and bars[i].high_price >= bars[i + 2].high_price
            )
            is_low = (
                bars[i].low_price <= bars[i - 1].low_price
                and bars[i].low_price <= bars[i - 2].low_price
                and bars[i].low_price <= bars[i + 1].low_price
                and bars[i].low_price <= bars[i + 2].low_price
            )
            if is_high:
                future_low = min(x.low_price for x in bars[i + 1:min(n, i + 9)])
                strength = "major" if bars[i].high_price - future_low >= avg_range * 2 else "minor"
                pivots.append(PivotPoint(index=i, price=bars[i].high_price, kind="high", strength=strength))
            if is_low:
                future_high = max(x.high_price for x in bars[i + 1:min(n, i + 9)])
                strength = "major" if future_high - bars[i].low_price >= avg_range * 2 else "minor"
                pivots.append(PivotPoint(index=i, price=bars[i].low_price, kind="low", strength=strength))
        return pivots

    def _latest_major_pivot(self, pivots: List[PivotPoint], kind: str, default_price: float) -> float:
        for pivot in reversed(pivots):
            if pivot.kind == kind and pivot.strength == "major":
                return pivot.price
        for pivot in reversed(pivots):
            if pivot.kind == kind:
                return pivot.price
        return default_price

    def _build_chart_description(self, data: PriceActionInput) -> str:
        bars = data.bars
        closes = [x.close_price for x in bars]
        ema20 = self._ema(closes, EMA_PERIOD)
        pivots = self._extract_pivots(bars)
        ctx = self._assess_market_context(bars, ema20, pivots)
        pullback = self._detect_pullback_structure(bars, ema20, pivots)
        breakout = self._detect_breakout_structure(bars, ema20, pivots)
        mtr = self._detect_major_reversal_structure(bars, ema20, pivots)

        last_5 = bars[-5:]
        lines: List[str] = []
        lines.append("以下是按 Price Action 规则整理后的结构化上下文，只能基于这些价格行为做判断。")
        lines.append("")
        lines.append("一、背景与市场状态：")
        lines.append(f"- 市场状态：{ctx['state']}")
        lines.append(f"- Always In：{ctx['always_in']}")
        lines.append(f"- 近20根 bull/bear/tr：{ctx['bull_trend_bars']}/{ctx['bear_trend_bars']}/{ctx['tr_bars']}")
        lines.append(f"- 重叠K线数：{ctx['overlap_count']}")
        lines.append(f"- 区间位置：{ctx['range_position']:.2f}")
        lines.append(f"- 复杂调整/TBTL：{'是' if ctx['tbtl']['qualified'] else '否'}")
        lines.append("")
        lines.append("二、候选形态：")
        lines.append(f"- 回调候选：{pullback['pattern_name']} / signal_ready={'是' if pullback['signal_ready'] else '否'}")
        lines.append(f"- 突破候选：{'是' if breakout['is_breakout'] else '否'} / 跟随={'是' if breakout['has_follow_through'] else '否'}")
        lines.append(f"- 大反转候选：{'是' if mtr['candidate'] else '否'} / signal_ready={'是' if mtr['signal_ready'] else '否'}")
        lines.append("")
        lines.append("三、最近5根K线明细：")
        for x in last_5:
            lines.append(
                f"- {x.trade_date}: O={self._fmt_num(x.open_price)}, H={self._fmt_num(x.high_price)}, "
                f"L={self._fmt_num(x.low_price)}, C={self._fmt_num(x.close_price)}"
            )
        return "\n".join(lines)

    def _infer_recent_high(self, bars: List[KLineBar]) -> float:
        pivots = self._extract_pivots(bars)
        return self._latest_major_pivot(pivots, "high", default_price=max(x.high_price for x in bars[-20:]))

    def _infer_recent_low(self, bars: List[KLineBar]) -> float:
        pivots = self._extract_pivots(bars)
        return self._latest_major_pivot(pivots, "low", default_price=min(x.low_price for x in bars[-20:]))

    @staticmethod
    def _avg_range(bars: List[KLineBar]) -> float:
        if not bars:
            return 0.0
        return sum(max(x.high_price - x.low_price, 1e-9) for x in bars) / len(bars)

    @staticmethod
    def _avg_body(bars: List[KLineBar]) -> float:
        if not bars:
            return 0.0
        return sum(abs(x.close_price - x.open_price) for x in bars) / len(bars)

    @staticmethod
    def _ema(values: List[float], period: int) -> List[float]:
        if not values:
            return []
        alpha = 2 / (period + 1)
        result = [float(values[0])]
        for v in values[1:]:
            result.append(alpha * float(v) + (1 - alpha) * result[-1])
        return result

    @staticmethod
    def _bar_kind(bar: KLineBar) -> Literal["bull_trend", "bear_trend", "tr_bar"]:
        bar_range = max(bar.high_price - bar.low_price, 1e-9)
        body = abs(bar.close_price - bar.open_price)
        upper_tail = bar.high_price - max(bar.open_price, bar.close_price)
        lower_tail = min(bar.open_price, bar.close_price) - bar.low_price
        body_ratio = body / bar_range
        upper_tail_ratio = upper_tail / bar_range
        lower_tail_ratio = lower_tail / bar_range

        if bar.close_price > bar.open_price and body_ratio >= TREND_BAR_BODY_RATIO and upper_tail_ratio <= TREND_BAR_MAX_TAIL_RATIO:
            return "bull_trend"
        if bar.close_price < bar.open_price and body_ratio >= TREND_BAR_BODY_RATIO and lower_tail_ratio <= TREND_BAR_MAX_TAIL_RATIO:
            return "bear_trend"
        return "tr_bar"

    @staticmethod
    def _is_overlap(prev_bar: KLineBar, curr_bar: KLineBar) -> bool:
        overlap = min(prev_bar.high_price, curr_bar.high_price) - max(prev_bar.low_price, curr_bar.low_price)
        return overlap > 0

    @staticmethod
    def _bull_micro_channel_len(bars: List[KLineBar]) -> int:
        if len(bars) < 2:
            return 1
        length = 1
        for i in range(len(bars) - 1, 0, -1):
            if bars[i].low_price >= bars[i - 1].low_price:
                length += 1
            else:
                break
        return length

    @staticmethod
    def _bear_micro_channel_len(bars: List[KLineBar]) -> int:
        if len(bars) < 2:
            return 1
        length = 1
        for i in range(len(bars) - 1, 0, -1):
            if bars[i].high_price <= bars[i - 1].high_price:
                length += 1
            else:
                break
        return length

    @staticmethod
    def _tail_heavy(bar: KLineBar) -> bool:
        bar_range = max(bar.high_price - bar.low_price, 1e-9)
        body = abs(bar.close_price - bar.open_price)
        return body / bar_range < 0.35

    def _describe_signal_bar(self, bar: KLineBar, prev_bar: Optional[KLineBar], avg_range: float) -> str:
        bar_range = max(bar.high_price - bar.low_price, 1e-9)
        near_high = bar.close_price >= bar.high_price - 0.25 * bar_range
        near_low = bar.close_price <= bar.low_price + 0.25 * bar_range
        big = bar_range >= max(avg_range * 1.2, 1e-9)
        direction = "阳线" if bar.close_price >= bar.open_price else "阴线"
        size = "大" if big else "普通"
        if prev_bar is not None:
            shape = self._classify_bar_shape(prev_bar, bar)
            shape_text = "孕线" if shape["inside"] else "吞噬线" if shape["outside"] else "普通结构"
        else:
            shape_text = "普通结构"
        close_pos = "收近高点" if near_high else ("收近低点" if near_low else "收盘居中")
        return f"{size}{direction}，{shape_text}，{close_pos}"

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
    analyzer = PriceActionBuyPointAnalyzer(model=model, enable_thinking=enable_thinking)
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
    result = analyze_buy_point(symbol="TEST.SH", bars=sample_bars, model="qwen-plus", enable_thinking=True)
    print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2))
