"""HuffPost 정치 기사 제목 워드클라우드 (2014~2018).
정기 연재물(뉴스레터 등) 기사 제외, 자주 나오는 인물 이름은 성 하나로 합침.
결과: 전체(trump 포함/제외 2종) + 연도별, 단어/두 단어 빈도표."""
import os
import re
from collections import Counter
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from wordcloud import WordCloud, STOPWORDS

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = f"{HERE}/output"
os.makedirs(OUT, exist_ok=True)

# 불용어: wordcloud 기본 목록 + 헤드라인에 흔한 의미 없는 말
STOP = set(STOPWORDS) | {"says", "said", "will", "just", "new", "one", "get", "gets", "may", "now", "still",
                         "re", "ll", "ve", "don", "t", "s", "can", "us", "via", "much", "way", "want", "wants",
                         "make", "makes", "going", "go", "says", "take", "takes", "know", "really", "thing", "things"}


# 매일 반복되는 정기 연재물 제목 (뉴스가 아니라 코너 이름)
SERIES = re.compile(r"morning email|huffpost rise|huffpost hill|huffpollster|friday talking points|"
                    r"headline quiz|terrible 10", re.I)
# 인물 이름 → 성 하나로 (전체 이름을 먼저, 그다음 단독으로 쓰인 이름)
NAMES = {"donald trump": "trump", "hillary clinton": "clinton", "bernie sanders": "sanders", "ted cruz": "cruz",
         "paul ryan": "ryan", "joe biden": "biden", "marco rubio": "rubio", "elizabeth warren": "warren",
         "mike pence": "pence", "jeb bush": "bush", "barack obama": "obama", "mitch mcconnell": "mcconnell",
         "nancy pelosi": "pelosi", "jeff sessions": "sessions", "robert mueller": "mueller", "ben carson": "carson",
         "chris christie": "christie", "john kasich": "kasich", "rand paul": "paul", "lindsey graham": "graham",
         "hillary": "clinton", "bernie": "sanders", "jeb": "bush", "donald": "trump"}
NAME_RE = re.compile(r"\b(" + "|".join(sorted(NAMES, key=len, reverse=True)) + r")\b")


def tokens(headline):
    h = headline.replace("U.S.", " usa ").replace("’", "'").lower()
    h = re.sub(r"'s\b", "", h)
    h = re.sub(r"\bwon't\b", "will not", h)
    h = re.sub(r"n't\b", " not", h)  # doesn't → does not (쪼개진 'doesn' 방지)
    h = NAME_RE.sub(lambda m: NAMES[m.group(1)], h)
    return [w for w in re.findall(r"[a-z]+", h) if len(w) > 1 and w not in STOP]


def cloud(freq, path, title=None, size=(1600, 900)):
    wc = WordCloud(width=size[0], height=size[1], background_color="white", max_words=150,
                   colormap="viridis", random_state=0).generate_from_frequencies(freq)
    wc.to_file(path)
    return wc


if __name__ == "__main__":
    df = pd.read_json(f"{HERE}/data/huffpost_news.json", lines=True)
    df["date"] = pd.to_datetime(df["date"])
    pol = df[(df["category"] == "POLITICS") & df.date.dt.year.between(2014, 2018)].copy()
    series = pol["headline"].str.contains(SERIES)
    print(f"정기 연재물 제외 {series.sum():,}건")
    pol = pol[~series]
    pol["tok"] = pol["headline"].map(tokens)
    print(f"정치 기사 {len(pol):,}건, {pol.date.min().date()} ~ {pol.date.max().date()}, 단어 {pol.tok.map(len).sum():,}개")

    uni = Counter(w for t in pol.tok for w in t)
    bi = Counter(f"{a} {b}" for t in pol.tok for a, b in zip(t, t[1:]))
    cloud(uni, f"{OUT}/wordcloud_politics_all.png")
    cloud({w: c for w, c in uni.items() if w != "trump"}, f"{OUT}/wordcloud_politics_all_no_trump.png")
    pd.DataFrame(uni.most_common(200), columns=["word", "count"]).to_csv(f"{OUT}/word_freq_all.csv", index=False)
    print("\n단어 상위 30:", ", ".join(f"{w}({c})" for w, c in uni.most_common(30)))
    print("\n두 단어 상위 20:", ", ".join(f"{w}({c})" for w, c in bi.most_common(20)))

    # 연도별
    pol["period"] = pol.date.dt.year.astype(str)
    periods = sorted(pol.period.unique())
    fig, axes = plt.subplots(2, 3, figsize=(18, 8))
    axes.flat[-1].axis("off")
    print()
    for ax, p in zip(axes.flat, periods):
        sub = pol[pol.period == p]
        f = Counter(w for t in sub.tok for w in t)
        ax.imshow(cloud(f, f"{OUT}/wordcloud_politics_{p}.png", size=(800, 450)))
        ax.set_title(f"{p}  ({len(sub):,} headlines)", fontsize=14)
        ax.axis("off")
        print(f"{p} ({len(sub):,}건) 상위 10: " + ", ".join(w for w, _ in f.most_common(10)))
    plt.tight_layout()
    plt.savefig(f"{OUT}/wordcloud_politics_by_year.png", dpi=110)
