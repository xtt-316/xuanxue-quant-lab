# -*- coding: utf-8 -*-
"""抓取上证指数(000001.SH)全部日线收盘价，保存为 data/shanghai_composite.csv。

数据源：腾讯行情接口（单次上限 800 条，自动向前翻页直到取完）。
仅在构建期联网运行一次；skill 运行期只读打包好的 CSV，完全离线。
仅供研究使用：以统计学方法检验民间流传说法，旨在破除封建迷信、弘扬科学精神，
不构成任何投资建议。
"""
import csv
import json
import ssl
import sys
import time
import urllib.request
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
OUT_CSV = DATA_DIR / "shanghai_composite.csv"
CODE = "sh000001"
START = "1990-12-19"          # 上证指数基日
END = "2026-10-20"
PAGE = 800                    # 接口单页上限
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def fetch_page(end: str) -> list:
    """取 [START, end] 区间内最后 PAGE 个交易日，返回 [[date, open, close, ...], ...]。"""
    url = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?"
           f"param={CODE},day,{START},{end},{PAGE},qfq")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    raw = urllib.request.urlopen(req, timeout=30, context=CTX).read().decode("utf-8")
    data = json.loads(raw)["data"][CODE]
    return data.get("qfqday") or data.get("day") or []


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    rows: dict[str, float] = {}   # date -> close，用 dict 自动去重
    end = END
    while True:
        page = fetch_page(end)
        if not page:
            break
        for k in page:
            rows[k[0]] = float(k[2])          # [date, open, close, high, low, vol, ...]
        first = page[0][0]
        print(f"  已取 {len(rows):5d} 天（当前最早 {first}，截至 {end}）")
        if first <= START or len(page) < PAGE:
            break
        y, m, d = (int(x) for x in first.split("-"))
        # 回退一天作为新的 end，继续向更早翻页
        import datetime as _dt
        end = (_dt.date(y, m, d) - _dt.timedelta(days=1)).isoformat()
        time.sleep(0.4)

    if len(rows) < 5000:
        print(f"[警告] 仅取得 {len(rows)} 条，数据可能不完整", file=sys.stderr)

    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "close"])
        for d in sorted(rows):
            w.writerow([d, rows[d]])
    dates = sorted(rows)
    print(f"完成：{len(rows)} 个交易日  {dates[0]} → {dates[-1]}  已写入 {OUT_CSV}")


if __name__ == "__main__":
    main()
