"""업종 뉴스 하루 단위: 거래일 t의 뉴스 = 전 거래일 16:00 ET ~ t일 09:30 ET 발행 기사(장 외 시간, 주말·휴일 포함).
판별 v1: 그날 점수가 직전 250개 판정일 평균보다 높으면 호재, 낮으면 악재 (최소 60일).
사전 단어가 하나도 없는 날(점수 0)은 판정 없음 — 처음엔 0점도 판정했으나 판정 분포가 한쪽으로 쏠려(예: 호재 62 / 악재 575) 확인 후 수정.
① 반응: 초과 갭 = (ETF 시가/전일 종가) - (S&P 시가/전일 종가)  → 뉴스가 가격을 움직였나 (거래 불가 구간)
② 예측: 초과 장중 수익 = (ETF 종가/시가) - (S&P 종가/시가)      → 개장 전 판정으로 거래 가능한가"""
import os
import numpy as np
import pandas as pd
import pysentiment2 as ps
import yfinance as yf
from scipy import stats
from scipy.stats import spearmanr
from judge_nyt import nyt_tokens, PERIODS
from sector_nyt import SECTORS, load_all

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = f"{HERE}/output/sector_daily"
os.makedirs(OUT, exist_ok=True)


def ohlc():
    path = f"{HERE}/data/sector_etf_ohlc.csv"
    if not os.path.exists(path):
        px = yf.download(["XLK", "XLE", "XLV", "^GSPC"], start="2013-12-01", end="2026-10-10", auto_adjust=False, progress=False)
        px[["Open", "Close"]].to_csv(path)
    px = pd.read_csv(path, header=[0, 1], index_col=0, parse_dates=True)
    return px["Open"], px["Close"]


def assign_trading_day(dates, days):
    """기사 시각 → 그 기사가 '개장 전 뉴스'로 쓰이는 거래일. 16:00 이후 기사는 다음 거래일, 09:30 이전 기사는 당일."""
    t = dates.values.astype("datetime64[m]")
    d = dates.dt.normalize().values
    mins = dates.dt.hour * 60 + dates.dt.minute
    # 장중(09:30~16:00) 기사는 제외 (그날 시가 이후에 나온 뉴스라 '개장 전 판정'에 쓸 수 없음)
    pre_open = (mins < 570).values
    post_close = (mins >= 960).values
    target = np.where(pre_open, d, np.where(post_close, d + np.timedelta64(1, "D"), np.datetime64("NaT")))
    idx = np.searchsorted(days, target, side="left")          # target 날짜 이후 첫 거래일
    ok = ~np.isnat(target) & (idx < len(days))
    out = np.full(len(t), np.datetime64("NaT"), dtype="datetime64[ns]")
    out[ok] = days[idx[ok]]
    return out


if __name__ == "__main__":
    df = load_all()
    op, cl = ohlc()
    days = cl.index.values
    df["tday"] = assign_trading_day(df["date"], days)
    print(f"장 외 시간 기사 비율 {df.tday.notna().mean():.0%}")
    gap = op / cl.shift(1) - 1
    intra = cl / op - 1
    sd = pd.read_csv(f"{HERE}/dict_sector.csv")
    lm = ps.LM()
    rows = []
    for sec, (etf, sel) in SECTORS.items():
        p = df[sel(df) & df.tday.notna()].copy()
        p["tok"] = p["headline"].map(nyt_tokens)
        vocab = set(w for t in p.tok for w in t)
        dicts = {"LM": {w: s for w in vocab if (s := int(np.sign(lm.get_score(lm.tokenize(w))["Polarity"])))},
                 "업종사전": dict(zip(*sd[sd.sector.isin(["common", sec])][["word", "score"]].values.T))}
        g = p.groupby("tday")
        s = pd.DataFrame({"articles": g.size(), "words": g["tok"].agg(lambda x: sum(len(t) for t in x))})
        for n, d in dicts.items():
            s[n] = g["tok"].agg(lambda x: sum(d.get(w, 0) for t in x for w in t)) / s["words"].clip(lower=1) * 100
            sig = s[n].where(s[n] != 0)                                   # 사전 단어가 있는 날만
            base = sig.dropna().shift(1).rolling(250, min_periods=60).mean().reindex(s.index)  # 직전 250개 판정일 평균
            s[f"{n}_판정"] = np.where(base.isna() | sig.isna(), "", np.where(sig > base, "호재", "악재"))
        s["ex_gap"] = ((gap[etf] - gap["^GSPC"]) * 100).reindex(s.index)
        s["ex_intra"] = ((intra[etf] - intra["^GSPC"]) * 100).reindex(s.index)
        s.to_csv(f"{OUT}/daily_{sec}.csv")
        print(f"[{sec} → {etf}] 기사 {len(p):,}건, 뉴스 있는 거래일 {len(s):,}일 (하루 중앙값 {s.articles.median():.0f}건)")
        for n in dicts:
            for label, (a, b) in {**PERIODS, "전체": ("2014-01-01", "2026-09-30")}.items():
                d = s[(s.index >= a) & (s.index <= b) & (s[f"{n}_판정"] != "")].dropna(subset=["ex_gap", "ex_intra"])
                row = dict(업종=sec, 사전=n, 구간=label, 호재일=(d[f"{n}_판정"] == "호재").sum(), 악재일=(d[f"{n}_판정"] == "악재").sum())
                for col, nm in (("ex_gap", "반응_갭"), ("ex_intra", "예측_장중")):
                    gg, bb = d[d[f"{n}_판정"] == "호재"][col], d[d[f"{n}_판정"] == "악재"][col]
                    row[f"{nm}_차이bp"] = (gg.mean() - bb.mean()) * 100
                    row[f"{nm}_p"] = stats.ttest_ind(gg, bb, equal_var=False).pvalue
                    ic = spearmanr(d[n], d[col])                     # IC: 점수 순위 vs 수익률 순위 (판정일만)
                    row[f"{nm}_IC"], row[f"{nm}_IC_p"] = ic.statistic, ic.pvalue
                rows.append(row)
    res = pd.DataFrame(rows)
    res.to_csv(f"{OUT}/sector_daily_validation.csv", index=False)
    pd.set_option("display.width", 250)
    print("\n호재 판정일 - 악재 판정일 (bp, 1bp = 0.01%)")
    print(res.round(3).to_string(index=False))
