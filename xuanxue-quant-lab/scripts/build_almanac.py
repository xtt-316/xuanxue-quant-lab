# -*- coding: utf-8 -*-
"""构建坊间玄学数据表（仅构建期联网装依赖，运行期全部离线查表）。

产出三份 CSV 到 data/：
- almanac_daily.csv   每日建除十二神 + 是否「宜纳财 开市 交易 立券」（lunar_python）
- mercury_retro.csv   水星逆行区间（pymeeus 视黄经逐日判定，公开资料校验误差约 1 天）
- moon_age.csv        每日月龄（Meeus 简化朔望算法，精度约数小时）

口径与校验输出见脚本末尾打印。
仅供研究使用：以统计学方法检验民间流传说法，坚持弘扬科学精神，不构成任何投资建议。
"""
from __future__ import annotations

import csv
import datetime as dt
import math
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
D0 = dt.date(1990, 1, 1)
D1 = dt.date(2026, 12, 31)

YI_KEYS = {"纳财", "开市", "交易", "立券"}


def build_almanac() -> list[tuple[dt.date, str, int]]:
    from lunar_python import Solar
    rows = []
    d = D0
    while d <= D1:
        lun = Solar.fromYmdHms(d.year, d.month, d.day, 12, 0, 0).getLunar()
        jc = lun.getZhiXing()          # 建除十二神：建 除 满 平 定 执 破 危 成 收 开 闭
        yi = lun.getDayYi()
        ok = 1 if YI_KEYS & set(yi) else 0
        rows.append((d, jc, ok))
        d += dt.timedelta(days=1)
    return rows


def build_mercury() -> list[tuple[dt.date, dt.date]]:
    from pymeeus.Mercury import Mercury
    from pymeeus.Epoch import Epoch

    def lon(jde: float) -> float:
        return float(Mercury.geocentric_position(Epoch(jde))[0])

    jd0 = D0.toordinal() + 1721424.5
    n = (D1 - D0).days
    prev = None
    cur_start = None
    last_retro_day = None
    out = []
    for i in range(n + 2):
        d = D0 + dt.timedelta(days=i)
        L = lon(jd0 + i + 0.5)
        if prev is not None:
            delta = (L - prev + 180.0) % 360.0 - 180.0
            if delta < 0:
                if cur_start is None:
                    cur_start = d
                last_retro_day = d
            else:
                if cur_start is not None:
                    # 平滑：区间至少 5 天才认（剔除驻点数值抖动）
                    if (last_retro_day - cur_start).days >= 5:
                        out.append((cur_start, last_retro_day))
                cur_start = None
        prev = L
    if cur_start is not None and (last_retro_day - cur_start).days >= 5:
        out.append((cur_start, last_retro_day))
    return out


# ------------------------------------------------ 月相：Meeus 简化朔望 --
def _new_moon_jde(k: int) -> float:
    """Meeus Astronomical Algorithms ch.49 截断级数：第 k 个朔的 JDE（精度数分钟）。"""
    T = k / 1236.85
    T2, T3, T4 = T * T, T * T * T, T ** 4
    jde = 2451550.09766 + 29.530588861 * k + 0.00015437 * T2 - 0.000000150 * T3 + 0.00000000073 * T4
    E = 1 - 0.002516 * T - 0.0000074 * T2
    M = 2.5534 + 29.10535670 * k - 0.0000014 * T2 - 0.00000011 * T3          # 太阳平近点角(度)
    Mp = 201.5643 + 385.81693528 * k + 0.0107582 * T2 + 0.00001238 * T3       # 月亮平近点角
    F = 160.7108 + 390.67050284 * k - 0.0016118 * T2 - 0.00000227 * T3        # 月亮纬度参数
    Om = 124.7746 - 1.56375588 * k + 0.0020672 * T2 + 0.00000215 * T3         # 升交点黄经
    A = [(299.77, 0.74058, 0.0001078), (251.88, 0.0003201, 0.0001503),
         (251.83, 0.0003249, 0.0001656), (349.42, 0.0044722, 0.0001613),
         (84.66, 0.0004773, 0.0001897), (141.74, 0.0058668, 0.0002415),
         (207.14, 0.0063987, 0.0003101), (154.84, 0.0003149, 0.0001521),
         (34.52, 0.0015333, 0.0001776), (111.33, 0.0005207, 0.0002104)]
    corr = (-0.40720 * math.sin(math.radians(Mp))
            + 0.17241 * E * math.sin(math.radians(M))
            + 0.01608 * math.sin(math.radians(2 * Mp))
            + 0.01039 * math.sin(math.radians(2 * F))
            + 0.00739 * E * math.sin(math.radians(Mp - M))
            - 0.00514 * E * math.sin(math.radians(Mp + M))
            + 0.00208 * E * E * math.sin(math.radians(2 * M))
            - 0.00111 * math.sin(math.radians(Mp - 2 * F))
            - 0.00057 * math.sin(math.radians(Mp + 2 * F))
            + 0.00056 * E * math.sin(math.radians(2 * Mp + M))
            - 0.00042 * math.sin(math.radians(3 * Mp))
            - 0.00042 * E * math.sin(math.radians(M + 2 * F))
            + 0.00038 * E * math.sin(math.radians(M - 2 * F))
            - 0.00024 * E * math.sin(math.radians(2 * Mp - M))
            - 0.00017 * math.sin(math.radians(Om))
            - 0.00007 * math.sin(math.radians(Mp + 2 * M)))
    for a, b, c in A:
        corr += b * math.sin(math.radians(a + c * k))
    return jde + corr


def _jde_to_date(jde: float) -> dt.date:
    return dt.date.fromordinal(int(jde - 1721424.5 + 0.5) + 1) if False else \
        (dt.datetime(2000, 1, 1) + dt.timedelta(days=jde - 2451545.0)).date()


def build_moon_ages() -> dict[dt.date, float]:
    """每日 12:00 UTC 相对最近一次朔的月龄（天）。"""
    jd_noon0 = D0.toordinal() + 1721424.5 - 0.5 + 0.5  # D0 12:00 UTC
    # 找覆盖范围的 k
    k_lo = int((jd_noon0 - 2451550.09766) / 29.530588861) - 2
    k_hi = int(((D1 - dt.date(2000, 1, 1)).days + 2451545.0 - 2451550.09766) / 29.530588861) + 3
    news = sorted(_new_moon_jde(k) for k in range(k_lo, k_hi))
    ages = {}
    for i in range((D1 - D0).days + 1):
        d = D0 + dt.timedelta(days=i)
        jd = d.toordinal() + 1721424.5  # 当日 0 时；月龄参考午时
        # 二分找最近的前一次朔
        lo, hi = 0, len(news) - 1
        j = -1
        while lo <= hi:
            mid = (lo + hi) // 2
            if news[mid] <= jd + 0.5:
                j = mid
                lo = mid + 1
            else:
                hi = mid - 1
        ages[d] = round(jd + 0.5 - news[j], 2)
    return ages


def main() -> None:
    print("黄历（lunar_python）……")
    alm = build_almanac()
    with (DATA / "almanac_daily.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "jianchu", "yi_ok"])
        w.writerows([[d.isoformat(), jc, ok] for d, jc, ok in alm])
    yi_days = sum(ok for _, _, ok in alm)
    print(f"  {len(alm)} 天，宜纳财开市日 {yi_days}（{100 * yi_days / len(alm):.1f}%）")

    print("水星逆行（pymeeus）……")
    retro = build_mercury()
    with (DATA / "mercury_retro.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["start", "end"])
        w.writerows([[a.isoformat(), b.isoformat()] for a, b in retro])
    span = sum((b - a).days for a, b in retro)
    print(f"  {len(retro)} 段，共 {span} 天（占 {100 * span / ((D1 - D0).days + 1):.1f}%）")
    for a, b in retro:
        if a.year == 2024:
            print(f"  2024 区间 {a} -> {b}")

    print("月相（Meeus 朔望）……")
    ages = build_moon_ages()
    with (DATA / "moon_age.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "age"])
        w.writerows([[d.isoformat(), a] for d, a in ages.items()])
    for chk in [dt.date(2024, 1, 11), dt.date(2024, 1, 25), dt.date(2024, 2, 9)]:
        near = min(ages.items(), key=lambda kv: abs((kv[0] - chk).days) + min(kv[1], 29.53 - kv[1]))
        print(f"  校验 {chk}（应为朔或望）: {near[0]} 月龄 {near[1]}")
    print("done")


if __name__ == "__main__":
    main()
