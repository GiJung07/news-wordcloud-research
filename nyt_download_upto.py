"""(전진 검증용) NYT Archive API로 2014-01 ~ 이번 달까지 월별 전체 기사 목록 다운로드 (필요한 필드만 저장).
월별 파일이 이미 있으면 건너뜀 → 중간에 끊겨도 다시 실행하면 이어서 받음. 요청 간격 12초."""
import json
import os
import re
import time
import urllib.error
import urllib.request
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = f"{HERE}/data/nyt"
KEY_FILE = "D:/Downloads/files/nyt_api_key.env"
os.makedirs(OUT, exist_ok=True)
KEY = re.search(r"NYT_API_KEY\s*=\s*([A-Za-z0-9_\-]+)", open(KEY_FILE, encoding="utf-8-sig").read()).group(1)


def fetch(y, m, tries=5):
    url = f"https://api.nytimes.com/svc/archive/v1/{y}/{m}.json?api-key={KEY}"
    for i in range(tries):
        try:
            return json.load(urllib.request.urlopen(url, timeout=180))["response"]["docs"]
        except urllib.error.HTTPError as e:
            if e.code == 429:            # 한도 초과 → 길게 쉬고 재시도
                time.sleep(60 * (i + 1))
            elif e.code >= 500:
                time.sleep(20)
            else:
                raise
        except (urllib.error.URLError, TimeoutError):
            time.sleep(20)
    raise RuntimeError(f"{y}-{m:02d} 실패")


if __name__ == "__main__":
    t = time.localtime()
    months = [(y, m) for y in range(2014, t.tm_year + 1) for m in range(1, 13) if (y, m) <= (t.tm_year, t.tm_mon)]
    for y, m in months:
        path = f"{OUT}/{y}-{m:02d}.csv.gz"
        if os.path.exists(path):
            continue
        docs = fetch(y, m)
        pd.DataFrame([dict(pub_date=d.get("pub_date"), headline=(d.get("headline") or {}).get("main"),
                           section=d.get("section_name"), subsection=d.get("subsection_name"),
                           desk=d.get("news_desk"), type=d.get("type_of_material"), doc=d.get("document_type"),
                           word_count=d.get("word_count"), url=d.get("web_url")) for d in docs]).to_csv(path, index=False)
        print(f"{y}-{m:02d}: {len(docs):,}건", flush=True)
        time.sleep(12)
    print("완료")
