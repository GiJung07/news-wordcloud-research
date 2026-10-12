"""워드클라우드 기반 호재/악재 판별 프로세스.
① 정치 기사 제목 → ② 정제(tokens) → ③ 주간 워드클라우드(단어 빈도) → ④ 단어 사전 점수 → ⑤ 주간 판정 → ⑥ 색칠 워드클라우드
사전 3종: LM(금융 감성 사전), VADER(일반 감성 사전), Claude 초안(dict_claude.csv). 사전에 없는 단어는 0점.
주간 점수 = Σ(빈도 × 단어 점수) / 전체 단어 수 × 100  (단어 100개당 순점수)
판정 = 이번 주 점수가 '직전 52주 평균'보다 높으면 호재, 낮으면 악재 (과거 정보만 사용, 최소 12주 쌓인 뒤부터)
⑦ 검증: 판정 주의 '다음 주' S&P500 수익률(그 주 마지막 종가 → 다음 주 마지막 종가)."""
import os
from collections import Counter
import numpy as np
import pandas as pd
import pysentiment2 as ps
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from wordcloud import WordCloud
from wordcloud_politics import tokens, SERIES

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = f"{HERE}/output"
COLORS = {1: "#1a9850", -1: "#d73027", 0: "#b0b0b0"}  # 호재 초록, 악재 빨강, 중립 회색


def load_articles():
    df = pd.read_json(f"{HERE}/data/huffpost_news.json", lines=True)
    df["date"] = pd.to_datetime(df["date"])
    p = df[(df["category"] == "POLITICS") & df.date.dt.year.between(2014, 2022)]
    p = p[~p["headline"].str.contains(SERIES)].copy()
    p["tok"] = p["headline"].map(tokens)
    p["week"] = p["date"].dt.to_period("W-SUN").dt.end_time.dt.normalize()  # 월~일, 일요일 날짜로 표시
    return p


def dictionaries(vocab):
    lm, vader = ps.LM(), SentimentIntensityAnalyzer()
    d_lm = {w: int(np.sign(lm.get_score(lm.tokenize(w))["Polarity"])) for w in vocab}
    d_vader = {w: vader.lexicon[w] / 4 for w in vocab if w in vader.lexicon}  # -4~4 → -1~1
    claude = pd.read_csv(f"{HERE}/dict_claude.csv")
    d_claude = dict(zip(claude.word, claude.score))
    return {"LM": {w: s for w, s in d_lm.items() if s}, "VADER": d_vader, "Claude": d_claude}


def weekly_scores(p, dicts):
    wk = p.groupby("week")["tok"].agg(lambda s: Counter(w for t in s for w in t))
    rows = []
    for week, cnt in wk.items():
        total = sum(cnt.values())
        row = dict(week=week, articles=(p.week == week).sum(), words=total)
        for name, d in dicts.items():
            row[name] = sum(c * d.get(w, 0) for w, c in cnt.items()) / total * 100
        rows.append(row)
    s = pd.DataFrame(rows).set_index("week")
    for name in dicts:
        base = s[name].shift(1).rolling(52, min_periods=12).mean()  # 직전 52주 평균 (이번 주 미포함)
        s[f"{name}_판정"] = np.where(base.isna(), "", np.where(s[name] > base, "호재", "악재"))
    return s, wk


def next_week_return(weeks):
    px = pd.read_csv(f"{HERE}/data/sp500.csv", parse_dates=["Date"]).set_index("Date")["Adj Close"]
    last = px.groupby(px.index.to_period("W-SUN").end_time.normalize()).last()  # 주별 마지막 종가
    r = last.shift(-1) / last - 1                                               # 다음 주 수익률
    return r.reindex(weeks)


def colored_cloud(cnt, d, path):
    color = lambda word, **kw: COLORS[int(np.sign(d.get(word, 0)))]
    WordCloud(width=1200, height=700, background_color="white", max_words=120, random_state=0,
              color_func=color).generate_from_frequencies(cnt).to_file(path)


if __name__ == "__main__":
    p = load_articles()
    vocab = set(w for t in p.tok for w in t)
    dicts = dictionaries(vocab)
    for n, d in dicts.items():
        pos = sum(v > 0 for v in d.values()); neg = sum(v < 0 for v in d.values())
        print(f"사전 {n:6s}: 우리 단어 중 호재 {pos}개 / 악재 {neg}개")

    s, wk = weekly_scores(p, dicts)
    s["next_ret_pct"] = next_week_return(s.index) * 100
    s.to_csv(f"{OUT}/weekly_judgement.csv")
    print(f"\n주 {len(s)}개 (기사 수 중앙값 {s.articles.median():.0f}건/주), 사전 간 주간 점수 상관:")
    print(s[list(dicts)].corr().round(2).to_string())

    print("\n검증: 판정별 다음 주 S&P500 평균 수익률(%)")
    for n in dicts:
        v = s[s[f"{n}_판정"] != ""]
        for label, sub in [("앞 2014-16", v[v.index.year <= 2016]), ("뒤 2017-22", v[v.index.year > 2016]), ("전체", v)]:
            g = sub.groupby(f"{n}_판정")["next_ret_pct"].agg(["mean", "count"])
            diff = g.loc["호재", "mean"] - g.loc["악재", "mean"]
            agree = ((sub[f"{n}_판정"] == "호재") == (sub.next_ret_pct > 0)).mean()
            print(f"  {n:6s} {label}: 호재 주 {g.loc['호재','mean']:+.2f}% ({g.loc['호재','count']}주) / "
                  f"악재 주 {g.loc['악재','mean']:+.2f}% ({g.loc['악재','count']}주) / 차이 {diff:+.2f}%p / 방향 적중 {agree:.0%}")

    # 예시: Claude 사전 기준 가장 악재·가장 호재로 판정된 주의 색칠 워드클라우드 (사전 3종 각각)
    v = s[(s.articles >= 30) & (s["Claude_판정"] != "")]
    for tag, week in (("most_negative", v["Claude"].idxmin()), ("most_positive", v["Claude"].idxmax())):
        for n, d in dicts.items():
            colored_cloud(wk[week], d, f"{OUT}/judge_{tag}_{week.date()}_{n}.png")
        print(f"\n예시 {tag} 주 {week.date()}: 기사 {s.loc[week,'articles']}건, 점수 " +
              ", ".join(f"{n} {s.loc[week, n]:+.2f}({s.loc[week, n+'_판정']})" for n in dicts) +
              f", 다음 주 S&P500 {s.loc[week,'next_ret_pct']:+.2f}%")
        print("  상위 단어: " + ", ".join(f"{w}({c})" for w, c in wk[week].most_common(12)))
