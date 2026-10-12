"""판별 프로세스 v2 (2026-10-09 고정). judge.py(v1) 대비 바꾼 점:
 a. 3단계 판정: 사전별 z = (주간 점수 - 직전 52주 평균) / 직전 52주 표준편차, z>+1 호재 / z<-1 악재 / 그 외 중립
 b. 사전 합의: LM·VADER·Claude 중 2개 이상 같은 판정이면 그 판정, 아니면 중립
 d. 구문 처리: 점수 단어 앞뒤 2단어 안에 반전 단어가 있으면 부호 반전, 두 단어 표현은 하나로 계산
    (처음엔 '앞 2단어'였으나 자체 점검에서 'Strike Averted' 같은 수동태를 놓쳐 결과 확인 전에 앞뒤로 수정)
워드클라우드(단어 빈도)·주 단위·NYT 기사 기준은 v1과 동일."""
import re
from collections import Counter
import numpy as np
import pandas as pd
from wordcloud_politics import NAME_RE, NAMES, STOP

REVERSERS = {"avert", "averts", "averted", "end", "ends", "ended", "ending", "lift", "lifts", "lifted",
             "ease", "eases", "eased", "resolve", "resolves", "resolved", "defuse", "defuses", "defused",
             "avoid", "avoids", "avoided", "prevent", "prevents", "prevented",
             "no", "not", "never", "without", "fail", "fails", "failed"}
PHRASES = {("debt", "ceiling"): -1, ("debt", "limit"): -1, ("tax", "cut"): 1, ("tax", "cuts"): 1,
           ("tax", "hike"): -1, ("tax", "hikes"): -1, ("tax", "increase"): -1, ("tax", "increases"): -1,
           ("trade", "deal"): 1, ("peace", "deal"): 1, ("peace", "talks"): 1, ("government", "shutdown"): -1}
WINDOW = 2


def raw_tokens(h):
    """불용어를 지우기 전의 단어 순서 (반전 단어 'no/not'을 보려면 필요). 정제 규칙은 tokens()와 동일."""
    h = h.replace("U.S.", " usa ")
    h = re.sub(r"\b(?:[A-Za-z]\.){2,}", lambda m: m.group(0).replace(".", ""), h)
    h = h.replace("’", "'").lower()
    h = re.sub(r"'s\b", "", h)
    h = re.sub(r"\bwon't\b", "will not", h)
    h = re.sub(r"n't\b", " not", h)
    h = NAME_RE.sub(lambda m: NAMES[m.group(1)], h)
    return re.findall(r"[a-z]+", h)


def headline_score(h, d, use_phrases):
    """헤드라인 하나의 점수 합. 두 단어 표현 먼저, 그다음 단어. 반전 단어가 앞뒤 WINDOW 안에 있으면 부호 반전."""
    t = raw_tokens(h)
    total, i = 0.0, 0
    while i < len(t):
        s, step = 0.0, 1
        if use_phrases and i + 1 < len(t) and (t[i], t[i + 1]) in PHRASES:
            s, step = PHRASES[(t[i], t[i + 1])], 2
        elif t[i] not in STOP and t[i] not in REVERSERS:
            s = d.get(t[i], 0)
        if s and any(w in REVERSERS for w in t[max(0, i - WINDOW):i] + t[i + step:i + step + WINDOW]):
            s = -s
        total += s
        i += step
    return total


def weekly_scores_v2(p, dicts):
    """p: headline, tok(워드클라우드 단어), week. 점수 = Σ헤드라인 점수 / 전체 단어 수 × 100"""
    s = p.groupby("week").agg(articles=("headline", "size"), words=("tok", lambda x: sum(len(t) for t in x)))
    for name, d in dicts.items():
        hs = p["headline"].map(lambda h: headline_score(h, d, use_phrases=(name == "Claude")))
        s[name] = hs.groupby(p["week"]).sum() / s["words"] * 100
        prev = s[name].shift(1).rolling(52, min_periods=12)
        s[f"{name}_z"] = (s[name] - prev.mean()) / prev.std()
        s[f"{name}_판정"] = np.select([s[f"{name}_z"] > 1, s[f"{name}_z"] < -1], ["호재", "악재"], "중립")
        s.loc[s[f"{name}_z"].isna(), f"{name}_판정"] = ""
    votes = s[[f"{n}_판정" for n in dicts]]
    good, bad = (votes == "호재").sum(1), (votes == "악재").sum(1)
    s["최종판정"] = np.select([good >= 2, bad >= 2], ["호재", "악재"], "중립")
    s.loc[(votes == "").any(axis=1), "최종판정"] = ""
    return s


if __name__ == "__main__":
    d = {"strike": -1, "deal": 1, "war": -1, "shutdown": -1}
    for h, want in [("Rail Strike Averted After Talks", 1), ("No Deal Reached", -1), ("Trade War Escalates", -1),
                    ("Senate Passes Tax Cuts", 0), ("Congress Votes To End Government Shutdown", 1), ("War Ends In Truce", 1)]:
        got = headline_score(h, d, use_phrases=True)
        print(f"{h:45s} 점수 {got:+.0f}")
        assert np.sign(got) == np.sign(want) or (want == 0 and got == 1), h  # tax cuts는 구문 +1
    print("구문 처리 자체 점검 통과")
