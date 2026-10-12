"""악재 판정 주 → 다음 주 S&P500 변동성이 커지나? (NYT, 기존 판정 그대로)
변동성 = 그 주 일별 수익률 제곱합의 제곱근(%). 회귀: 다음 주 변동성 ~ 악재(0/1) + 이번 주 변동성, HAC(5).
이번 주 변동성 통제가 없는 단순 비교도 함께 출력(통제의 중요성 확인용)."""
import os
import numpy as np
import pandas as pd
import statsmodels.api as sm
from judge_nyt import PERIODS

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = f"{HERE}/output/nyt"

if __name__ == "__main__":
    s = pd.read_csv(f"{OUT}/weekly_judgement_nyt.csv", parse_dates=["week"]).set_index("week")
    px = pd.read_csv(f"{HERE}/data/sp500_2014_2026.csv", parse_dates=["Date"]).set_index("Date")["Adj Close"]
    r = px.pct_change().dropna() * 100
    rv = np.sqrt((r ** 2).groupby(r.index.to_period("W-SUN").end_time.normalize()).sum())
    s["rv"] = rv.reindex(s.index)
    s["next_rv"] = rv.shift(-1).reindex(s.index)
    print(f"주간 변동성 평균 {s.rv.mean():.2f}%, 이번 주와 다음 주 변동성 상관 {s.rv.corr(s.next_rv):.2f}\n")

    rows = []
    for n in ("LM", "VADER", "Claude"):
        for label, (a, b) in PERIODS.items():
            d = s[(s.index >= a) & (s.index <= b) & (s[f"{n}_판정"] != "")].dropna(subset=["rv", "next_rv"])
            bad = (d[f"{n}_판정"] == "악재").astype(float)
            raw = d.loc[bad == 1, "next_rv"].mean() - d.loc[bad == 0, "next_rv"].mean()
            m = sm.OLS(d["next_rv"], sm.add_constant(pd.DataFrame({"악재": bad, "이번주_rv": d["rv"]}))).fit(
                cov_type="HAC", cov_kwds={"maxlags": 5})
            rows.append(dict(사전=n, 구간=label, 주=len(d), 단순차이=raw, 통제후_악재효과=m.params["악재"],
                             t=m.tvalues["악재"], p=m.pvalues["악재"]))
    res = pd.DataFrame(rows)
    res.to_csv(f"{OUT}/volatility_nyt.csv", index=False)
    print("악재 주의 다음 주 변동성 - 호재 주의 다음 주 변동성 (%p). 통제후 = 이번 주 변동성을 고정했을 때")
    print(res.round(3).to_string(index=False))
