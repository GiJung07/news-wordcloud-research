"""개별 기업: 장외 시간(전일 16:00~당일 09:30) 헤드라인에 회사 이름이 나온 (회사, 거래일) 사건.
반응 z = 당일 초과 수익률(회사 - S&P500, 전일 종가→당일 종가) / 직전 60일 초과 수익률 표준편차 (과거만 사용)
① 방향: 단어 있는 사건의 평균 z - 없는 사건의 평균 z   ② 크기: 같은 비교를 |z|로
앞/뒤 절반(사건 날짜 중앙값 기준)으로 나눠 재현 확인 + 반응을 무작위로 섞은 가짜 데이터 200회와 비교.
사전 IC: LM, 공통 사전 점수 vs z (스피어만)."""
import os
import re
import numpy as np
import pandas as pd
import pysentiment2 as ps
import yfinance as yf
from scipy import stats
from scipy.stats import spearmanr
from judge_nyt import nyt_tokens
from sector_nyt import load_all
from sector_daily import assign_trading_day, ohlc

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = f"{HERE}/output/firm"
os.makedirs(OUT, exist_ok=True)
MIN_EVENTS_FIRM, MIN_WORD = 20, 15


def firm_prices(tickers):
    path = f"{HERE}/data/firm_close.csv"
    if not os.path.exists(path):
        px = yf.download(tickers + ["^GSPC"], start="2013-09-01", end="2026-10-10", auto_adjust=False, progress=False)["Adj Close"]
        px.to_csv(path)
    return pd.read_csv(path, parse_dates=["Date"]).set_index("Date")


def build_events():
    df = load_all()
    _, cl = ohlc()
    df["tday"] = assign_trading_day(df["date"], cl.index.values)
    df = df[df.tday.notna()]
    firms = pd.read_csv(f"{HERE}/firms.csv")
    rows = []
    for _, f in firms.iterrows():
        m = df[df.headline.str.contains(f.pattern, regex=True)]
        if len(m) < MIN_EVENTS_FIRM:
            continue
        name_words = set(w for h in m.headline for w in nyt_tokens(re.sub(r"[^A-Za-z&.’' -]", " ", "".join(re.findall(f.pattern, h)))))
        for tday, g in m.groupby("tday"):
            toks = set(w for h in g.headline for w in nyt_tokens(h)) - name_words
            rows.append(dict(ticker=f.ticker, sector=f.sector, tday=tday, n=len(g), headlines=" | ".join(g.headline), tok=toks))
    ev = pd.DataFrame(rows)
    px = firm_prices(sorted(ev.ticker.unique()))
    r = px.pct_change()
    ex = r.sub(r["^GSPC"], axis=0)
    vol = ex.rolling(60, min_periods=40).std().shift(1)                 # 과거 60일만
    z = (ex / vol)
    ev["z"] = [z.at[t, k] if t in z.index else np.nan for t, k in zip(ev.tday, ev.ticker)]
    ev["ex_pct"] = [ex.at[t, k] * 100 if t in ex.index else np.nan for t, k in zip(ev.tday, ev.ticker)]
    return ev.dropna(subset=["z"])


def word_stats(ev, words, col):
    """단어별: 있음 평균 - 없음 평균, Welch p (행렬로 한 번에)"""
    M = np.array([[w in t for w in words] for t in ev.tok])
    y = ev[col].values
    n1 = M.sum(0); n0 = len(y) - n1
    s1 = M.T @ y; q1 = M.T @ y ** 2
    m1, m0 = s1 / n1, (y.sum() - s1) / n0
    v1 = (q1 - n1 * m1 ** 2) / (n1 - 1); v0 = ((y ** 2).sum() - q1 - n0 * m0 ** 2) / (n0 - 1)
    se = np.sqrt(v1 / n1 + v0 / n0); t = (m1 - m0) / se
    dfree = (v1 / n1 + v0 / n0) ** 2 / ((v1 / n1) ** 2 / (n1 - 1) + (v0 / n0) ** 2 / (n0 - 1))
    return pd.DataFrame({"n": n1, "diff": m1 - m0, "p": 2 * stats.t.sf(np.abs(t), dfree)}, index=words), M


def split_check(tr, te, words, col):
    a, _ = word_stats(tr, words, col)
    b, _ = word_stats(te, words, col)
    res = a.join(b, lsuffix="_앞", rsuffix="_뒤")
    sig = res[res.p_앞 < 0.05]
    same = np.sign(sig.diff_앞) == np.sign(sig.diff_뒤)
    return res, dict(유의_앞=len(sig), 같은방향=int(same.sum()), 둘다유의=int((same & (sig.p_뒤 < 0.05)).sum()))


if __name__ == "__main__":
    ev = build_events()
    ev["absz"] = ev.z.abs()
    ev.drop(columns="tok").to_csv(f"{OUT}/events.csv", index=False)
    cut = ev.tday.median()
    tr, te = ev[ev.tday <= cut], ev[ev.tday > cut]
    print(f"사건 {len(ev):,}개 (회사 {ev.ticker.nunique()}곳), 평균 |z| {ev.absz.mean():.2f} (뉴스 없는 날 기준 기대값 약 0.8)")
    print(f"앞 절반 ~{cut.date()} {len(tr):,}개 / 뒤 절반 {len(te):,}개")

    # 사전 IC
    lm = ps.LM()
    common = pd.read_csv(f"{HERE}/dict_sector.csv").query("sector == 'common'")
    cd = dict(zip(common.word, common.score))
    ev["LM"] = [sum(int(np.sign(lm.get_score(lm.tokenize(w))["Polarity"])) for w in t) for t in ev.tok]
    ev["공통사전"] = [sum(cd.get(w, 0) for w in t) for t in ev.tok]
    print("\n사전 IC (점수 vs 방향 z, 점수 0인 사건 제외):")
    for n in ("LM", "공통사전"):
        for lab, d in (("앞", ev[ev.tday <= cut]), ("뒤", ev[ev.tday > cut]), ("전체", ev)):
            d = d[d[n] != 0]
            ic = spearmanr(d[n], d.z)
            print(f"  {n:5s} {lab:2s} 사건 {len(d):,}개  IC {ic.statistic:+.3f} (p={ic.pvalue:.3f})")

    vocab = pd.Series([w for t in tr.tok for w in t]).value_counts()
    vte = pd.Series([w for t in te.tok for w in t]).value_counts()
    words = sorted(set(vocab[vocab >= MIN_WORD].index) & set(vte[vte >= MIN_WORD].index))
    print(f"\n시험 단어 {len(words)}개 (앞뒤 각 {MIN_WORD}건 이상)")
    rng = np.random.default_rng(0)
    for col, label in (("z", "① 방향"), ("absz", "② 크기")):
        res, real = split_check(tr, te, words, col)
        res.sort_values("p_앞").to_csv(f"{OUT}/words_{col}.csv")
        fake = []
        for _ in range(200):
            trf, tef = tr.copy(), te.copy()
            trf[col], tef[col] = rng.permutation(trf[col].values), rng.permutation(tef[col].values)
            fake.append(split_check(trf, tef, words, col)[1])
        fake = pd.DataFrame(fake)
        print(f"\n{label}: 실제 {real} | 가짜 평균 " + ", ".join(f"{k} {fake[k].mean():.1f}" for k in real) +
              " | 가짜가 실제 이상인 비율 " + ", ".join(f"{k} {(fake[k] >= real[k]).mean():.0%}" for k in real))
        both = res[(res.p_앞 < 0.05) & (res.p_뒤 < 0.05) & (np.sign(res.diff_앞) == np.sign(res.diff_뒤))]
        print("  앞뒤 모두 유의 + 같은 방향인 단어:")
        print(both.round(3).to_string() if len(both) else "  없음")
        print("  앞 기간 상위 10개:")
        print(res.sort_values("p_앞").head(10).round(3).to_string())
