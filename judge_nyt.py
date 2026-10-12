"""HuffPost로 만든 판별 프로세스(judge.py)를 '그대로' NYT 정치 기사에 적용해 검증.
바꾼 것은 데이터 정리 두 가지뿐: ① NYT 약어 표기(G.O.P. → gop) ② 정치 기사 기준(U.S./Politics, type=News).
사전 3종·주 단위·'직전 52주 평균' 판정·다음 주 수익률 정의는 judge.py와 동일.
검증 구간: A 2014~2016, B 2017~2022-09 (HuffPost와 같은 기간), C 2022-10~2026-09 (처음 보는 4년)."""
import glob
import os
import re
import numpy as np
import pandas as pd
from scipy import stats
from judge import dictionaries, weekly_scores, colored_cloud
from wordcloud_politics import tokens

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = f"{HERE}/output/nyt"
os.makedirs(OUT, exist_ok=True)
PERIODS = {"A 2014-16": ("2014-01-01", "2016-12-31"), "B 2017-22.09": ("2017-01-01", "2022-09-30"),
           "C 2022.10-26.09 (신규)": ("2022-10-01", "2026-09-30")}


def nyt_tokens(h):
    h = h.replace("U.S.", " usa ")                                                   # 기존 규칙 먼저
    h = re.sub(r"\b(?:[A-Za-z]\.){2,}", lambda m: m.group(0).replace(".", ""), h)  # G.O.P. → GOP
    return tokens(h)


def load_nyt():
    df = pd.concat([pd.read_csv(f) for f in sorted(glob.glob(f"{HERE}/data/nyt/*.csv.gz"))], ignore_index=True)
    df = df[(df.doc.str.lower() == "article") & (df.section == "U.S.") & (df.subsection == "Politics")
            & (df.type == "News") & df.headline.notna()].copy()
    df["date"] = pd.to_datetime(df.pub_date, utc=True, format="ISO8601").dt.tz_convert("America/New_York").dt.tz_localize(None)
    df["tok"] = df["headline"].map(nyt_tokens)
    df["week"] = df["date"].dt.to_period("W-SUN").dt.end_time.dt.normalize()
    return df


def next_week_return(weeks):
    px = pd.read_csv(f"{HERE}/data/sp500_2014_2026.csv", parse_dates=["Date"]).set_index("Date")["Adj Close"]
    last = px.groupby(px.index.to_period("W-SUN").end_time.normalize()).last()
    return (last.shift(-1) / last - 1).reindex(weeks)


if __name__ == "__main__":
    p = load_nyt()
    print(f"NYT 정치 기사 {len(p):,}건, {p.date.min().date()} ~ {p.date.max().date()}")
    dicts = dictionaries(set(w for t in p.tok for w in t))
    s, wk = weekly_scores(p, dicts)
    s["next_ret_pct"] = next_week_return(s.index) * 100
    s.to_csv(f"{OUT}/weekly_judgement_nyt.csv")
    print(f"주 {len(s)}개 (기사 수 중앙값 {s.articles.median():.0f}건/주). 사전 간 점수 상관:")
    print(s[list(dicts)].corr().round(2).to_string())

    print("\n검증: 판정별 다음 주 S&P500 평균 수익률(%)")
    rows = []
    for n in dicts:
        for label, (a, b) in PERIODS.items():
            sub = s[(s.index >= a) & (s.index <= b) & (s[f"{n}_판정"] != "")].dropna(subset=["next_ret_pct"])
            g, bd = sub[sub[f"{n}_판정"] == "호재"].next_ret_pct, sub[sub[f"{n}_판정"] == "악재"].next_ret_pct
            t, pv = stats.ttest_ind(g, bd, equal_var=False)
            rows.append(dict(사전=n, 구간=label, 호재주=len(g), 호재평균=g.mean(), 악재주=len(bd), 악재평균=bd.mean(),
                             차이=g.mean() - bd.mean(), t=t, p=pv))
    res = pd.DataFrame(rows)
    res.to_csv(f"{OUT}/validation_nyt.csv", index=False)
    print(res.round(3).to_string(index=False))

    # 새 구간(C)에서 가장 악재/호재로 판정된 주 예시 (Claude 사전 기준)
    c0, c1 = PERIODS["C 2022.10-26.09 (신규)"]
    v = s[(s.index >= c0) & (s.index <= c1) & (s.articles >= 30)]
    for tag, week in (("most_negative", v["Claude"].idxmin()), ("most_positive", v["Claude"].idxmax())):
        for n, d in dicts.items():
            colored_cloud(wk[week], d, f"{OUT}/judge_{tag}_{week.date()}_{n}.png")
        print(f"\n예시 {tag} 주 {week.date()}: 기사 {s.loc[week, 'articles']}건, " +
              ", ".join(f"{n} {s.loc[week, n]:+.2f}({s.loc[week, n + '_판정']})" for n in dicts) +
              f", 다음 주 S&P500 {s.loc[week, 'next_ret_pct']:+.2f}%")
        print("  상위 단어: " + ", ".join(f"{w}({c})" for w, c in wk[week].most_common(12)))
