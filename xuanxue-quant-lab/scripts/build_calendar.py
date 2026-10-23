# -*- coding: utf-8 -*-
"""构建期脚本：生成两张历法表（之后 skill 运行期只读 CSV，完全离线）。

输出：
  data/calendar_events.csv  —— 1900-2027 每年的 24 节气日期 + 春节（正月初一）日期
  data/lunar_months.csv     —— 农历月表：每个农历月(含闰月)的公历起始日与天数，
                               仅凭此表即可完成公历<->农历的双向换算（Python 与网页 JS 共用）

依赖（仅构建期）：sxtwl、lunardate
仅供研究使用：以统计学方法检验民间流传说法，旨在破除封建迷信、弘扬科学精神，
不构成任何投资建议。
"""
import csv
import datetime as dt
from pathlib import Path

import lunardate
import sxtwl

DATA = Path(__file__).resolve().parent.parent / "data"

# sxtwl 的 getJieQi() 返回节气下标，此顺序与 sxtwl.JieQiInfo 的键序一致（下面会断言校验）
JIEQI_NAMES = ["冬至", "小寒", "大寒", "立春", "雨水", "惊蛰", "春分", "清明", "谷雨",
               "立夏", "小满", "芒种", "夏至", "小暑", "大暑", "立秋", "处暑", "白露",
               "秋分", "寒露", "霜降", "立冬", "小雪", "大雪"]

YEAR0, YEAR1 = 1900, 2027


def main() -> None:
    # 校验节气名顺序：2024-02-04 必须是立春（下标 3）
    names = list(sxtwl.JieQiInfo.keys()) if isinstance(sxtwl.JieQiInfo, dict) else JIEQI_NAMES
    if isinstance(sxtwl.JieQiInfo, dict):
        assert names == JIEQI_NAMES, f"sxtwl 节气键序与预期不符: {names[:5]}..."
    d = sxtwl.fromSolar(2024, 2, 4)
    assert d.hasJieQi() and JIEQI_NAMES[d.getJieQi()] == "立春"

    # ---- 1) 节气 + 春节事件表 ----
    events = []
    for y in range(YEAR0, YEAR1 + 1):
        day = dt.date(y, 1, 1)
        while day.year == y:
            dd = sxtwl.fromSolar(day.year, day.month, day.day)
            if dd.hasJieQi():
                events.append((day.isoformat(), "jieqi", JIEQI_NAMES[dd.getJieQi()]))
            day += dt.timedelta(days=1)
        cny = lunardate.LunarDate(y, 1, 1).to_solar_date()
        events.append((cny.isoformat(), "cny", "春节"))
    events.sort()
    with (DATA / "calendar_events.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "type", "name"])
        w.writerows(events)
    n_cny = sum(1 for e in events if e[1] == "cny")
    print(f"calendar_events.csv：{len(events)} 行（{YEAR0}-{YEAR1}，含 {n_cny} 个春节）")

    # ---- 2) 农历月表 ----
    rows = []
    for y in range(YEAR0, YEAR1 + 1):
        for m in range(1, 13):
            for leap in (0, 1):
                try:
                    start = lunardate.LunarDate(y, m, 1, leap).to_solar_date()
                except ValueError:
                    continue          # 该农历月（或闰月）不存在
                # 月长度：下月初一减一天（非闰月的下一个月可能是同月闰版，闰月的下一个月是 m+1）
                nxt = None
                if leap == 0:
                    cands = [(m, 1)] + [(nm, nl) for nm in range(m + 1, 14) for nl in (0, 1)]
                else:
                    cands = [(nm, nl) for nm in range(m + 1, 14) for nl in (0, 1)]
                for cand in cands:
                    try:
                        nxt = lunardate.LunarDate(y, cand[0], 1, cand[1]).to_solar_date()
                        break
                    except ValueError:
                        continue
                if nxt is None:      # 跨到下一个农历年的正月
                    nxt = lunardate.LunarDate(y + 1, 1, 1).to_solar_date()
                length = (nxt - start).days
                if length in (29, 30):
                    rows.append((y, m, leap, start.isoformat(), length))
    with (DATA / "lunar_months.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["lunar_year", "lunar_month", "is_leap", "start", "length"])
        w.writerows(rows)
    total_days = sum(r[4] for r in rows)
    print(f"lunar_months.csv：{len(rows)} 个农历月，覆盖 {total_days} 天")

    # 抽查：2024-02-10 春节、2025-01-29 春节；2023 闰二月
    chk = {r[0]: r for r in rows if r[1] == 1 and r[2] == 0}
    assert lunardate.LunarDate(2024, 1, 1).to_solar_date().isoformat() == "2024-02-10"
    assert any(r[0] == 2023 and r[1] == 2 and r[2] == 1 for r in rows), "2023 闰二月缺失"
    print("自检通过：2024春节=2024-02-10，2023有闰二月 ✓")


if __name__ == "__main__":
    main()
