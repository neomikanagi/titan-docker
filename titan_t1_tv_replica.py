"""
Titan T1 — 尽量与 TradingView Pine 策略逐条对齐的本地复刻。

对齐要点：
- SuperTrend：与 Pine 相同顺序 —— 先算 raw 上下轨，再 nz(up[1], raw_up)、nz(dn[1], raw_dn)，
  再更新 up_val/dn_val，趋势翻转使用「翻转前」的 dn1/up1（即 nz(prev_final, raw)）。
- ATR：changeATR=true 时与 ta.atr(period) 一致（TR 的 RMA）。
- 止损：ta.atr(14)（与 Pine 一致），与 ST 所用周期分离。
- RSI：ta.rsi（Wilder / RMA），非 rolling().mean()。
- 入场：raw_long 在 bar t；Pine 的 delayed_longCondition = raw_long[1]，故在 bar t 用 raw_long[t-1] 触发入场（与 TV 默认「下一根执行」一致）。
- 执行顺序：与 Pine 源码一致 —— 先 entry，再各类 close（同根可能先买后卖）。

依赖：pandas, numpy, yfinance（仅示例下载时）

仍可能与 TV 图表存在微小差异的来源：
- 数据源：yfinance 与 TV 的 symbol/复权/会话时间不一致；
- Pine 的 ta.stdev 与 pandas 在极短窗口或 na 处理上可能有细微差别；
- re_entry 在 Pine 中依赖「上一根 bar 末 position_size」与「当前 bar」的相对关系，本地用「上一根末由多转空」的离散定义近似（见 simulate_strategy 文档字符串）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np
import pandas as pd

# =============================================================================
# 默认参数（与 Pine input 一致，可按需修改）
# =============================================================================
@dataclass
class TitanT1Params:
    ema_len: int = 200
    change_atr: bool = True  # True: ta.atr；False: sma(tr, period)
    st_period: int = 10
    st_mult: float = 2.5
    confirm_bars: int = 2
    bb_len: int = 20
    bb_mult: float = 2.0
    rsi_len: int = 14
    rsi_oversold: int = 30
    vrev_ema_filter: bool = False
    use_trailing_sl: bool = True
    sl_atr_mult: float = 3.0
    catastrophic_sl_mult: float = 5.0


def _nz(x: float, y: float) -> float:
    """对应 Pine nz(a,b)：a 为 nan 时用 b。"""
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return y
    return float(x)


def calculate_tv_rma(series: pd.Series, length: int) -> pd.Series:
    """TradingView RMA（Wilder），与 ta.rma / ta.atr 内核一致。"""
    alpha = 1.0 / length
    arr = series.astype(float).values
    n = len(arr)
    out = np.full(n, np.nan, dtype=float)
    valid = np.where(~np.isnan(arr))[0]
    if len(valid) == 0:
        return pd.Series(out, index=series.index)
    start = int(valid[0])
    if start + length - 1 >= n:
        return pd.Series(out, index=series.index)
    seed = start + length - 1
    out[seed] = np.nanmean(arr[start : start + length])
    for i in range(seed + 1, n):
        if np.isnan(arr[i]):
            out[i] = out[i - 1]
        else:
            out[i] = alpha * arr[i] + (1 - alpha) * out[i - 1]
    return pd.Series(out, index=series.index)


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr


def atr_like_pine(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int, change_atr: bool
) -> pd.Series:
    tr = true_range(high, low, close)
    if change_atr:
        return calculate_tv_rma(tr, period)
    return tr.rolling(period).mean()


def supertrend_like_pine(
    hl2: pd.Series,
    close: pd.Series,
    atr_st: pd.Series,
    multiplier: float,
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    与 Pine f_Supertrend_Custom 同一顺序：
    1) raw up_val / dn_val
    2) up1 = nz(up[1], raw_up), dn1 = nz(dn[1], raw_dn)  —— 用于趋势翻转
    3) trend 用 close 与 up1、dn1（非 min/max 之后）
    4) 再更新本根最终 up_val、dn_val（max / min）
    """
    n = len(close)
    up_raw = hl2 - multiplier * atr_st
    dn_raw = hl2 + multiplier * atr_st

    up_final = np.full(n, np.nan, dtype=float)
    dn_final = np.full(n, np.nan, dtype=float)
    trend = np.ones(n, dtype=np.int8)

    c = close.astype(float).values
    ur = up_raw.astype(float).values
    dr = dn_raw.astype(float).values
    atrv = atr_st.astype(float).values

    for i in range(n):
        if np.isnan(atrv[i]):
            continue

        if i == 0:
            up_final[i] = ur[i]
            dn_final[i] = dr[i]
            trend[i] = 1
            continue

        # 与 Pine：up1_val := nz(up_val[1], up_val)；dn1_val := nz(dn_val[1], dn_val)（此处 up/dn 为 raw）
        up1 = _nz(up_final[i - 1], ur[i])
        dn1 = _nz(dn_final[i - 1], dr[i])

        tv = int(trend[i - 1])
        if tv == -1 and c[i] > dn1:
            tv = 1
        elif tv == 1 and c[i] < up1:
            tv = -1
        trend[i] = tv

        # up_val := close[1] > up1 ? max(up_val, up1) : up_val
        if c[i - 1] > up1:
            up_final[i] = max(ur[i], up1)
        else:
            up_final[i] = ur[i]

        # dn_val := close[1] < dn1 ? min(dn_val, dn1) : dn_val
        if c[i - 1] < dn1:
            dn_final[i] = min(dr[i], dn1)
        else:
            dn_final[i] = dr[i]

    st_trend = pd.Series(trend, index=close.index)
    up_s = pd.Series(up_final, index=close.index)
    dn_s = pd.Series(dn_final, index=close.index)
    return st_trend, up_s, dn_s


def rsi_like_pine(close: pd.Series, length: int) -> pd.Series:
    """ta.rsi：平均涨跌为 RMA(Wilder)。"""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = calculate_tv_rma(gain, length)
    avg_loss = calculate_tv_rma(loss, length)
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi


def bb_basis_stdev_like_pine(close: pd.Series, length: int, mult: float) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """Bollinger：SMA + mult * stdev；Pine ta.stdev 与样本标准差一致（ddof=1）。"""
    basis = close.rolling(length).mean()
    dev = close.rolling(length).std(ddof=1)
    lower = basis - mult * dev
    upper = basis + mult * dev
    return basis, lower, upper


def compute_indicators(df: pd.DataFrame, p: TitanT1Params) -> pd.DataFrame:
    """仅指标与「每根 K 线」信号，不含仓位。"""
    o = df.copy()
    high, low, close = o["High"], o["Low"], o["Close"]
    hl2 = (high + low) / 2.0

    atr_st = atr_like_pine(high, low, close, p.st_period, p.change_atr)
    atr14 = atr_like_pine(high, low, close, 14, p.change_atr)

    st_trend, up_val, dn_val = supertrend_like_pine(hl2, close, atr_st, p.st_mult)
    o["ATR_ST"] = atr_st
    o["ATR14"] = atr14
    o["ST_Trend"] = st_trend
    o["ST_UpVal"] = up_val
    o["ST_DnVal"] = dn_val

    o["EMA_200"] = close.ewm(span=p.ema_len, adjust=False).mean()

    below_ema = close < o["EMA_200"]
    o["Exit_Trend_Long"] = (
        below_ema.astype(int).rolling(p.confirm_bars).sum() >= p.confirm_bars
    )

    basis, bb_lower, bb_upper = bb_basis_stdev_like_pine(close, p.bb_len, p.bb_mult)
    o["BB_Basis"] = basis
    o["BB_Lower"] = bb_lower
    o["BB_Upper"] = bb_upper

    o["RSI"] = rsi_like_pine(close, p.rsi_len)

    st_flip_up = (st_trend == 1) & (st_trend.shift(1) == -1)
    trend_following = st_flip_up & (close > o["EMA_200"])

    bb_bounce = (close.shift(1) <= o["BB_Lower"].shift(1)) & (close > o["BB_Lower"])
    bb_cross_mid = (close.shift(1) <= o["BB_Basis"].shift(1)) & (close > o["BB_Basis"])
    rsi_cross = (o["RSI"].shift(1) <= p.rsi_oversold) & (o["RSI"] > p.rsi_oversold)
    v_rev = bb_bounce & bb_cross_mid & rsi_cross
    if p.vrev_ema_filter:
        v_rev = v_rev & (close > o["EMA_200"])

    o["Trend_Following_Entry"] = trend_following
    o["V_Reversal_Entry"] = v_rev
    o["Raw_Long"] = o["Trend_Following_Entry"] | o["V_Reversal_Entry"]
    # Pine: delayed_longCondition = raw_longCondition[1]
    o["Delayed_Long"] = o["Raw_Long"].shift(1).fillna(False).astype(bool)

    return o


@dataclass
class StrategyState:
    position_size: int = 0
    is_v_reversal_entry: bool = False
    trail_long_sl: float = float("nan")
    position_avg_price: float = float("nan")


def simulate_strategy(o: pd.DataFrame, p: TitanT1Params) -> pd.DataFrame:
    """
    按 Pine 块顺序：先写 is_v_reversal_entry，再 entry，再 trailing / trend / catastrophic。

    re_entry：Pine 为 position_size[1]>0 且 position_size==0。日线离散化下采用：
    上一根末由持多变为空仓（pos_end[t-2]==1 且 pos_end[t-1]==0），且本根 ST 为多、收盘>EMA。
    """
    close = o["Close"].astype(float)
    atr14 = o["ATR14"].astype(float)
    st_trend = o["ST_Trend"].astype(int)
    ema = o["EMA_200"].astype(float)
    v_rev_col = o["V_Reversal_Entry"].astype(bool)

    n = len(o)
    pos = np.zeros(n, dtype=np.int8)
    is_vrev = np.zeros(n, dtype=bool)
    trail = np.full(n, np.nan, dtype=float)
    avg_px = np.full(n, np.nan, dtype=float)

    ev_entry = [None] * n
    ev_exit = [None] * n

    state = StrategyState()
    pos_end_prev = 0
    pos_end_prev2 = 0

    for t in range(n):
        c = float(close.iloc[t])
        a14 = float(atr14.iloc[t]) if not np.isnan(atr14.iloc[t]) else np.nan

        state.position_size = pos_end_prev

        delayed = bool(o["Delayed_Long"].iloc[t])
        re_entry = (
            t >= 2
            and pos_end_prev2 == 1
            and pos_end_prev == 0
            and int(st_trend.iloc[t]) == 1
            and c > float(ema.iloc[t])
        )

        entry_signal = delayed or re_entry

        if entry_signal and state.position_size == 0:
            v_rev_prev = bool(v_rev_col.iloc[t - 1]) if t > 0 else False
            state.is_v_reversal_entry = v_rev_prev or re_entry

        has_long = state.position_size > 0

        if entry_signal and (not has_long):
            state.position_size = 1
            state.position_avg_price = c
            if not np.isnan(a14):
                state.trail_long_sl = c - a14 * p.sl_atr_mult
            ev_entry[t] = "RE-BUY" if re_entry else "BUY"

        has_long = state.position_size > 0

        if p.use_trailing_sl and has_long and state.is_v_reversal_entry and not np.isnan(a14):
            sl_level = c - a14 * p.sl_atr_mult
            prev_tr = state.trail_long_sl
            if np.isnan(prev_tr):
                state.trail_long_sl = sl_level
            else:
                state.trail_long_sl = max(prev_tr, sl_level)
            if c < state.trail_long_sl:
                ev_exit[t] = "V-Rev SL"
                state.position_size = 0
                state.is_v_reversal_entry = False

        has_long = state.position_size > 0
        et = bool(o["Exit_Trend_Long"].iloc[t])

        if has_long:
            if et and (not state.is_v_reversal_entry):
                ev_exit[t] = "Trend SELL"
                state.position_size = 0
                state.is_v_reversal_entry = False
            elif et and state.is_v_reversal_entry and (not p.use_trailing_sl):
                ev_exit[t] = "Trend SELL"
                state.position_size = 0
                state.is_v_reversal_entry = False

        has_long = state.position_size > 0
        if has_long and not np.isnan(a14):
            cat = state.position_avg_price - a14 * p.catastrophic_sl_mult
            if c < cat:
                ev_exit[t] = "CAT SL"
                state.position_size = 0
                state.is_v_reversal_entry = False

        pos[t] = state.position_size
        is_vrev[t] = state.is_v_reversal_entry
        trail[t] = state.trail_long_sl
        avg_px[t] = state.position_avg_price

        pos_end_prev2 = pos_end_prev
        pos_end_prev = int(state.position_size)

    o = o.copy()
    o["Sim_Position"] = pos
    o["Sim_IsVRev"] = is_vrev
    o["Sim_TrailSL"] = trail
    o["Sim_AvgPx"] = avg_px
    o["Sim_Entry"] = ev_entry
    o["Sim_Exit"] = ev_exit
    return o


def run_yfinance_example(
    ticker: str = "^NYFANG",
    period: str = "2y",
    interval: str = "1d",
    params: Optional[TitanT1Params] = None,
) -> pd.DataFrame:
    import yfinance as yf

    p = params or TitanT1Params()
    df = yf.download(ticker, period=period, interval=interval, progress=False)
    if df.empty:
        raise RuntimeError("yfinance 返回空数据")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
    df = compute_indicators(df, p)
    df = simulate_strategy(df, p)
    return df


if __name__ == "__main__":
    pd.set_option("display.width", 200)
    p = TitanT1Params()
    out = run_yfinance_example(params=p)
    tail = out[
        [
            "Close",
            "ST_Trend",
            "EMA_200",
            "Raw_Long",
            "Delayed_Long",
            "Sim_Position",
            "Sim_Entry",
            "Sim_Exit",
        ]
    ].tail(15)
    print(tail.to_string())
