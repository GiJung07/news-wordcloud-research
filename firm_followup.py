"""기업 사건 후속 점검 (firm_words.py 사건 그대로).
1. 거래 가능 시험: 반응을 개장 갭(전일 종가→당일 시가)과 장중(시가→종가)으로 분리. 회사-S&P, 직전 60일 초과 변동성으로 나눔.
2. 보도 효과: 주가 움직임 묘사 단어(MOVE)가 헤드라인에 하나라도 있는 사건 제외 후 재측정.
지표: LM 점수 IC(방향), 실적 단어(EARN, 앞 결과에서 나온 확인용 목록) 유무별 평균 |z|(크기)."""
import os
import re
import numpy as np
import pandas as pd
import pysentiment2 as ps
import yfinance as yf
from scipy import stats
from scipy.stats import spearmanr
from firm_words import build_events

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = f"{HERE}/output/firm"
MOVE = re.compile(r"\b(shares?|stocks?|investors?|markets?|rises?|rose|risen|falls?|fell|fallen|soars?|soared|surges?|surged|"
                  r"jumps?|jumped|climbs?|climbed|gains?|gained|rally|rallies|rallied|plunges?|plunged|drops?|dropped|"
                  r"slides?|slid|sinks?|sank|tumbles?|tumbled|slumps?|slumped)\b", re.I)
EARN = {"earnings", "profit", "profits", "revenue", "quarter", "sales"}


def open_close(tickers):
    path = f"{HERE}/data/firm_open_close.csv"
    if not os.path.exists(path):
        px = yf.download(tickers + ["^GSPC"], start="2013-09-01", end="2026-10-10", auto_adjust=False, progress=False)
        px[["Open", "Close"]].to_csv(path)
    px = pd.read_csv(path, header=[0, 1], index_col=0, parse_dates=True)
    return px["Open"], px["Close"]


if __name__ == "__main__":
    ev = build_events()
    op, cl = open_close(sorted(ev.ticker.unique()))
    gap, intra = op / cl.shift(1) - 1, cl / op - 1                       # 같은 날 시가/종가 비율이라 수정주가 불필요
    exg, exi = gap.sub(gap["^GSPC"], axis=0), intra.sub(intra["^GSPC"], axis=0)
    vol = (cl.pct_change().sub(cl.pct_change()["^GSPC"], axis=0)).rolling(60, min_periods=40).std().shift(1)
    pick = lambda m: [m.at[t, k] / vol.at[t, k] if t in m.index else np.nan for t, k in zip(ev.tday, ev.ticker)]
    ev["z_gap"], ev["z_intra"] = pick(exg), pick(exi)
    lm = ps.LM()
    ev["LM"] = [sum(int(np.sign(lm.get_score(lm.tokenize(w))["Polarity"])) for w in t) for t in ev.tok]
    ev["move"] = ev.headlines.str.contains(MOVE)
    ev["earn"] = ev.tok.map(lambda t: bool(t & EARN))
    ev = ev.dropna(subset=["z", "z_gap", "z_intra"])
    cut = ev.tday.median()
    print(f"사건 {len(ev):,}개, 주가 묘사 단어가 있는 사건 {ev.move.mean():.0%}, 실적 단어 사건 {ev.earn.mean():.1%}")

    rows = []
    for subset, d0 in (("전체 사건", ev), ("주가 묘사 제외", ev[~ev.move])):
        for half, d1 in (("앞", d0[d0.tday <= cut]), ("뒤", d0[d0.tday > cut]), ("전체", d0)):
            d = d1[d1.LM != 0]
            row = dict(사건집합=subset, 기간=half, LM사건=len(d))
            for col, nm in (("z", "하루"), ("z_gap", "갭"), ("z_intra", "장중")):
                ic = spearmanr(d.LM, d[col])
                row[f"IC_{nm}"], row[f"p_{nm}"] = ic.statistic, ic.pvalue
            for col, nm in (("z_gap", "갭"), ("z_intra", "장중")):
                a, b = d1[d1.earn][col].abs(), d1[~d1.earn][col].abs()
                row[f"실적크기_{nm}"] = a.mean() - b.mean()
                row[f"실적크기_{nm}_p"] = stats.ttest_ind(a, b, equal_var=False).pvalue if len(a) > 2 else np.nan
            rows.append(row)
    res = pd.DataFrame(rows)
    res.to_csv(f"{OUT}/firm_followup.csv", index=False)
    pd.set_option("display.width", 250)
    print("\nLM IC (점수 vs 방향 z)  /  실적크기 = 실적 단어 있는 사건의 평균 |z| - 없는 사건 (평소 변동폭 배수)")
    print(res.round(3).to_string(index=False))
