
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, List, Optional, Literal

from openai import OpenAI
from pydantic import BaseModel, Field, ConfigDict, ValidationError, field_validator, model_validator

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

    def _rule_based_analysis(self, data: PriceActionInput) -> PriceActionDecision:
        bars = data.bars
        closes = [x.close_price for x in bars]
        highs = [x.high_price for x in bars]
        lows = [x.low_price for x in bars]
        opens = [x.open_price for x in bars]

        recent_high = data.recent_high if data.recent_high is not None else self._infer_recent_high(bars)
        recent_low = data.recent_low if data.recent_low is not None else self._infer_recent_low(bars)

        avg_range_10 = self._avg_range(bars[-10:])
        avg_range_20 = self._avg_range(bars[-20:])
        avg_body_20 = self._avg_body(bars[-20:])

        ema20 = self._ema(closes, 20)
        ema20_last = ema20[-1]
        ema20_prev5 = ema20[-6] if len(ema20) >= 6 else ema20[0]
        ema20_slope = ema20_last - ema20_prev5

        bull_trend_bars_20 = 0
        bear_trend_bars_20 = 0
        tr_bars_20 = 0
        overlap_count_20 = 0

        for i, bar in enumerate(bars[-20:], start=len(bars) - 20):
            kind = self._bar_kind(bar)
            if kind == "bull_trend":
                bull_trend_bars_20 += 1
            elif kind == "bear_trend":
                bear_trend_bars_20 += 1
            else:
                tr_bars_20 += 1

            if i > 0 and self._is_overlap(bars[i - 1], bars[i]):
                overlap_count_20 += 1

        bull_micro = self._bull_micro_channel_len(bars)
        bear_micro = self._bear_micro_channel_len(bars)

        pivots = self._extract_pivots(bars)
        major_low = self._latest_major_pivot(pivots, "low", default_price=min(lows[-20:]))
        major_high = self._latest_major_pivot(pivots, "high", default_price=max(highs[-20:]))

        range20_high = max(highs[-20:])
        range20_low = min(lows[-20:])
        range20 = max(range20_high - range20_low, 1e-9)
        current_close = closes[-1]
        location_in_20 = (current_close - range20_low) / range20

        up_breakout = self._detect_bull_breakout(bars, avg_range_20, avg_body_20, ema20_last)
        breakout_follow_through = self._detect_breakout_follow_through(bars, direction="up", avg_body=avg_body_20)

        bull_channel_strength = 0
        if current_close > ema20_last:
            bull_channel_strength += 1
        if ema20_slope > 0:
            bull_channel_strength += 1
        if bull_trend_bars_20 > bear_trend_bars_20:
            bull_channel_strength += 1
        if overlap_count_20 <= 8:
            bull_channel_strength += 1
        if highs[-1] >= highs[-5]:
            bull_channel_strength += 1

        bear_channel_strength = 0
        if current_close < ema20_last:
            bear_channel_strength += 1
        if ema20_slope < 0:
            bear_channel_strength += 1
        if bear_trend_bars_20 > bull_trend_bars_20:
            bear_channel_strength += 1
        if overlap_count_20 <= 8:
            bear_channel_strength += 1
        if lows[-1] <= lows[-5]:
            bear_channel_strength += 1

        pullback_info = self._detect_bull_pullback(bars, ema20)
        wedge_info = self._detect_bull_wedge(bars, pivots)
        reversal_info = self._detect_bull_reversal(bars, ema20, pivots, avg_range_20)

        if overlap_count_20 >= 10 or tr_bars_20 >= 10 or (pullback_info["duration"] >= 20):
            channel_name = "震荡区间 / 宽幅双向交易环境"
            channel_support_buy = "否"
            channel_state = "trading_range"
        elif bull_channel_strength >= 4 and pullback_info["depth"] <= avg_range_20 * 2.5:
            if bull_micro >= 5:
                channel_name = "强势多头通道 / 近期存在微通道特征"
            else:
                channel_name = "多头通道"
            channel_support_buy = "是"
            channel_state = "bull_channel"
        elif bear_channel_strength >= 4 and not reversal_info["qualified"]:
            channel_name = "空头通道 / 当前仍受下行背景压制"
            channel_support_buy = "否"
            channel_state = "bear_channel"
        elif bull_channel_strength >= 3 and overlap_count_20 <= 11:
            channel_name = "宽多头通道 / 偏多但双向波动较多"
            channel_support_buy = "谨慎，需在边缘或确认后"
            channel_state = "broad_bull_channel"
        elif reversal_info["qualified"]:
            channel_name = "空转多早期 / 反转尝试已形成"
            channel_support_buy = "有条件支持"
            channel_state = "bull_reversal"
        else:
            channel_name = "通道不清晰 / 更接近震荡"
            channel_support_buy = "否"
            channel_state = "unclear"

        current_pattern = "未形成允许的买点结构"
        pattern_allowed_type = "否"
        key_candle = self._describe_last_bar(bars[-1], avg_range_10)
        has_follow_through = "否"
        can_trigger_buy = "否"
        expected_entry = "等待更靠近关键支撑、区间下沿、突破回踩位或 major higher low 的位置"
        trigger_condition = "需要先出现允许的买点类型，并给出明确止损与结构目标"
        buy_price = None
        stop_loss = None
        take_profit = None
        reason_parts: List[str] = []

        # A. 趋势中的回调买点
        trend_pullback_ok = False
        if channel_state in {"bull_channel", "broad_bull_channel"}:
            first_pullback_ok = bull_micro >= 5 and 1 <= pullback_info["duration"] <= 5 and pullback_info["attempts"] <= 1
            h2_ok = pullback_info["attempts"] >= 2 and pullback_info["signal_ready"]
            wedge_ok = wedge_info["qualified"]
            shallow_ok = pullback_info["depth"] <= avg_range_20 * 2.5 and pullback_info["held_above_major_low"]

            if shallow_ok and (first_pullback_ok or h2_ok or wedge_ok):
                trend_pullback_ok = True
                current_pattern = pullback_info["pattern_name"] if not wedge_ok else wedge_info["pattern_name"]
                pattern_allowed_type = "是，属于趋势中的回调买点"
                key_candle = pullback_info["signal_bar_text"] if not wedge_ok else wedge_info["signal_bar_text"]
                has_follow_through = "是" if pullback_info["has_follow_through"] or channel_state == "bull_channel" else "否"
                can_trigger_buy = "是" if pullback_info["signal_ready"] or wedge_info["signal_ready"] else "否"

                if pullback_info["signal_ready"] or wedge_info["signal_ready"]:
                    entry_ref = max(bars[-1].high_price, bars[-2].high_price if len(bars) >= 2 else bars[-1].high_price)
                    buy_price = f"突破 {self._fmt_num(entry_ref)} 上方可执行买入"
                    stop_anchor = min(pullback_info["swing_low"], major_low)
                    stop_loss = f"{self._fmt_num(stop_anchor)} 下方（主要拐点 / 回调失效位）"
                    target_1 = max(recent_high, range20_high)
                    risk = max(entry_ref - stop_anchor, avg_range_20 * 0.8)
                    mm_target = entry_ref + 2 * risk
                    take_profit = f"先看 {self._fmt_num(target_1)}，强势则看 {self._fmt_num(mm_target)} 的测量移动目标"
                    expected_entry = None
                    trigger_condition = None
                    reason_parts.append("当前背景仍以多头通道/偏多通道为主，属于顺势回调而非震荡中部追涨。")
                    if bull_micro >= 5:
                        reason_parts.append("前段微通道后首次回调通常更偏向趋势延续，而非直接反转。")
                    if h2_ok:
                        reason_parts.append("回调中已出现 H2/二次恢复尝试，更符合 Brooks 体系中的顺势入场。")
                    if wedge_ok:
                        reason_parts.append("回调末端具备三推楔形牛旗特征，属于允许的趋势回调买点。")
                else:
                    reason_parts.append("背景偏多，但信号K尚未完成触发，仍需等待突破信号高点。")

        # B. 有效突破后的买点
        breakout_ok = False
        if not trend_pullback_ok and up_breakout["qualified"]:
            strong_same_bar = up_breakout["strong"] and channel_state in {"bull_channel", "broad_bull_channel"} and up_breakout["close_near_high"]
            confirmed_breakout = breakout_follow_through["qualified"]
            if confirmed_breakout or strong_same_bar:
                breakout_ok = True
                current_pattern = "有效向上突破" if confirmed_breakout else "强势突破K直接入场"
                pattern_allowed_type = "是，属于有效突破后的买点"
                key_candle = up_breakout["text"]
                has_follow_through = "是" if confirmed_breakout else "强突破同K可入场"
                can_trigger_buy = "是"

                breakout_level = up_breakout["breakout_level"]
                entry_ref = bars[-1].close_price if strong_same_bar and not confirmed_breakout else max(bars[-1].high_price, breakout_level)
                stop_anchor = min(up_breakout["protective_low"], major_low)
                buy_price = f"{self._fmt_num(entry_ref)} 附近执行，优先按突破延续或回踩突破位处理"
                stop_loss = f"{self._fmt_num(stop_anchor)} 下方（突破失效位 / 主要拐点）"
                risk = max(entry_ref - stop_anchor, avg_range_20 * 0.8)
                target_1 = breakout_level + (range20_high - range20_low)
                target_2 = entry_ref + 2 * risk
                take_profit = f"先看 {self._fmt_num(max(target_1, recent_high))}，强势则看 {self._fmt_num(max(target_1, target_2))}"
                expected_entry = None
                trigger_condition = None
                reason_parts.append("当前不是在震荡区间中部盲目追价，而是对明确突破进行交易。")
                if confirmed_breakout:
                    reason_parts.append("突破后已有同向 follow-through，突破成功概率明显提升。")
                else:
                    reason_parts.append("当前K线本身足够强，符合 Brooks 体系里强突破同K入场的例外情况。")
            else:
                reason_parts.append("虽有突破尝试，但缺乏合格 follow-through，按区间/失败突破优先处理。")

        # C. 强反转买点
        reversal_ok = False
        if not trend_pullback_ok and not breakout_ok and reversal_info["qualified"]:
            reversal_ok = True
            current_pattern = reversal_info["pattern_name"]
            pattern_allowed_type = "是，属于强反转买点"
            key_candle = reversal_info["signal_bar_text"]
            has_follow_through = "是" if reversal_info["has_follow_through"] else "否"
            can_trigger_buy = "是" if reversal_info["signal_ready"] else "否"

            if reversal_info["signal_ready"] and reversal_info["has_follow_through"]:
                entry_ref = reversal_info["entry_price"]
                stop_anchor = reversal_info["stop_price"]
                target_1 = max(recent_high, reversal_info["first_target"])
                risk = max(entry_ref - stop_anchor, avg_range_20 * 0.8)
                target_2 = entry_ref + 2 * risk
                buy_price = f"突破 {self._fmt_num(entry_ref)} 上方可执行买入"
                stop_loss = f"{self._fmt_num(stop_anchor)} 下方（反转失效位 / 双底或楔形低点）"
                take_profit = f"先看 {self._fmt_num(target_1)}，强势则看 {self._fmt_num(max(target_1, target_2))}"
                expected_entry = None
                trigger_condition = None
                reason_parts.append("此前下行背景已先被破坏，再出现反转结构与强信号K，不是单根阳线主观抄底。")
                reason_parts.append("反转已获得跟随确认，更符合站点要求的结构 + 信号 + follow-through。")
            else:
                reason_parts.append("反转结构初步形成，但若无跟随确认，仍不能视为可执行买点。")

        # 震荡区间中部硬性过滤
        in_middle = 0.33 <= location_in_20 <= 0.67
        if channel_state == "trading_range" and in_middle:
            trend_pullback_ok = breakout_ok = reversal_ok = False
            current_pattern = "震荡区间中部"
            pattern_allowed_type = "否"
            has_follow_through = "否"
            can_trigger_buy = "否"
            buy_price = None
            stop_loss = None
            take_profit = None
            expected_entry = "更合理的位置是区间下沿附近，或等待真正突破并出现强 follow-through"
            trigger_condition = "脱离区间中部后，再看边缘反转或有效突破"
            reason_parts.append("当前价格位于近20根区间中部，Brooks 体系中这是明确的回避区域。")

        # 空头通道未完成反转硬性过滤
        if channel_state == "bear_channel" and not reversal_ok:
            trend_pullback_ok = breakout_ok = False
            current_pattern = "空头通道中的反弹 / 结构尚未完成扭转"
            pattern_allowed_type = "否"
            has_follow_through = "否"
            can_trigger_buy = "否"
            buy_price = None
            stop_loss = None
            take_profit = None
            expected_entry = "等待先破坏空头结构，再观察双底、楔形底或 major higher low"
            trigger_condition = "至少需要趋势线/EMA20 破位、反转信号K、以及 follow-through"
            reason_parts.append("当前仍受空头通道压制，站点规则下不能把普通反弹当成买点。")

        qualified_buy = trend_pullback_ok or breakout_ok or reversal_ok
        if qualified_buy and buy_price and stop_loss and take_profit:
            conclusion = "买"
            channel_support_buy_final = channel_support_buy
            if not reason_parts:
                reason_parts.append("背景、形态、信号、触发、止损和目标均已具备。")
        else:
            conclusion = "不买"
            buy_price = None
            stop_loss = None
            take_profit = None
            channel_support_buy_final = channel_support_buy if channel_support_buy != "是" else "是，但当前触发未完成"
            if not reason_parts:
                reason_parts.append("当前结构没有同时满足背景、形态、信号、触发、止损和目标。")
            if expected_entry is None:
                expected_entry = "等待更优结构出现后再介入"
            if trigger_condition is None:
                trigger_condition = "需要先完成允许的买点结构，并给出清晰止损和目标"

        reason = " ".join(reason_parts).strip()
        if not reason:
            reason = "当前图表未形成符合 Price Action 规则的可执行买点。"

        return PriceActionDecision(
            conclusion=conclusion,
            current_channel=channel_name,
            channel_support_buy=channel_support_buy_final,
            current_pattern=current_pattern,
            pattern_allowed_type=pattern_allowed_type,
            key_candle=key_candle,
            has_follow_through=has_follow_through,
            can_trigger_buy=can_trigger_buy,
            expected_entry=expected_entry,
            trigger_condition=trigger_condition,
            buy_price=buy_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            reason=reason,
        )

    def _detect_bull_pullback(self, bars: List[KLineBar], ema20: List[float]) -> dict:
        n = len(bars)
        avg_range = self._avg_range(bars[-20:])
        recent_window = bars[-12:] if n >= 12 else bars
        highest_before_last = max(x.high_price for x in bars[-20:-1]) if n >= 21 else max(x.high_price for x in bars[:-1])

        # 从最近的局部高点开始估计本轮回调
        pullback_start = n - 1
        highest_seen = bars[-1].high_price
        for i in range(n - 2, max(-1, n - 12), -1):
            if bars[i].high_price >= highest_seen:
                pullback_start = i
                highest_seen = bars[i].high_price
            else:
                break

        duration = n - 1 - pullback_start
        swing_high = max(x.high_price for x in bars[max(0, pullback_start - 2):pullback_start + 1])
        swing_low = min(x.low_price for x in bars[pullback_start:])
        depth = max(swing_high - swing_low, 0.0)

        attempts = 0
        last_signal_idx = None
        for i in range(max(pullback_start + 1, 1), n):
            if bars[i].high_price > bars[i - 1].high_price:
                attempts += 1
                last_signal_idx = i

        bull_signal = False
        signal_bar_text = self._describe_last_bar(bars[-1], avg_range)
        if n >= 2:
            bull_signal = (
                bars[-1].close_price > bars[-1].open_price
                and bars[-1].close_price >= (bars[-1].high_price - 0.25 * max(bars[-1].high_price - bars[-1].low_price, 1e-9))
            ) or (bars[-1].high_price > bars[-2].high_price and bars[-1].close_price >= bars[-2].close_price)

        has_follow_through = False
        if n >= 2:
            has_follow_through = (
                bars[-1].close_price > bars[-1].open_price
                and bars[-2].close_price > bars[-2].open_price
                and bars[-1].close_price >= bars[-2].close_price
            )

        if duration <= 1 and bars[-1].high_price >= highest_before_last:
            pattern_name = "强势延续 / 非典型回调"
        elif attempts <= 1:
            pattern_name = "首次回调候选 / H1 候选"
        elif attempts == 2:
            pattern_name = "H2 / 双腿回调"
        else:
            pattern_name = "多腿回调，需警惕震荡化"

        major_low = min(x.low_price for x in bars[-40:]) if n >= 40 else min(x.low_price for x in bars)
        held_above_major_low = swing_low > major_low or abs(swing_low - major_low) <= avg_range * 0.3

        return {
            "duration": duration,
            "depth": depth,
            "attempts": attempts,
            "pattern_name": pattern_name,
            "signal_ready": bull_signal,
            "signal_bar_text": signal_bar_text,
            "has_follow_through": has_follow_through,
            "swing_low": swing_low,
            "held_above_major_low": held_above_major_low,
        }

    def _detect_bull_wedge(self, bars: List[KLineBar], pivots: List[PivotPoint]) -> dict:
        low_pivots = [p for p in pivots if p.kind == "low"]
        if len(low_pivots) < 3:
            return {
                "qualified": False,
                "pattern_name": "未形成楔形牛旗",
                "signal_ready": False,
                "signal_bar_text": self._describe_last_bar(bars[-1], self._avg_range(bars[-10:])),
            }

        last3 = low_pivots[-3:]
        spacing_ok = (last3[1].index - last3[0].index >= 2) and (last3[2].index - last3[1].index >= 2)
        prices = [p.price for p in last3]
        compressing = prices[0] >= prices[1] >= prices[2] or (max(prices) - min(prices) <= self._avg_range(bars[-20:]) * 2.5)
        last_bar = bars[-1]
        signal_ready = last_bar.close_price > last_bar.open_price and last_bar.close_price >= (last_bar.high_price - 0.3 * max(last_bar.high_price - last_bar.low_price, 1e-9))
        return {
            "qualified": spacing_ok and compressing,
            "pattern_name": "楔形牛旗 / 三推回调",
            "signal_ready": signal_ready,
            "signal_bar_text": self._describe_last_bar(last_bar, self._avg_range(bars[-10:])),
        }

    def _detect_bull_reversal(self, bars: List[KLineBar], ema20: List[float], pivots: List[PivotPoint], avg_range: float) -> dict:
        n = len(bars)
        if n < 25:
            return {
                "qualified": False,
                "pattern_name": "未形成强反转",
                "signal_ready": False,
                "has_follow_through": False,
                "signal_bar_text": self._describe_last_bar(bars[-1], avg_range),
                "entry_price": bars[-1].high_price,
                "stop_price": bars[-1].low_price,
                "first_target": bars[-1].high_price,
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
            double_bottom = abs(a.price - b.price) <= avg_range * 0.8
            bottom_low = min(a.price, b.price)

        wedge = self._detect_bull_wedge(bars, pivots)["qualified"]

        trendline_break = bars[-1].close_price > ema20[-1] and max(x.high_price for x in bars[-3:]) > max(x.high_price for x in bars[-8:-3])
        strong_signal = (
            bars[-1].close_price > bars[-1].open_price
            and (bars[-1].close_price - bars[-1].open_price) >= 0.5 * max(bars[-1].high_price - bars[-1].low_price, 1e-9)
            and bars[-1].close_price >= bars[-1].high_price - 0.25 * max(bars[-1].high_price - bars[-1].low_price, 1e-9)
        )
        has_follow_through = n >= 2 and (
            (bars[-1].close_price > bars[-1].open_price and bars[-2].close_price > bars[-2].open_price)
            or (bars[-1].close_price > bars[-2].high_price)
        )
        first_target = max(x.high_price for x in bars[-20:-5]) if n >= 25 else max(x.high_price for x in bars[-10:])
        qualified = prior_bearish and trendline_break and (double_bottom or wedge) and strong_signal

        pattern_name = "双底 / 大反转买点" if double_bottom else "楔形底 / 强反转买点"
        return {
            "qualified": qualified,
            "pattern_name": pattern_name,
            "signal_ready": strong_signal,
            "has_follow_through": has_follow_through,
            "signal_bar_text": self._describe_last_bar(bars[-1], avg_range),
            "entry_price": max(bars[-1].high_price, bars[-2].high_price if n >= 2 else bars[-1].high_price),
            "stop_price": bottom_low,
            "first_target": first_target,
        }

    def _detect_bull_breakout(self, bars: List[KLineBar], avg_range: float, avg_body: float, ema20_last: float) -> dict:
        last_bar = bars[-1]
        prev_high_20 = max(x.high_price for x in bars[-21:-1]) if len(bars) >= 21 else max(x.high_price for x in bars[:-1])
        bar_range = max(last_bar.high_price - last_bar.low_price, 1e-9)
        body = abs(last_bar.close_price - last_bar.open_price)
        strong = (
            last_bar.close_price > last_bar.open_price
            and body >= max(avg_body * 1.2, bar_range * 0.55)
            and last_bar.close_price > prev_high_20
            and last_bar.close_price > ema20_last
        )
        close_near_high = last_bar.close_price >= last_bar.high_price - 0.25 * bar_range
        qualified = strong or (last_bar.high_price > prev_high_20 and close_near_high and body >= avg_body)
        text = self._describe_last_bar(last_bar, avg_range) + f"，并向上突破 {self._fmt_num(prev_high_20)}"
        protective_low = min(last_bar.low_price, bars[-2].low_price if len(bars) >= 2 else last_bar.low_price, prev_high_20)
        return {
            "qualified": qualified,
            "strong": strong,
            "close_near_high": close_near_high,
            "text": text,
            "breakout_level": prev_high_20,
            "protective_low": protective_low,
        }

    def _detect_breakout_follow_through(self, bars: List[KLineBar], direction: str, avg_body: float) -> dict:
        if len(bars) < 2:
            return {"qualified": False}

        prev_bar = bars[-2]
        last_bar = bars[-1]

        if direction == "up":
            prev_body = abs(prev_bar.close_price - prev_bar.open_price)
            last_body = abs(last_bar.close_price - last_bar.open_price)
            qualified = (
                prev_bar.close_price > prev_bar.open_price
                and last_bar.close_price > last_bar.open_price
                and last_bar.close_price >= prev_bar.close_price
                and prev_body >= avg_body * 0.9
                and last_body >= avg_body * 0.8
            )
            return {"qualified": qualified}

        return {"qualified": False}

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
        ema20 = self._ema(closes, 20)
        n = len(bars)

        last_5 = bars[-5:]
        last_10 = bars[-10:]
        last_20 = bars[-20:]
        pivots = self._extract_pivots(bars)

        bull_trend_bars_20 = sum(1 for x in last_20 if self._bar_kind(x) == "bull_trend")
        bear_trend_bars_20 = sum(1 for x in last_20 if self._bar_kind(x) == "bear_trend")
        tr_bars_20 = sum(1 for x in last_20 if self._bar_kind(x) == "tr_bar")
        overlap_count_20 = sum(1 for i in range(1, len(last_20)) if self._is_overlap(last_20[i - 1], last_20[i]))
        bull_micro = self._bull_micro_channel_len(bars)
        bear_micro = self._bear_micro_channel_len(bars)
        pullback_info = self._detect_bull_pullback(bars, ema20)
        wedge_info = self._detect_bull_wedge(bars, pivots)
        reversal_info = self._detect_bull_reversal(bars, ema20, pivots, self._avg_range(last_20))
        breakout_info = self._detect_bull_breakout(bars, self._avg_range(last_20), self._avg_body(last_20), ema20[-1])

        range20_high = max(x.high_price for x in last_20)
        range20_low = min(x.low_price for x in last_20)
        current_close = bars[-1].close_price
        location_in_20 = (current_close - range20_low) / max(range20_high - range20_low, 1e-9)

        lines: List[str] = []
        lines.append("以下是按 Brooks Price Action 逻辑整理后的结构化上下文，只能基于这些价格行为做判断。")
        lines.append("")
        lines.append("一、背景与市场状态：")
        lines.append(f"- 样本根数：{n}")
        lines.append(f"- 最新收盘价：{self._fmt_num(current_close)}")
        lines.append(f"- EMA20 最新值：{self._fmt_num(ema20[-1])}")
        lines.append(f"- EMA20 近5根斜率：{self._fmt_num(ema20[-1] - ema20[-6] if len(ema20) >= 6 else 0)}")
        lines.append(f"- 最近20根 bull trend bar 数：{bull_trend_bars_20}")
        lines.append(f"- 最近20根 bear trend bar 数：{bear_trend_bars_20}")
        lines.append(f"- 最近20根 trading-range bar 数：{tr_bars_20}")
        lines.append(f"- 最近20根重叠K线数：{overlap_count_20}")
        lines.append(f"- 当前在近20根区间中的位置：{location_in_20:.2f}（0靠近下沿，1靠近上沿）")
        lines.append("")
        lines.append("二、通道 / 回调 / 区间：")
        lines.append(f"- Bull micro channel 连续长度：{bull_micro}")
        lines.append(f"- Bear micro channel 连续长度：{bear_micro}")
        lines.append(f"- 当前多头回调持续根数：{pullback_info['duration']}")
        lines.append(f"- 当前多头回调深度：{self._fmt_num(pullback_info['depth'])}")
        lines.append(f"- 回调中的恢复尝试次数（H1/H2 计数参考）：{pullback_info['attempts']}")
        lines.append(f"- 当前回调形态判断：{pullback_info['pattern_name']}")
        lines.append(f"- 是否守住主要低点：{'是' if pullback_info['held_above_major_low'] else '否'}")
        lines.append("")
        lines.append("三、突破 / 反转 / 楔形：")
        lines.append(f"- 最新向上突破判断：{'是' if breakout_info['qualified'] else '否'}")
        lines.append(f"- 突破说明：{breakout_info['text']}")
        lines.append(f"- 楔形牛旗候选：{'是' if wedge_info['qualified'] else '否'}")
        lines.append(f"- 强反转候选：{'是' if reversal_info['qualified'] else '否'}")
        lines.append(f"- 反转说明：{reversal_info['pattern_name']}")
        lines.append("")
        lines.append("四、最近5根K线明细（升序）：")
        for x in last_5:
            lines.append(
                f"- {x.trade_date}: O={self._fmt_num(x.open_price)}, H={self._fmt_num(x.high_price)}, "
                f"L={self._fmt_num(x.low_price)}, C={self._fmt_num(x.close_price)}"
            )
        lines.append("")
        lines.append("五、最近10根收盘价：")
        lines.append("- " + ", ".join(self._fmt_num(x.close_price) for x in last_10))
        lines.append("")
        lines.append("六、分析铁律：")
        lines.append("- 先判断是趋势还是震荡区间；若是震荡中部，优先不买。")
        lines.append("- 只允许三类买点：趋势中的回调买点、有效突破后的买点、有跟随确认的强反转买点。")
        lines.append("- EMA20、主要拐点、H1/H2、微通道首次回调、突破后的 follow-through 都必须纳入。")
        lines.append("- 强突破允许同K入场；一般突破若无 follow-through，不得轻易判定为买点。")
        lines.append("- 若止损无法放在主要拐点/失效位之外，或目标无法基于前高/区间边缘/测量移动定义，则不买。")

        return "\n".join(lines)

    def _infer_recent_high(self, bars: List[KLineBar]) -> float:
        pivots = self._extract_pivots(bars)
        for pivot in reversed(pivots):
            if pivot.kind == "high" and pivot.strength == "major":
                return pivot.price
        last_20 = bars[-20:] if len(bars) >= 20 else bars
        return max(x.high_price for x in last_20)

    def _infer_recent_low(self, bars: List[KLineBar]) -> float:
        pivots = self._extract_pivots(bars)
        for pivot in reversed(pivots):
            if pivot.kind == "low" and pivot.strength == "major":
                return pivot.price
        last_20 = bars[-20:] if len(bars) >= 20 else bars
        return min(x.low_price for x in last_20)

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

        if bar.close_price > bar.open_price and body_ratio >= 0.5 and upper_tail_ratio <= 0.25:
            return "bull_trend"
        if bar.close_price < bar.open_price and body_ratio >= 0.5 and lower_tail_ratio <= 0.25:
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

    def _describe_last_bar(self, bar: KLineBar, avg_range: float) -> str:
        bar_range = max(bar.high_price - bar.low_price, 1e-9)
        body = abs(bar.close_price - bar.open_price)
        near_high = bar.close_price >= bar.high_price - 0.25 * bar_range
        near_low = bar.close_price <= bar.low_price + 0.25 * bar_range
        big = bar_range >= max(avg_range * 1.2, 1e-9)

        direction = "阳线" if bar.close_price >= bar.open_price else "阴线"
        size = "大" if big else "普通"
        close_pos = "收近高点" if near_high else ("收近低点" if near_low else "收盘居中")
        return f"{size}{direction}，{close_pos}"

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
