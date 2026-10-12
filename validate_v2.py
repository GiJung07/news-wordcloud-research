"""v2 판별 프로세스 검증.
[참고 검증] NYT 2014~2026-09 (이미 v1로 한 번 본 데이터라 '참고용')
[전진 검증] 고정일(2026-10-09) 이후 주만 따로 집계. --update 로 실행하면 최신 NYT·S&P500을 받아 이어서 기록.
대상: 방향(다음 주 수익률: 호재 주 평균 - 악재 주 평균) / 변동성(다음 주 변동성 ~ 악재 + 호재 + 이번 주 변동성, 중립이 기준)."""
import hashlib
import os
import subprocess
import sys
import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats
from judge import dictionaries
from judge_nyt import load_nyt, PERIODS
from judge_v2 import weekly_scores_v2

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = f"{HERE}/output/v2"
os.makedirs(OUT, exist_ok=True)
FREEZE = pd.Timestamp("2026-10-11")  # 이 날짜(일요일)로 끝나는 주까지가 고정 전. 이후 주가 전진 검증 대상
FROZEN_FILES = ["judge_v2.py", "judge.py", "judge_nyt.py", "wordcloud_politics.py", "dict_claude.csv"]


def market():
    px = pd.read_csv(f"{HERE}/data/sp500_2014_2026.csv", parse_dates=["Date"]).set_index("Date")["Adj Close"]
    wk = px.index.to_period("W-SUN").end_time.normalize()
    last = px.groupby(wk).last()
    r = px.pct_change() * 100
    rv = np.sqrt((r ** 2).groupby(wk).sum())
    return (last.shift(-1) / last - 1) * 100, rv


def evaluate(s, label):
    d = s[s["최종판정"] != ""].dropna(subset=["next_ret", "rv", "next_rv"])
    out = dict(구간=label, 주=len(d), **{f"{k}주": (d["최종판정"] == k).sum() for k in ("호재", "중립", "악재")})
    g, b = d[d["최종판정"] == "호재"].next_ret, d[d["최종판정"] == "악재"].next_ret
    if len(g) > 2 and len(b) > 2:
        t, pv = stats.ttest_ind(g, b, equal_var=False)
        out.update(방향_호재평균=g.mean(), 방향_악재평균=b.mean(), 방향_차이=g.mean() - b.mean(), 방향_p=pv)
        X = sm.add_constant(pd.DataFrame({"악재": (d["최종판정"] == "악재").astype(float),
                                          "호재": (d["최종판정"] == "호재").astype(float), "rv": d["rv"]}))
        m = sm.OLS(d["next_rv"], X).fit(cov_type="HAC", cov_kwds={"maxlags": 5})
        out.update(변동성_악재효과=m.params["악재"], 변동성_악재_p=m.pvalues["악재"],
                   변동성_호재효과=m.params["호재"], 변동성_호재_p=m.pvalues["호재"])
    return out


def update_data():
    """전진 검증용: 최신 NYT 월·S&P500 갱신 (이미 받은 달은 건너뜀, 진행 중인 달은 다시 받음)"""
    today = pd.Timestamp.today()
    cur = f"{HERE}/data/nyt/{today.year}-{today.month:02d}.csv.gz"
    if os.path.exists(cur):
        os.remove(cur)
    subprocess.run([sys.executable, f"{HERE}/nyt_download_upto.py"], check=True)
    import yfinance as yf
    df = yf.download("^GSPC", start="2013-12-01", end=(today + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
                     auto_adjust=False, progress=False)
    df.columns = [c[0] for c in df.columns]
    df.to_csv(f"{HERE}/data/sp500_2014_2026.csv")


if __name__ == "__main__":
    if "--update" in sys.argv:
        update_data()
    digest = hashlib.sha256(b"".join(open(f"{HERE}/{f}", "rb").read() for f in FROZEN_FILES)).hexdigest()[:12]
    print(f"v2 고정 파일 지문 {digest} (고정 후 바뀌면 전진 검증 무효)")

    p = load_nyt()
    dicts = dictionaries(set(w for t in p.tok for w in t))
    s = weekly_scores_v2(p, dicts)
    s["next_ret"], s["next_rv"] = market()[0].reindex(s.index), market()[1].shift(-1).reindex(s.index)
    s["rv"] = market()[1].reindex(s.index)
    s.to_csv(f"{OUT}/weekly_judgement_v2.csv")

    rows = [evaluate(s[(s.index >= a) & (s.index <= b)], f"참고 {k}") for k, (a, b) in PERIODS.items()]
    fwd = s[s.index > FREEZE]
    rows.append(evaluate(fwd, f"전진 (고정 후 {fwd['next_ret'].notna().sum()}주)") if len(fwd) else dict(구간="전진 (아직 0주)"))
    res = pd.DataFrame(rows)
    res.to_csv(f"{OUT}/validation_v2.csv", index=False)
    pd.set_option("display.width", 250)
    print(res.round(3).to_string(index=False))
    print("\n사전별 판정 일치: 세 사전이 모두 같은 판정인 주 비율",
          f"{(s[[f'{n}_판정' for n in dicts]].nunique(axis=1) == 1).mean():.0%}")
