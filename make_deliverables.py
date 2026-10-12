"""대표님 전달용 워드클라우드 묶음 (deliverables/wordcloud/).
NYT 정치 2014~2026: 전체(trump 포함/제외), 연도별 13장 + 한 장 모음
NYT 업종 2014~2026: 기술·에너지·헬스케어
HuffPost 정치 2014~2018: 기존 결과 복사
각 워드클라우드마다 상위 200개 단어 빈도표(csv) 함께 저장."""
import os
import shutil
from collections import Counter
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from wordcloud import WordCloud
from judge_nyt import load_nyt, nyt_tokens
from sector_nyt import SECTORS, load_all

HERE = os.path.dirname(os.path.abspath(__file__))
DST = f"{HERE}/deliverables/wordcloud"
os.makedirs(DST, exist_ok=True)


def save(freq, name, title=None, size=(1600, 900)):
    wc = WordCloud(width=size[0], height=size[1], background_color="white", max_words=150,
                   colormap="viridis", random_state=0).generate_from_frequencies(freq)
    wc.to_file(f"{DST}/{name}.png")
    pd.DataFrame(Counter(freq).most_common(200), columns=["word", "count"]).to_csv(
        f"{DST}/{name}_freq.csv", index=False, encoding="utf-8-sig")
    return wc


if __name__ == "__main__":
    p = load_nyt()
    p = p[(p.date >= "2014-01-01") & (p.date < "2026-10-01")]
    allf = Counter(w for t in p.tok for w in t)
    save(allf, "nyt_politics_2014-2026")
    save({w: c for w, c in allf.items() if w != "trump"}, "nyt_politics_2014-2026_no_trump")
    years = sorted(p.date.dt.year.unique())
    fig, axes = plt.subplots(5, 3, figsize=(18, 20))
    for ax, y in zip(axes.flat, years):
        sub = p[p.date.dt.year == y]
        wc = save(Counter(w for t in sub.tok for w in t), f"nyt_politics_{y}", size=(800, 450))
        ax.imshow(wc); ax.set_title(f"{y}  ({len(sub):,} headlines)", fontsize=14); ax.axis("off")
    for ax in axes.flat[len(years):]:
        ax.axis("off")
    plt.tight_layout(); plt.savefig(f"{DST}/nyt_politics_by_year.png", dpi=100); plt.close()

    df = load_all()
    df = df[(df.date >= "2014-01-01") & (df.date < "2026-10-01")]
    for sec, (etf, sel) in SECTORS.items():
        sub = df[sel(df)]
        save(Counter(w for h in sub.headline for w in nyt_tokens(h)), f"nyt_sector_{sec}_{etf}")

    for f in ("wordcloud_politics_all.png", "wordcloud_politics_all_no_trump.png", "wordcloud_politics_by_year.png",
              "word_freq_all.csv"):
        shutil.copy(f"{HERE}/output/{f}", f"{DST}/huffpost_{f.replace('wordcloud_politics_', 'politics_2014-2018_')}")
    print(f"{len(os.listdir(DST))}개 파일 → {DST}")
    print("NYT 정치 상위 15:", ", ".join(f"{w}({c})" for w, c in allf.most_common(15)))
