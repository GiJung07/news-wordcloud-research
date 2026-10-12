"""REPORT.md용 그래프 (deliverables/charts/). 저장된 결과 파일만 읽어서 그림 → 분석 재실행 없음.
1 데이터 기사 수 추이  2 정치 판정 검증(차이 + 95% 신뢰구간)  3 업종 하루 단위 IC  4 기업 IC: 갭 vs 장중  5 기업 크기 단어."""
import glob
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import stats

HERE = os.path.dirname(os.path.abspath(__file__))
DST = f"{HERE}/deliverables/charts"
os.makedirs(DST, exist_ok=True)
C1, C2, C3 = "#2a78d6", "#eb6834", "#1baf7a"           # 검증된 범주색 1~3번 (blue, orange, aqua)
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
plt.rcParams.update({"font.family": "Malgun Gothic", "axes.unicode_minus": False, "figure.facecolor": SURF,
                     "axes.facecolor": SURF, "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2,
                     "ytick.color": INK2, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
                     "axes.spines.top": False, "axes.spines.right": False, "font.size": 11})


def title(ax, t, sub=None):
    ax.set_title(t, loc="left", fontsize=14, color=INK, fontweight="bold", pad=24 if sub else 10)
    if sub:
        ax.text(0, 1.02, sub, transform=ax.transAxes, fontsize=10, color=INK2)


def diff_ci(good, bad):
    d = good.mean() - bad.mean()
    se = np.sqrt(good.var(ddof=1) / len(good) + bad.var(ddof=1) / len(bad))
    return d, 1.96 * se, stats.ttest_ind(good, bad, equal_var=False).pvalue


# 1. 기사 수 추이
def chart_coverage():
    hp = pd.read_json(f"{HERE}/data/huffpost_news.json", lines=True)
    hp["y"] = pd.to_datetime(hp.date).dt.year
    hp = hp[(hp.category == "POLITICS") & hp.y.between(2014, 2022)].groupby("y").size()
    ny = pd.concat([pd.read_csv(f) for f in sorted(glob.glob(f"{HERE}/data/nyt/*.csv.gz"))])
    ny = ny[(ny.doc.str.lower() == "article") & (ny.section == "U.S.") & (ny.subsection == "Politics") & (ny.type == "News")].copy()
    ny["y"] = pd.to_datetime(ny.pub_date, utc=True, format="ISO8601").dt.tz_convert("America/New_York").dt.year
    ny = ny[ny.y.between(2014, 2025)].groupby("y").size()
    fig, ax = plt.subplots(figsize=(10, 4.8))
    ax.plot(ny.index, ny.values, color=C1, lw=2, marker="o", ms=8, mec=SURF, mew=2, label="NYT (최종 분석)")
    ax.plot(hp.index, hp.values, color=C2, lw=2, marker="o", ms=8, mec=SURF, mew=2, label="HuffPost")
    ax.annotate(f"{hp[2019]:,}건", (2019, hp[2019]), textcoords="offset points", xytext=(10, 6), ha="left", color=INK2)
    ax.annotate(f"{ny[2019]:,}건", (2019, ny[2019]), textcoords="offset points", xytext=(0, 10), ha="center", color=INK2)
    ax.set_ylim(0, None); ax.set_xticks(range(2014, 2026)); ax.set_ylabel("정치 기사 수 (연간)")
    ax.legend(frameon=False, loc="upper right")
    title(ax, "정치 기사 수: HuffPost는 2018년 이후 급감, NYT는 12년 내내 고름", "2026년은 진행 중이라 제외")
    fig.tight_layout(); fig.savefig(f"{DST}/01_coverage.png", dpi=130); plt.close(fig)


# 2. 정치 v1 판정 검증 (포레스트 플롯)
def chart_politics():
    hp = pd.read_csv(f"{HERE}/output/weekly_judgement.csv", parse_dates=["week"]).set_index("week")
    ny = pd.read_csv(f"{HERE}/output/nyt/weekly_judgement_nyt.csv", parse_dates=["week"]).set_index("week")
    sets = [("HuffPost 2014-22", hp, None, None), ("NYT A 2014-16", ny, "2014-01-01", "2016-12-31"),
            ("NYT B 2017-22.09", ny, "2017-01-01", "2022-09-30"), ("NYT C 2022.10-26.09 (신규)", ny, "2022-10-01", "2026-09-30")]
    rows = []
    for name, s, a, b in sets:
        if a:
            s = s[(s.index >= a) & (s.index <= b)]
        for dct in ("LM", "VADER", "Claude"):
            d = s[s[f"{dct}_판정"].fillna("") != ""].dropna(subset=["next_ret_pct"])
            rows.append((name, dct, *diff_ci(d[d[f"{dct}_판정"] == "호재"].next_ret_pct, d[d[f"{dct}_판정"] == "악재"].next_ret_pct)))
    r = pd.DataFrame(rows, columns=["set", "dict", "d", "ci", "p"])
    fig, ax = plt.subplots(figsize=(10, 6.2))
    colors = {"LM": C1, "VADER": C2, "Claude": C3}
    y = 0; yt, yl = [], []
    for name in r.set.unique():
        for off, (_, row) in zip((-0.25, 0, 0.25), r[r.set == name].iterrows()):
            ax.errorbar(row.d, y + off, xerr=row.ci, fmt="o", ms=8, color=colors[row.dict], ecolor=colors[row.dict],
                        elinewidth=2, capsize=0, mec=SURF, mew=1.5, label=row.dict if y == 0 else None)
            ax.text(row.d + row.ci + 0.05, y + off, f"{row.d:+.2f} (p={row.p:.2f})", va="center", fontsize=9, color=INK2)
        yt.append(y); yl.append(name); y += 1
    ax.axvline(0, color=INK2, lw=1)
    ax.set_yticks(yt, yl); ax.invert_yaxis(); ax.grid(axis="y", visible=False)
    ax.set_xlabel("호재 판정 주 - 악재 판정 주의 다음 주 S&P500 수익률 차이 (%p, 막대 = 95% 신뢰구간)")
    ax.legend(frameon=False, loc="lower left")
    title(ax, "정치 뉴스 판정 v1: 모든 신뢰구간이 0을 지남", "HuffPost에서 보인 + 방향이 NYT와 새 4년에서 재현되지 않음")
    fig.tight_layout(); fig.savefig(f"{DST}/02_politics_v1.png", dpi=130); plt.close(fig)


# 3. 업종 하루 단위 IC
def chart_sector():
    r = pd.read_csv(f"{HERE}/output/sector_daily/sector_daily_validation.csv")
    r = r[r["구간"] == "전체"]
    names = {"tech": "기술", "energy": "에너지", "health": "헬스케어"}
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.6), sharey=True)
    for ax, (col, lab) in zip(axes, (("반응_갭_IC", "개장 갭 (반응)"), ("예측_장중_IC", "장중 (거래 가능)"))):
        x = np.arange(3)
        for i, (dct, c) in enumerate((("LM", C1), ("업종사전", C2))):
            v = r[r["사전"] == dct].set_index("업종").loc[list(names)][col].values
            p = r[r["사전"] == dct].set_index("업종").loc[list(names)][col + "_p"].values
            bars = ax.bar(x + (i - 0.5) * 0.36, v, 0.34, color=c, label=dct)
            for xi, vi, pi in zip(x + (i - 0.5) * 0.36, v, p):
                ax.text(xi, vi + (0.004 if vi >= 0 else -0.004), f"{vi:+.3f}", ha="center", va="bottom" if vi >= 0 else "top",
                        fontsize=9, color=INK2)
        ax.axhline(0, color=INK2, lw=1); ax.set_xticks(x, list(names.values())); ax.grid(axis="x", visible=False)
        ax.set_ylim(-0.065, 0.07)
        ax.set_title(lab, fontsize=12, color=INK)
    axes[0].set_ylabel("IC (점수 순위 vs 초과 수익률 순위)"); axes[1].legend(frameon=False)
    fig.suptitle("업종 뉴스(하루 단위): IC 12개 모두 유의하지 않음 (p ≥ 0.19)", x=0.01, ha="left", fontsize=14, fontweight="bold", color=INK)
    fig.tight_layout(); fig.savefig(f"{DST}/03_sector_daily_ic.png", dpi=130); plt.close(fig)


# 4. 기업 IC: 갭 vs 장중
def chart_firm_ic():
    r = pd.read_csv(f"{HERE}/output/firm/firm_followup.csv")
    fig, ax = plt.subplots(figsize=(10, 4.8))
    groups = [("하루 전체", "하루"), ("개장 갭", "갭"), ("장중 (거래 가능)", "장중")]
    x = np.arange(len(groups))
    for i, (half, c) in enumerate((("앞", C1), ("뒤", C2))):
        d = r[(r["사건집합"] == "전체 사건") & (r["기간"] == half)].iloc[0]
        v = np.array([d[f"IC_{g}"] for _, g in groups])
        ci = 1.96 / np.sqrt(d["LM사건"] - 3)
        xs = x + (i - 0.5) * 0.36
        ax.bar(xs, v, 0.34, color=c, label=f"{half} 절반 ({'~2019-04' if half == '앞' else '2019-04~'})")
        ax.errorbar(xs, v, yerr=ci, fmt="none", ecolor=INK2, elinewidth=1.5)
        for xi, vi in zip(xs, v):
            ax.text(xi + 0.05, vi + (ci + 0.006 if vi >= 0 else -ci - 0.006), f"{vi:+.3f}", ha="center",
                    va="bottom" if vi >= 0 else "top", fontsize=9, color=INK2)
    ax.axhline(0, color=INK2, lw=1); ax.set_xticks(x, [g for g, _ in groups]); ax.grid(axis="x", visible=False)
    ax.set_ylabel("IC (LM 점수 vs 반응, 선 = 95% 신뢰구간)"); ax.legend(frameon=False, loc="upper right")
    title(ax, "개별 기업: 기사 톤은 개장 갭에서 반영되고, 장중에는 남지 않음", "41개 기업, LM 점수가 있는 사건 2,749개")
    fig.tight_layout(); fig.savefig(f"{DST}/04_firm_ic.png", dpi=130); plt.close(fig)


# 5. 기업: 반응 크기를 키우는/줄이는 단어
def chart_firm_words():
    w = pd.read_csv(f"{HERE}/output/firm/words_absz.csv", index_col=0)
    w = w[(w.p_앞 < 0.05) & (w.p_뒤 < 0.05) & (np.sign(w.diff_앞) == np.sign(w.diff_뒤))]
    w = w.assign(m=(w.diff_앞 + w.diff_뒤) / 2).sort_values("m")
    fig, ax = plt.subplots(figsize=(10, 7))
    y = np.arange(len(w))
    ax.hlines(y, w[["diff_앞", "diff_뒤"]].min(1), w[["diff_앞", "diff_뒤"]].max(1), color=GRID, lw=3)
    ax.scatter(w.diff_앞, y, s=70, color=C1, edgecolor=SURF, lw=1.5, label="앞 절반", zorder=3)
    ax.scatter(w.diff_뒤, y, s=70, color=C2, edgecolor=SURF, lw=1.5, label="뒤 절반", zorder=3)
    ax.axvline(0, color=INK2, lw=1)
    ax.set_yticks(y, w.index); ax.grid(axis="y", visible=False)
    ax.set_xlabel("그 단어가 나온 날의 추가 반응 크기 (평소 변동폭의 배수)")
    ax.legend(frameon=False, loc="lower right")
    title(ax, "실적 단어가 나오면 주가가 평소의 1~4배 더 움직임",
          "앞·뒤 두 기간 모두 유의한 20개 단어 (가짜 데이터 평균 2.5개)")
    fig.tight_layout(); fig.savefig(f"{DST}/05_firm_words.png", dpi=130); plt.close(fig)


if __name__ == "__main__":
    for f in (chart_coverage, chart_politics, chart_sector, chart_firm_ic, chart_firm_words):
        f(); print(f.__name__, "완료")
