"""단어 → 다음 거래일 S&P500 수익률. 앞 기간(2014-16)에서 호재/악재 후보를 고르고 뒤 기간(2017-22)에서 방향 확인.
분석 단위는 날짜. 단어 효과 = 단어가 나온 날 평균 수익률 - 안 나온 날 평균 수익률 (Welch t검정).
단어 범위 = 양쪽 기간 각각 N건 이상 기사에 나온 단어, N = 20/50/100."""
import os
import numpy as np
import pandas as pd
from scipy import stats
from wordcloud_politics import tokens, SERIES

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = f"{HERE}/output"
SPLIT = 2016  # 앞 기간 = ~2016, 뒤 기간 = 2017~


def load():
    df = pd.read_json(f"{HERE}/data/huffpost_news.json", lines=True)
    df["date"] = pd.to_datetime(df["date"])
    p = df[(df["category"] == "POLITICS") & df.date.dt.year.between(2014, 2022)]
    p = p[~p["headline"].str.contains(SERIES)].copy()
    p["tok"] = p["headline"].map(lambda h: set(tokens(h)))

    px = pd.read_csv(f"{HERE}/data/sp500.csv", parse_dates=["Date"]).set_index("Date")["Adj Close"]
    ret = px.pct_change().dropna()
    # 기사 날짜보다 '엄격히 뒤'인 첫 거래일의 수익률 (그날 종가 이후에 나온 기사여도 미래를 보지 않음)
    days = ret.index.values
    pos = np.searchsorted(days, p["date"].values, side="right")
    p = p[pos < len(days)]
    p["trade_day"] = days[pos[pos < len(days)]]
    return p, ret


def day_table(p, ret):
    """거래일별: 그날 대응되는 기사들에 나온 단어 집합 + 수익률"""
    g = p.groupby("trade_day")["tok"].agg(lambda s: set().union(*s))
    d = pd.DataFrame({"words": g, "ret": ret.reindex(g.index)})
    d["n_articles"] = p.groupby("trade_day").size()
    return d


def word_effects(d, words):
    rows = []
    r = d["ret"].values
    for w in words:
        has = d["words"].map(lambda s: w in s).values
        a, b = r[has], r[~has]
        t, pv = stats.ttest_ind(a, b, equal_var=False) if len(a) > 2 else (np.nan, np.nan)
        rows.append(dict(word=w, days=has.sum(), diff_bp=(a.mean() - b.mean()) * 1e4, p=pv))
    return pd.DataFrame(rows).set_index("word")


if __name__ == "__main__":
    p, ret = load()
    tr, te = p[p.date.dt.year <= SPLIT], p[p.date.dt.year > SPLIT]
    dtr, dte = day_table(tr, ret), day_table(te, ret)
    print(f"앞 기간: 기사 {len(tr):,}건, 거래일 {len(dtr):,}일 | 뒤 기간: 기사 {len(te):,}건, 거래일 {len(dte):,}일")
    print(f"하루 평균 수익률: 앞 {dtr.ret.mean()*1e4:+.1f}bp, 뒤 {dte.ret.mean()*1e4:+.1f}bp (1bp = 0.01%)")
    ctr = tr.explode("tok")["tok"].value_counts()
    cte = te.explode("tok")["tok"].value_counts()

    summary = []
    for n in (20, 50, 100):
        words = sorted(set(ctr[ctr >= n].index) & set(cte[cte >= n].index))
        etr, ete = word_effects(dtr, words), word_effects(dte, words)
        res = etr.join(ete, lsuffix="_train", rsuffix="_test")
        res["signal"] = np.where(res.p_train < 0.05, np.where(res.diff_bp_train > 0, "호재", "악재"), "")
        res["same_dir"] = np.sign(res.diff_bp_train) == np.sign(res.diff_bp_test)
        res.sort_values("p_train").to_csv(f"{OUT}/word_returns_min{n}.csv")
        sig = res[res.signal != ""]
        k = len(sig); agree = sig.same_dir.sum()
        binom = stats.binomtest(int(agree), k, 0.5, alternative="greater").pvalue if k else np.nan
        test_sig = (sig.same_dir & (sig.p_test < 0.05)).sum()
        summary.append(dict(min_count=n, words=len(res), sig_train=k, expected_by_chance=round(len(res) * 0.05, 1),
                            same_dir_test=agree, same_dir_rate=agree / k if k else np.nan, binom_p=binom,
                            also_sig_test=test_sig, all_words_same_dir_rate=res.same_dir.mean()))
        print(f"\n=== 최소 {n}건 버전: 단어 {len(res)}개 ===")
        print(f"앞 기간 유의(p<0.05): {k}개 (우연만으로도 약 {len(res)*0.05:.0f}개 기대)")
        print(f"그중 뒤 기간 같은 방향: {agree}/{k} = {agree/k:.0%} (동전 던지기 50%, 이항검정 p={binom:.3f}), 뒤 기간에서도 유의: {test_sig}개")
        print(f"전체 단어의 방향 일치율: {res.same_dir.mean():.0%}")
        cols = ["signal", "days_train", "diff_bp_train", "p_train", "days_test", "diff_bp_test", "p_test", "same_dir"]
        print(sig.sort_values("diff_bp_train")[cols].round(3).to_string())
    pd.DataFrame(summary).to_csv(f"{OUT}/word_returns_summary.csv", index=False)
