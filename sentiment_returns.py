"""감성 사전으로 정치 헤드라인 톤(긍정/부정) 판별 → 그날 평균 톤이 다음 거래일 S&P500 수익률과 관련 있나.
사전 2종: Loughran-McDonald(금융 문서용), VADER(짧은 글용). 조정할 값 없음.
검정: 수익률 ~ 톤 + log(기사 수) 회귀(HAC 표준오차), 톤 5분위별 평균 수익률. 앞(2014-16)/뒤(2017-22)/전체."""
import os
import numpy as np
import pandas as pd
import pysentiment2 as ps
import statsmodels.api as sm
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from word_returns import load, SPLIT

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = f"{HERE}/output"


def label(s):
    return np.where(s > 0.05, "긍정", np.where(s < -0.05, "부정", "중립"))


def test(d, col):
    X = sm.add_constant(pd.DataFrame({"tone": d[col], "log_n": np.log(d["n"])}))
    m = sm.OLS(d["ret"] * 1e4, X).fit(cov_type="HAC", cov_kwds={"maxlags": 5})
    q = pd.qcut(d[col].rank(method="first"), 5, labels=False)
    qm = d.groupby(q)["ret"].mean() * 1e4
    return dict(days=len(d), corr=d[col].corr(d["ret"]), slope_bp=m.params["tone"], t=m.tvalues["tone"],
                p=m.pvalues["tone"], q1_bp=qm.iloc[0], q5_bp=qm.iloc[-1], q5_minus_q1=qm.iloc[-1] - qm.iloc[0])


if __name__ == "__main__":
    p, ret = load()
    lm, vader = ps.LM(), SentimentIntensityAnalyzer()
    p["lm"] = p["headline"].map(lambda h: lm.get_score(lm.tokenize(h))["Polarity"])
    p["vader"] = p["headline"].map(lambda h: vader.polarity_scores(h)["compound"])

    print(f"헤드라인 {len(p):,}건")
    for c in ("lm", "vader"):
        lab = pd.Series(label(p[c])).value_counts(normalize=True)
        print(f"  {c:5s} 긍정 {lab.get('긍정', 0):.0%} / 부정 {lab.get('부정', 0):.0%} / 중립 {lab.get('중립', 0):.0%}")
    print(f"  두 사전 점수 상관 {p.lm.corr(p.vader):.2f}, 판정 일치율 {(label(p.lm) == label(p.vader)).mean():.0%}")
    for c in ("lm", "vader"):
        s = p.sort_values(c)
        print(f"\n[{c}] 가장 부정적 5개: " + " | ".join(s.headline.head(5)))
        print(f"[{c}] 가장 긍정적 5개: " + " | ".join(s.headline.tail(5)))
    p[["date", "trade_day", "headline", "lm", "vader"]].to_csv(f"{OUT}/headline_sentiment.csv", index=False)

    # 거래일별 평균 톤
    d = p.groupby("trade_day").agg(lm=("lm", "mean"), vader=("vader", "mean"), n=("headline", "size"))
    d["ret"] = ret.reindex(d.index)
    d["period"] = np.where(d.index.year <= SPLIT, "앞 2014-16", "뒤 2017-22")
    rows = []
    for c in ("lm", "vader"):
        for name, sub in [("앞 2014-16", d[d.period == "앞 2014-16"]), ("뒤 2017-22", d[d.period == "뒤 2017-22"]), ("전체", d)]:
            rows.append(dict(lexicon=c, period=name, **test(sub, c)))
        for y, sub in d.groupby(d.index.year):
            if len(sub) > 30:
                rows.append(dict(lexicon=c, period=str(y), **test(sub, c)))
    res = pd.DataFrame(rows)
    res.to_csv(f"{OUT}/sentiment_returns.csv", index=False)
    print("\n톤 → 다음 거래일 수익률 (slope: 톤 1단위당 bp, q5-q1: 가장 긍정적인 날 20% - 가장 부정적인 날 20%, bp)")
    print(res.round(3).to_string(index=False))
