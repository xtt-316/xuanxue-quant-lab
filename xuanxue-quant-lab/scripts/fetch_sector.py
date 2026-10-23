# -*- coding: utf-8 -*-
"""构建期脚本：抓取五行行业帖所需的行业主题指数（每个五行一个代表），翻页取全历史。

输出 data/sector_indexes.csv：code,name,element,date,close
仅供本项目统计检验使用。本项目以统计学方法检验民间流传说法，坚持弘扬科学精神，
不构成任何投资建议。
"""
import csv
import datetime as dt
import json
import ssl
import time
import urllib.request
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
OUT = DATA_DIR / "sector_indexes.csv"
START = "2004-01-01"
END = "2026-10-20"
PAGE = 800
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

SECTORS = [
    ("sz399986", "中证银行", "金"),
    ("sz399997", "中证白酒", "水"),
    ("sz399967", "中证军工", "火"),
    ("sh000933", "中证医药", "木"),
    ("sz399393", "房地产", "土"),
]

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def fetch_page(code: str, end: str) -> list:
    url = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?"
           f"param={code},day,{START},{end},{PAGE},qfq")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    data = json.loads(urllib.request.urlopen(req, timeout=30, context=CTX).read().decode("utf-8"))
    d = data["data"].get(code) or {}
    return d.get("day") or []


def fetch_all(code: str) -> dict:
    rows: dict[str, float] = {}
    end = END
    while True:
        page = fetch_page(code, end)
        if not page:
            break
        for k in page:
            rows[k[0]] = float(k[2])
        first = page[0][0]
        if first <= START or len(page) < PAGE:
            break
        y, m, d = (int(x) for x in first.split("-"))
        end = (dt.date(y, m, d) - dt.timedelta(days=1)).isoformat()
        time.sleep(0.4)
    return rows


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_rows = []
    for code, name, el in SECTORS:
        rows = fetch_all(code)
        dates = sorted(rows)
        if len(rows) < 1200:
            print(f"[跳过] {name}({code}) 仅 {len(rows)} 天，历史不足")
            continue
        for d in dates:
            out_rows.append((code, name, el, d, rows[d]))
        print(f"OK {name}({code}) {el} {len(rows)} 天 {dates[0]} -> {dates[-1]}")
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["code", "name", "element", "date", "close"])
        w.writerows(out_rows)
    print(f"完成：{len(out_rows)} 行 -> {OUT}")


if __name__ == "__main__":
    main()
