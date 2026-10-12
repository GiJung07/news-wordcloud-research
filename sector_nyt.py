"""업종 뉴스 → 그 업종 ETF의 다음 주 초과 수익률(ETF - S&P500). 판별은 v1(직전 52주 평균 위/아래).
업종: 기술(Technology→XLK), 에너지(Climate + Business/Energy & Environment→XLE), 헬스케어(Health→XLV)
사전: LM, 업종 사전(dict_sector.csv의 common + 해당 업종, 결과 보기 전 작성). 기사 기준: NYT type=News.
보조: 다음 주 초과 수익률 변동성 ~ 악재 + 이번 주 초과 변동성 (HAC)."""
import glob
import os
import numpy as np
import pandas as pd
import pysentiment2 as ps
import statsmodels.api as sm
import yfinance as yf
from scipy import stats
from judge import weekly_scores
from judge_nyt import nyt_tokens, PERIODS

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = f"{HERE}/output/sector"
os.makedirs(OUT, exist_ok=True)
SECTORS = {
    "tech": ("XLK", lambda d: d.section == "Technology"),
    "energy": ("XLE", lambda d: (d.section == "Climate") | (d.subsection.fillna("").str.strip() == "Energy & Environment")),
    "health": ("XLV", lambda d: d.section == "Health"),
}


def load_all():
    df = pd.concat([pd.read_csv(f) for f in sorted(glob.glob(f"{HERE}/data/nyt/*.csv.gz"))], ignore_index=True)
    df = df[(df.doc.str.lower() == "article") & (df.type == "News") & df.headline.notna()].copy()
    df["date"] = pd.to_datetime(df.pub_date, utc=True, format="ISO8601").dt.tz_convert("America/New_York").dt.tz_localize(None)
    df["week"] = df["date"].dt.to_period("W-SUN").dt.end_time.dt.normalize()
    return df


def prices():
    path = f"{HERE}/data/sector_etf.csv"
    if not os.path.exists(path):
        px = yf.download(["XLK", "XLE", "XLV", "^GSPC"], start="2013-12-01", end="2026-10-10",
                         auto_adjust=False, progress=False)["Adj Close"]
        px.to_csv(path)
    px = pd.read_csv(path, parse_dates=["Date"]).set_index("Date")
    wk = px.index.to_period("W-SUN").end_time.normalize()
    last = px.groupby(wk).last()
    wret = last.pct_change() * 100                        # 주간 수익률 (그 주 마지막 종가 기준)
    dret = px.pct_change() * 100
    return wret, dret, wk


if __name__ == "__main__":
    df = load_all()
    wret, dret, wk = prices()
    sd = pd.read_csv(f"{HERE}/dict_sector.csv")
    lm = ps.LM()
    rows = []
    for sec, (etf, sel) in SECTORS.items():
        p = df[sel(df)].copy()
        p["tok"] = p["headline"].map(nyt_tokens)
        vocab = set(w for t in p.tok for w in t)
        dicts = {"LM": {w: s for w in vocab if (s := int(np.sign(lm.get_score(lm.tokenize(w))["Polarity"])))},
                 "업종사전": dict(zip(*sd[sd.sector.isin(["common", sec])][["word", "score"]].values.T))}
        s, _ = weekly_scores(p, dicts)
        ex = (wret[etf] - wret["^GSPC"])                                   # 이번 주 초과 수익률
        exd = dret[etf] - dret["^GSPC"]
        exvol = np.sqrt((exd ** 2).groupby(wk).sum())                      # 이번 주 초과 변동성
        s["next_ex"], s["exvol"], s["next_exvol"] = ex.shift(-1).reindex(s.index), exvol.reindex(s.index), exvol.shift(-1).reindex(s.index)
        s.to_csv(f"{OUT}/weekly_{sec}.csv")
        print(f"[{sec} → {etf}] 기사 {len(p):,}건, 주당 중앙값 {s.articles.median():.0f}건, "
              f"LM 단어 {len(dicts['LM'])}개 / 업종사전 단어 {len(dicts['업종사전'])}개 중 등장 {sum(w in vocab for w in dicts['업종사전'])}개, "
              f"두 사전 주간 점수 상관 {s['LM'].corr(s['업종사전']):.2f}")
        for n in dicts:
            for label, (a, b) in {**PERIODS, "전체": ("2014-01-01", "2026-09-30")}.items():
                d = s[(s.index >= a) & (s.index <= b) & (s[f"{n}_판정"] != "")].dropna(subset=["next_ex", "exvol", "next_exvol"])
                g, bd = d[d[f"{n}_판정"] == "호재"].next_ex, d[d[f"{n}_판정"] == "악재"].next_ex
                t, pv = stats.ttest_ind(g, bd, equal_var=False)
                m = sm.OLS(d["next_exvol"], sm.add_constant(pd.DataFrame({"악재": (d[f"{n}_판정"] == "악재").astype(float),
                           "vol": d["exvol"]}))).fit(cov_type="HAC", cov_kwds={"maxlags": 5})
                rows.append(dict(업종=sec, ETF=etf, 사전=n, 구간=label, 호재주=len(g), 악재주=len(bd),
                                 초과수익_호재=g.mean(), 초과수익_악재=bd.mean(), 차이=g.mean() - bd.mean(), p=pv,
                                 변동성_악재효과=m.params["악재"], 변동성_p=m.pvalues["악재"]))
    res = pd.DataFrame(rows)
    res.to_csv(f"{OUT}/sector_validation.csv", index=False)
    pd.set_option("display.width", 250)
    print("\n다음 주 초과 수익률(%, ETF - S&P500): 호재 판정 주 - 악재 판정 주")
    print(res.round(3).to_string(index=False))
