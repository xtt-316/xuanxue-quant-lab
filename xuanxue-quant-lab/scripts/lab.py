# -*- coding: utf-8 -*-
"""统计引擎：民间命理说法 vs 上证指数 的统计检验（全项目唯一数字来源）。

检验方法：把交易日分成玄学组（满足民间说法的日子）与对照组（其余日子），
比较两组日均收益的差异是否统计显著（Welch t 检验，双尾）。
多重比较用 Bonferroni 校正。

依赖：numpy（必须）；scipy（可选，缺失时自动退回内置 t 分布 p 值计算）
仅供研究使用：以统计学方法检验民间流传说法，旨在破除封建迷信、弘扬科学精神，
不构成任何投资建议。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
from pathlib import Path

import numpy as np

import profile as pf

DATA = Path(__file__).resolve().parent.parent / "data"
MIN_N = 25                 # 每组少于该样本量判“样本不足”
JIEQI_WINDOW = 15          # 节气检验窗口：节气当日起 15 个自然日
P_CUTOFF = 0.05

DISCLAIMER = "本项目以统计学方法检验民间流传说法，坚持弘扬科学精神，不构成任何投资建议。"


# ---------------------------------------------------------------- p 值计算 --
def _betacf(a: float, b: float, x: float) -> float:
    MAXIT, EPS, FPMIN = 200, 3e-12, 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    if abs(d) < FPMIN:
        d = FPMIN
    d = 1.0 / d
    h = d
    for m in range(1, MAXIT + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        dele = d * c
        h *= dele
        if abs(dele - 1.0) < EPS:
            break
    return h


def _betai(a: float, b: float, x: float) -> float:
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    bt = math.exp(lbeta + a * math.log(x) + b * math.log(1 - x))
    if x < (a + 1) / (a + b + 2):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1 - x) / b


def t_sf_two_sided(t: float, df: float) -> float:
    """t 分布双尾 p 值。优先 scipy，缺失用不完全 Beta 函数。"""
    try:
        from scipy import stats
        return float(2 * stats.t.sf(abs(t), df))
    except Exception:
        if math.isnan(t) or df <= 0:
            return float("nan")
        return float(_betai(df / 2.0, 0.5, df / (df + t * t)))


# ---------------------------------------------------------------- 市场数据 --
JIANCHU = ["建", "除", "满", "平", "定", "执", "破", "危", "成", "收", "开", "闭"]
SANHE_GROUPS = [("鼠", "龙", "猴"), ("牛", "蛇", "鸡"), ("虎", "马", "狗"), ("兔", "羊", "猪")]
MOON_HALF = 14.765            # 朔望周期一半：月龄小于此为盈月（朔后至望）
JIEQI_ALL_WINDOW = 5          # 节气变盘问：每个节气后 5 个自然日


class Market:
    def __init__(self):
        import csv
        with (DATA / "shanghai_composite.csv").open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        self.dates = [dt.date.fromisoformat(r["date"]) for r in rows]
        self.close = np.array([float(r["close"]) for r in rows])
        self.ret = np.concatenate([[np.nan], self.close[1:] / self.close[:-1] - 1.0])
        self.cal = pf.Calendar()

        # 每个交易日的派生属性（供各分类器共用，全部先算好）
        self.month = np.array([d.month for d in self.dates])
        self.day = np.array([d.day for d in self.dates])
        self.weekday = np.array([d.weekday() for d in self.dates])
        self.lunar_year = np.array([self.cal.solar_to_lunar(d)[0] for d in self.dates])
        self.jd = np.array([(d - dt.date(1899, 12, 31)).days for d in self.dates])  # 日序

        # 坊间玄学数据表（构建期由 build_almanac.py 生成，运行期离线查表）
        self._load_almanac()

        # 节气日期序数：name -> 升序日期数组
        self.jieqi_days: dict[str, np.ndarray] = {}
        for d0, name in self.cal.jieqi:
            self.jieqi_days.setdefault(name, []).append((d0 - dt.date(1899, 12, 31)).days)
        self.jieqi_days = {k: np.array(v) for k, v in self.jieqi_days.items()}
        self.all_jieqi_jd = np.array(sorted(x for v in self.jieqi_days.values() for x in v))

        # 月度首个/末个交易日掩码（turn-of-month 用）
        first3, last1, month_id = [], [], []
        ym_prev = None
        for i, d in enumerate(self.dates):
            ym = (d.year, d.month)
            month_id.append(ym)
        month_id = np.array([y * 100 + m for y, m in month_id])
        self.month_id = month_id
        f3 = np.zeros(len(self.dates), dtype=bool)
        l1 = np.zeros(len(self.dates), dtype=bool)
        for m0 in np.unique(month_id):
            idx = np.where(month_id == m0)[0]
            f3[idx[:3]] = True
            l1[idx[-1]] = True
        self.first3 = f3
        self.last1 = l1

    def _load_almanac(self) -> None:
        """黄历宜忌 / 水星逆行 / 月龄 三表对齐到交易日（无表则全 False，页面如实降级）。"""
        import csv as _csv
        n = len(self.dates)
        self.yi = np.zeros(n, dtype=bool)          # 宜纳财开市日
        self.jianchu = np.full(n, -1, dtype=int)   # 建除十二神序号
        self.retro = np.zeros(n, dtype=bool)       # 水星逆行日
        self.moon_age = np.full(n, np.nan)
        try:
            with (DATA / "almanac_daily.csv").open(encoding="utf-8") as f:
                alm = {r["date"]: (r["jianchu"], int(r["yi_ok"])) for r in _csv.DictReader(f)}
            for i, d in enumerate(self.dates):
                rec = alm.get(d.isoformat())
                if rec:
                    self.jianchu[i] = JIANCHU.index(rec[0]) if rec[0] in JIANCHU else -1
                    self.yi[i] = bool(rec[1])
            with (DATA / "mercury_retro.csv").open(encoding="utf-8") as f:
                spans = [(dt.date.fromisoformat(r["start"]), dt.date.fromisoformat(r["end"]))
                         for r in _csv.DictReader(f)]
            for i, d in enumerate(self.dates):
                self.retro[i] = any(a <= d <= b for a, b in spans)
            with (DATA / "moon_age.csv").open(encoding="utf-8") as f:
                ages = {r["date"]: float(r["age"]) for r in _csv.DictReader(f)}
            for i, d in enumerate(self.dates):
                v = ages.get(d.isoformat())
                if v is not None:
                    self.moon_age[i] = v
        except FileNotFoundError:
            pass


# ---------------------------------------------------------------- 分类器 --
def mask_sign(mk: Market, sign: str) -> np.ndarray:
    """星座月：落在该星座 (m,d) 区间（含跨年）的日子。"""
    starts = dict(pf.CONSTELLATIONS + [((12, 22), "摩羯座")])
    ends = {(1, 19): "摩羯座", (2, 18): "水瓶座", (3, 20): "双鱼座", (4, 19): "白羊座",
            (5, 20): "金牛座", (6, 21): "双子座", (7, 22): "巨蟹座", (8, 22): "狮子座",
            (9, 22): "处女座", (10, 23): "天秤座", (11, 22): "天蝎座", (12, 21): "射手座"}
    s = next(k for k, v in starts.items() if v == sign)
    e = next(k for k, v in ends.items() if v == sign)
    md = mk.month * 100 + mk.day
    s_v, e_v = s[0] * 100 + s[1], e[0] * 100 + e[1]
    if s_v <= e_v:
        return (md >= s_v) & (md <= e_v)
    return (md >= s_v) | (md <= e_v)          # 摩羯座跨年


def mask_month(mk: Market, month: int) -> np.ndarray:
    return mk.month == month


def mask_day(mk: Market, day: int) -> np.ndarray:
    return mk.day == day


def mask_animal(mk: Market, animal: str) -> np.ndarray:
    idx = pf.ANIMALS.index(animal)
    return np.array([(int(y) - 4) % 12 == idx for y in mk.lunar_year])


def mask_element(mk: Market, element: str) -> np.ndarray:
    nayin = np.array([pf.Calendar.nayin(int(y)) for y in mk.lunar_year])
    return np.array([n[-1] == element for n in nayin])


def mask_jieqi(mk: Market, name: str, window: int = JIEQI_WINDOW) -> np.ndarray:
    """节气当日起 window 个自然日。"""
    days = mk.jieqi_days[name]
    out = np.zeros(len(mk.jd), dtype=bool)
    for start in days:
        out |= (mk.jd >= start) & (mk.jd < start + window)
    return out


def mask_lunar_birthday(mk: Market, lm: int, ld: int, leap: int) -> np.ndarray:
    """每年农历生日当天（闰月生日取非闰同月同日；该日不存在则跳过该年）。"""
    hit = np.zeros(len(mk.jd), dtype=bool)
    years = sorted(set(int(y) for y in mk.lunar_year))
    for y in years:
        s = mk.cal.lunar_to_solar(y, lm, ld, 0)
        if s is None:
            continue
        j = (s - dt.date(1899, 12, 31)).days
        hit |= mk.jd == j
    return hit


def mask_turn_of_month(mk: Market) -> np.ndarray:
    return mk.first3 | mk.last1


# ------------------------------------------------ 坊间玄学掩码（v5 新七问） --
def mask_almanac_yi(mk: Market) -> np.ndarray:
    """黄历宜忌：宜纳财 开市 交易 立券之日。"""
    return mk.yi.copy()


def mask_jianchu(mk: Market, jc: str) -> np.ndarray:
    return mk.jianchu == JIANCHU.index(jc)


def mask_mercury_retro(mk: Market) -> np.ndarray:
    return mk.retro.copy()


def mask_moon_waxing(mk: Market) -> np.ndarray:
    """盈月：朔后至望（月龄小于半周期）。用与网页一致的 1 位舍入值判定。"""
    return np.round(mk.moon_age, 1) < MOON_HALF


def moon_quarter(mk: Market) -> np.ndarray:
    """月相四相分区：0 朔后 1 盈 2 望后 3 亏（各约四分之一周期）。"""
    age = np.where(np.isnan(mk.moon_age), 99.0, mk.moon_age)
    return np.select([age < 7.38, age < MOON_HALF, age < 22.15, age < 29.53],
                     [0, 1, 2, 3], default=-1)


def mask_jieqi_all(mk: Market, window: int = JIEQI_ALL_WINDOW) -> np.ndarray:
    """节气变盘：所有节气当日起 window 个自然日。"""
    out = np.zeros(len(mk.jd), dtype=bool)
    for start in mk.all_jieqi_jd:
        out |= (mk.jd >= start) & (mk.jd < start + window)
    return out


def mask_digit(mk: Market, digit: int) -> np.ndarray:
    """数字禁忌：日号含某数字（如 4 → 每月 4 14 24 号；8 → 8 18 28 号）。"""
    return (mk.day % 10 == digit) | (mk.day // 10 == digit)


def sanhe_of(animal: str) -> tuple:
    for grp in SANHE_GROUPS:
        if animal in grp:
            return grp
    raise ValueError(animal)


def mask_sanhe(mk: Market, animal: str) -> np.ndarray:
    """三合流年：与生肖同属三合组（申子辰 亥卯未 寅午戌 巳酉丑）的年份。"""
    grp = set(sanhe_of(animal))
    return np.array([pf.ANIMALS[(int(y) - 4) % 12] in grp for y in mk.lunar_year])


def mask_pre_cny(mk: Market, k: int = 5) -> np.ndarray:
    """春节（正月初一）前 k 个交易日。"""
    hit = np.zeros(len(mk.jd), dtype=bool)
    for d0 in mk.cal.cny.values():
        j = (d0 - dt.date(1899, 12, 31)).days
        idx = np.where(mk.jd < j)[0]
        if len(idx):
            hit[idx[-k:]] = True
    return hit


WEEKDAY_NAMES = ["周一", "周二", "周三", "周四", "周五"]


# ---------------------------------------------------------------- 检验 --
def run_test(mk: Market, key: str, title: str, claim: str, mask: np.ndarray,
             origin: str = None, origin_bai: str = None) -> dict:
    r = mk.ret[1:]                       # 去掉首个 NaN
    m = mask[1:]
    a, b = r[m], r[~m]
    n1, n0 = len(a), len(b)
    if min(n1, n0) < 2:                  # 如农历正月初一：春节休市，样本期从未开盘
        return {
            "key": key, "title": title, "claim": claim,
            "origin": origin, "origin_bai": origin_bai,
            "n1": n1, "n0": n0, "mean1_bp": None, "mean0_bp": None,
            "sd1_bp": None, "sd0_bp": None, "t": None, "df": None, "p": None,
            "verdict": "insufficient",
            "verdict_text": ("样本期内该日子从未出现在交易日里（春节休市），玄学无从谈起"
                             if n1 == 0 else "样本不足，无法下结论"),
            "verdict_bai": ("股市在春节放假，这个日子从来没开过盘，说法再玄也无处显灵"
                            if n1 == 0 else "满足说法的交易日太少，数据不够下结论"),
            "strat_curve": None, "bench_curve": None,
        }
    m1, m0 = float(a.mean()), float(b.mean())
    s1, s0 = float(a.std(ddof=1)), float(b.std(ddof=1))
    t = (m1 - m0) / math.sqrt(s1 * s1 / n1 + s0 * s0 / n0)
    df = (s1 * s1 / n1 + s0 * s0 / n0) ** 2 / (
        (s1 * s1 / n1) ** 2 / (n1 - 1) + (s0 * s0 / n0) ** 2 / (n0 - 1))
    p = t_sf_two_sided(t, df)

    if min(n1, n0) < MIN_N:
        verdict, verdict_text = "insufficient", "样本不足，无法下结论"
        verdict_bai = "满足说法的交易日太少，数据不够下结论"
    elif p < P_CUTOFF:
        better = "玄学组" if m1 > m0 else "对照组"
        verdict = "significant"
        verdict_text = f"名义上显著（p={p:.3f}，{better}日均收益更高），但先别激动，见多重比较章节"
        verdict_bai = "表面看 p 值小于 0.05 像有关系，但试的日子一多总会撞上几个假显著，先别当真，看压轴的多重比较"
    else:
        verdict, verdict_text = "null", "无统计显著关系"
        verdict_bai = "这两组行情的差别和随机波动分不开，说法不成立"

    # 净值曲线（仅在玄学组日“持仓”）
    strat = np.cumprod(1 + np.where(mask[1:], r, 0.0))
    bench = np.cumprod(1 + r)
    return {
        "key": key, "title": title, "claim": claim,
        "origin": origin, "origin_bai": origin_bai,
        "n1": n1, "n0": n0,
        "mean1_bp": round(m1 * 1e4, 2), "mean0_bp": round(m0 * 1e4, 2),
        "sd1_bp": round(s1 * 1e4, 2), "sd0_bp": round(s0 * 1e4, 2),
        "t": round(t, 3), "df": round(df, 1), "p": (None if math.isnan(p) else round(p, 4)),
        "verdict": verdict, "verdict_text": verdict_text, "verdict_bai": verdict_bai,
        "strat_curve": [round(x, 4) for x in strat[::max(1, len(strat) // 600)]],
        "bench_curve": [round(x, 4) for x in bench[::max(1, len(bench) // 600)]],
    }


def personal_tests(mk: Market, prof: dict) -> list[dict]:
    # 坊间七问：全部取市面上最通行的玄学炒股说法，逐条变成可回测策略。
    # 黄历 水逆 月相 节气 数字为全市场通行；本命年与三合仍与客官生肖挂钩。
    return [
        run_test(mk, "almanac", "坊间七问 其一 黄历宜忌",
                 "民间说法：黄历宜纳财开市之日行情更旺，宜日动仓凶日不动",
                 mask_almanac_yi(mk),
                 origin="坊间原版：老黄历择日传统，每日建除十二神定宜忌，宜纳财 开市 交易 立券方能动财",
                 origin_bai="这就是翻黄历看宜字炒股，市面上最正统的择日法，持仓约占三分之一交易日"),
        run_test(mk, "retro", "坊间七问 其二 水星逆行",
                 "民间说法：水星逆行期间诸事不顺，不宜签约交易，宜空仓观望",
                 mask_mercury_retro(mk),
                 origin="坊间原版：当代占星水逆论，每年三到四次，每次约三周，星象 App 皆言此间勿做重大决定",
                 origin_bai="水逆不炒股是星座玄学的顶流玩法，我们用天文算法逐日算出 1990 年以来全部水逆期再检验"),
        run_test(mk, "moon", "坊间七问 其三 满月效应",
                 "民间说法：新月渐盈行情渐旺，满月之后由盈转亏，买新月 卖满月",
                 mask_moon_waxing(mk),
                 origin="坊间原版：月相交易法（Lunar Cycle），券商研报亦写过满月效应，新月至上弦下注 满月后收手",
                 origin_bai="跟着月亮做，月亮从新月长到满月的约半个月里持有，其余空仓"),
        run_test(mk, "animal", f"坊间七问 其四 本命年避险 属{prof['animal']}",
                 "民间主流说法：本命年犯太岁 宜守不宜攻 不宜重仓搏杀（另有本命年搏一把的少数派）",
                 mask_animal(mk, prof["animal"]),
                 origin=f"坊间原版：命理主流，属{prof['animal']}之人逢{prof['animal']}年犯太岁，红腰带之外 更宜减仓避险",
                 origin_bai="主流版本是本命年要守：策略按你生肖年空仓、其余满仓来算；正向搏一把的终值附在卡后"),
        run_test(mk, "jieqi_all", "坊间七问 其五 节气变盘",
                 f"民间说法：节气前后市场易变盘，节气后{JIEQI_ALL_WINDOW}日行情启动",
                 mask_jieqi_all(mk),
                 origin="坊间原版：股民圈节气变盘论（江恩理论亦重节气时间窗），二十四节气皆为时间之窗",
                 origin_bai="一年 24 个节气，每个节气之后的几天都满仓，看节气是不是真的带来行情"),
        run_test(mk, "digit", "坊间七问 其六 数字禁忌 逢四",
                 "市井说法：四谐音死 逢四不发（4 14 24 号勿动）；八谐音发 逢八必发（8 18 28 号宜买）",
                 mask_digit(mk, 4),
                 origin="坊间原版：市井数字禁忌，谐音定吉凶，楼层车牌挑八避四，炒股亦然",
                 origin_bai="检验每月 4 14 24 号（玄学组）与其余日子；逢八满仓的终值附在卡后双向对照"),
        run_test(mk, "sanhe", f"坊间七问 其七 三合流年 属{prof['animal']}",
                 f"命理说法：与生肖三合之年运势顺遂（合太岁），属{prof['animal']}逢{''.join(sanhe_of(prof['animal']))}年宜重仓",
                 mask_sanhe(mk, prof["animal"]),
                 origin=f"坊间原版：命理三合，申子辰 亥卯未 寅午戌 巳酉丑各成一局，与属相三合之年年运相扶",
                 origin_bai="命理说跟你生肖合得来的那几年运气顺，策略就是这几年满仓其余空仓"),
    ]


# 七问各自对应的可回测策略文案（全项目唯一来源；网页端模板由此生成）
# 格式统一为策略名：规则，由冒号分隔，供台词拆分使用
STRATEGY_TEMPLATES = {
    "almanac": "黄历择时：宜纳财开市之日满仓，其余空仓",
    "retro": "水逆避险：水星逆行期间空仓，顺行才持有",
    "moon": "月相轮动：新月后持有，满月后空仓",
    "animal": "本命年避险：属{animal}的生肖年空仓，其余年份满仓，正向搏一把终值另附",
    "jieqi_all": "节气轮动：每个节气之后{window}个自然日满仓，年年如此",
    "digit": "逢四避险：每月4 14 24号空仓，其余满仓，逢八满仓终值另附",
    "sanhe": "三合流年：与属{animal}三合之年满仓，其余年份空仓",
}


def strategy_text(key: str, prof: dict) -> str:
    return STRATEGY_TEMPLATES[key].format(
        animal=prof.get("animal", ""), window=JIEQI_ALL_WINDOW)


def attach_strategies(mk: Market, tests: list, prof: dict,
                      answers: dict = None, ws: str = None) -> None:
    """为七问附上策略文案与终值（全量计算，非抽样）。

    红线（strat_curve）为 玄学信号x行为规则 的合体曲线：
    信号允许日才可持仓，客官的六答规则定押多少 何时加减仓。
    照做 / 反做为固定仓位满仓口径的对照终值；避险类策略持有非凶日。
    """
    r = mk.ret[1:]
    for t in tests:
        t["strategy"] = strategy_text(t["key"], prof)
        if t.get("strat_curve") is not None:
            m = mask_for_profile(mk, prof, t["key"])[1:]
            # 避险类：掩码=凶日，策略持有的是非凶日（水逆空仓 逢四空仓 本命年避险）
            avoid = t["key"] in ("retro", "digit", "animal")
            hold_m = ~m if avoid else m
            t["strategy_total"] = round(float(np.cumprod(1 + np.where(hold_m, r, 0.0))[-1]), 2)
            t["strategy_total_rev"] = round(float(np.cumprod(1 + np.where(~hold_m, r, 0.0))[-1]), 2)
            # 本命年：主版本避险（生肖年空仓），正向终值单独附注
            if t["key"] == "animal":
                t["strategy_total_fwd"] = round(float(np.cumprod(1 + np.where(m, r, 0.0))[-1]), 2)
            if t["key"] == "digit":
                t["strategy_total_fwd"] = round(
                    float(np.cumprod(1 + np.where(mask_digit(mk, 8)[1:], r, 0.0))[-1]), 2)
            # 合体红线：玄学允许日 x 行为规则
            if answers is not None and ws is not None:
                full_hold = np.concatenate([[False], hold_m])
                beh = behavior_strategy(mk, answers, ws, hold=full_hold)
                t["strategy_total_bih"] = beh["total"]
                t["strat_curve"] = beh["curve"]


def mask_for_profile(mk: Market, prof: dict, key: str) -> np.ndarray:
    """按检验 key 返回该问对应的玄学组掩码（全市场问与生辰无关）。"""
    if key == "almanac":
        return mask_almanac_yi(mk)
    if key == "retro":
        return mask_mercury_retro(mk)
    if key == "moon":
        return mask_moon_waxing(mk)
    if key == "animal":
        return mask_animal(mk, prof["animal"])
    if key == "jieqi_all":
        return mask_jieqi_all(mk)
    if key == "digit":
        return mask_digit(mk, 4)
    if key == "sanhe":
        return mask_sanhe(mk, prof["animal"])
    # 旧版七问掩码（静态卷宗 典籍对照保留）
    if key == "sign":
        return mask_sign(mk, prof["constellation"])
    if key == "month":
        return mask_month(mk, prof["birth_month"])
    if key == "day":
        return mask_day(mk, prof["birth_day"])
    if key == "lunar":
        return mask_lunar_birthday(mk, prof["lunar"]["month"], prof["lunar"]["day"],
                                    prof["lunar"]["is_leap"])
    if key == "jieqi":
        return mask_jieqi(mk, prof["jieqi"]["name"])
    if key == "element":
        return mask_element(mk, prof["nayin_element"])
    raise KeyError(key)


def scan_family(mk: Market, family: str) -> dict:
    """全扫描：某个属性族的所有取值都检验一遍（p 值墙的原材料）。"""
    if family == "day":
        items = [(str(d), f"每月{d}号", mask_day(mk, d)) for d in range(1, 32)]
        claim = "每月 X 号是我的幸运日"
    elif family == "jieqi":
        jieqi_order = ["冬至", "小寒", "大寒", "立春", "雨水", "惊蛰", "春分", "清明", "谷雨",
                       "立夏", "小满", "芒种", "夏至", "小暑", "大暑", "立秋", "处暑", "白露",
                       "秋分", "寒露", "霜降", "立冬", "小雪", "大雪"]
        items = [(n, n, mask_jieqi(mk, n)) for n in jieqi_order]
        claim = "节气 X 之后更容易涨"
    elif family == "month":
        items = [(str(m), f"{m}月", mask_month(mk, m)) for m in range(1, 13)]
        claim = "X 月的行情更好"
    elif family == "animal":
        items = [(a, f"属{a}的本命年", mask_animal(mk, a)) for a in pf.ANIMALS]
        claim = "生肖 X 的年份行情更好"
    elif family == "element":
        items = [(e, f"{e}年", mask_element(mk, e)) for e in ["金", "木", "水", "火", "土"]]
        claim = "五行属 X 的年份行情更好"
    elif family == "jianchu":
        items = [(j, f"建除{j}日", mk.jianchu == i) for i, j in enumerate(JIANCHU)]
        claim = "建除十二神定吉凶 X 值日宜买"
    elif family == "moonphase":
        q = moon_quarter(mk)
        names = ["朔后（新月周）", "盈月（上弦周）", "望后（满月周）", "亏月（下弦周）"]
        items = [(str(i), names[i], q == i) for i in range(4)]
        claim = "月相 X 期间行情更好"
    else:
        raise ValueError(family)

    res = []
    for key, label, msk in items:
        r = mk.ret[1:]
        m = msk[1:]
        a, b = r[m], r[~m]
        n1, n0 = len(a), len(b)
        if min(n1, n0) < 5:
            continue
        m1, m0 = float(a.mean()), float(b.mean())
        s1, s0 = float(a.std(ddof=1)), float(b.std(ddof=1))
        t = (m1 - m0) / math.sqrt(s1 * s1 / n1 + s0 * s0 / n0)
        df = (s1 * s1 / n1 + s0 * s0 / n0) ** 2 / (
            (s1 * s1 / n1) ** 2 / (n1 - 1) + (s0 * s0 / n0) ** 2 / (n0 - 1))
        res.append({"key": key, "label": label, "n1": n1,
                    "mean1_bp": round(m1 * 1e4, 2), "mean0_bp": round(m0 * 1e4, 2),
                    "t": round(t, 3), "p": round(t_sf_two_sided(t, df), 4),
                    "diff_bp": round((m1 - m0) * 1e4, 2)})
    m_tests = len(res)
    for x in res:
        x["p_bonf"] = round(min(1.0, x["p"] * m_tests), 4)
    sig_raw = [x for x in res if x["p"] < P_CUTOFF]
    sig_adj = [x for x in res if x["p_bonf"] < P_CUTOFF]
    expected = round(P_CUTOFF * m_tests, 1)
    return {"family": family, "claim": claim, "items": res,
            "m": m_tests,
            "n_sig_raw": len(sig_raw), "sig_raw": [x["key"] for x in sig_raw],
            "n_sig_adj": len(sig_adj), "sig_adj": [x["key"] for x in sig_adj],
            "expected_false_pos": expected}


def classic_tests(mk: Market) -> list[dict]:
    out = [run_test(mk, "tom", "典籍对照 月末月初效应",
                    "学术文献里的“真”日历效应：每月前3个+最后1个交易日",
                    mask_turn_of_month(mk)),
           run_test(mk, "precny", "典籍对照 春节前行情",
                    "民间与券商都爱说的：春节前5个交易日行情偏暖",
                    mask_pre_cny(mk, 5))]
    for i, name in enumerate(WEEKDAY_NAMES):
        out.append(run_test(mk, f"wd{i}", f"典籍对照 星期效应 {name}",
                            f"民间说法：{name}的大盘有固定脾气",
                            mk.weekday == i))
    return out


# ---------------------------------------------------------------- 问券 --
# 互动问券（网页对话选项 / skill 由 AI 代问）：风格分与五行偏好
QUESTIONNAIRE = [
    {"key": "q1", "question": "客官账户浮亏一成，心中作何打算？",
     "options": [("A", "加仓摊薄 越跌越买", 2.0, None),
                 ("B", "关灯吃面 装死不动", 1.0, None),
                 ("C", "割肉离场 另寻高枝", 0.0, None)]},
    {"key": "q2", "question": "客官看盘，最爱哪路生意？",
     "options": [("金", "银行钢铁 老钱之地", None, "金"),
                 ("木", "农林中药 草木之生", None, "木"),
                 ("水", "酒水航运 消涓之流", None, "水"),
                 ("火", "军工光伏 烈火之势", None, "火"),
                 ("土", "建筑建材 厚土之基", None, "土")]},
    {"key": "q3", "question": "盈利两成，客官如何处置？",
     "options": [("A", "落袋为安", 0.0, None),
                 ("B", "让利润奔跑", 1.5, None),
                 ("C", "加杠杆搏一把", 3.0, None)]},
    {"key": "q4", "question": "客官更信哪种赚钱路子？",
     "options": [("A", "内幕消息", None, None),
                 ("B", "价值投资", None, None),
                 ("C", "技术分析", None, None),
                 ("D", "随缘", None, None)]},
    {"key": "q5", "question": "一笔仓位，客官通常拿多久？",
     "options": [("A", "数日便卖", None, None),
                 ("B", "半年上下", None, None),
                 ("C", "三年以上", None, None),
                 ("D", "从不看盘", None, None)]},
    {"key": "q6", "question": "若依你命帖行仓，客官肯押几成？",
     "options": [("A", "一成试水", None, None),
                 ("B", "三成为度", None, None),
                 ("C", "半仓相搏", None, None),
                 ("D", "全押不悔", None, None)]},
]


def parse_answers(raw):
    parts = [x.strip() for x in raw.split(",")] if raw else []
    return {"q1": parts[0] if len(parts) > 0 and parts[0] in "ABC" else "B",
            "q2": parts[1] if len(parts) > 1 and parts[1] in "金木水火土" else None,
            "q3": parts[2] if len(parts) > 2 and parts[2] in "ABC" else "A",
            "q4": parts[3] if len(parts) > 3 and parts[3] in "ABCD" else "D",
            "q5": parts[4] if len(parts) > 4 and parts[4] in "ABCD" else "B",
            "q6": parts[5] if len(parts) > 5 and parts[5] in "ABCD" else "C",
            "defaulted": not raw}


POS_OF_ANSWER = {"A": 0.1, "B": 0.3, "C": 0.5, "D": 1.0}
POS_NAME = {0.1: "一成", 0.3: "三成", 0.5: "半仓", 1.0: "全押"}


def answers_info(answers):
    score = {"A": 2.0, "B": 1.0, "C": 0.0}[answers["q1"]] + {"A": 0.0, "B": 1.5, "C": 3.0}[answers["q3"]]
    pos = POS_OF_ANSWER[answers["q6"]]
    return {"score": score,
            "style": "保守" if score <= 1.0 else ("中庸" if score <= 2.5 else "进取"),
            "element_pref": answers["q2"],
            "leverage": answers["q3"] == "C",
            "xuan_pos": pos,
            "xuan_pos_name": POS_NAME[pos]}


# 本命合参：按五行旺衰点名七问之一为本命之策（问卷仓位与之合成专属曲线）
BIRTH_STRATEGY_RULE = {
    "旺": {"family": "sanhe", "wenyan": "命旺当令，乘旺而行，三合流年（与属{animal}三合之岁）满仓",
           "bai": "你的年命五行正得出生季节之势，状态最旺，谢知夏便取三合流年为你主打：合太岁之年才出手"},
    "相": {"family": "jieqi_all", "wenyan": "命相得势，应时而动，每个节气之后{window}日持仓",
           "bai": "你的五行受季节生扶、势头正盛，谢知夏便取节气轮动为你主打：跟着二十四节气择时"},
    "休": {"family": "almanac", "wenyan": "命休潜修，谨遵黄历，宜纳财开市之日方才持仓",
           "bai": "你的五行泄力于季节、宜静养潜修，谢知夏便取黄历择时为你主打：老黄历说宜才动"},
    "囚": {"family": "retro", "wenyan": "命囚受制，避其锋芒，水星逆行期间空仓观望",
           "bai": "你的五行被季节压住、行动受制，谢知夏便取水逆避险为你主打：天象不顺就按兵不动"},
    "死": {"family": "animal", "wenyan": "命死归藏，本命年避险，属{animal}之年空仓，其余满仓",
           "bai": "你的五行被季节所克、最宜归藏，谢知夏便取本命年避险为你主打：犯太岁之年以守为攻"},
}


def birth_strategy_rule(ws: str, prof: dict) -> dict:
    r = BIRTH_STRATEGY_RULE[ws]
    return {"family": r["family"],
            "wenyan": r["wenyan"].format(animal=prof.get("animal", ""),
                                         window=JIEQI_ALL_WINDOW),
            "bai": r["bai"]}




# ---------------------------------------------------------------- 历史人物 --
FIGURES = {
    "吕不韦": {"dyn": "战国", "tag": "杠杆奇货",
               "like": "奇货可居，把全部身家押给一个落魄质子，十年后做成秦国相邦，史上最成功的一笔杠杆投资",
               "bai_like": "吕不韦看中一个被冷落的王孙，把全部身家押上去赌他能当王，十年后赌成了，自己也做了丞相，这就是加杠杆赌一把的祖师爷",
               "fate": "结局：始皇亲政，被迫饮鸩。杠杆赢了十倍，输掉了性命",
               "bai_fate": "可惜新王一亲政就容不下他，最后被迫自尽，杠杆赢了十倍，最后连命都赔进去"},
    "刘备": {"dyn": "三国", "tag": "加仓摊薄",
             "like": "半生颠沛六易其主，屡败屡战越跌越买，六十岁才回本称帝",
             "bai_like": "刘备前半生屡战屡败、投奔过六家诸侯，但从不认输、一路坚持补仓，六十岁才终于翻身称帝，像极了浮亏加仓的股民",
             "fate": "结局：白帝托孤，摊到最后，也没摊回夷陵那一仓",
             "bai_fate": "晚年倾全国之力伐吴，夷陵一把亏光，白帝城托孤去世，最后一笔大仓位没能摊回来"},
    "万历": {"dyn": "明", "tag": "装死祖师",
             "like": "朱翊钧近三十年不上朝，大臣骂声充耳不闻，关灯吃面装死不动的祖师爷",
             "bai_like": "万历皇帝将近三十年不上朝，任凭大臣怎么骂都不理，持仓被套后关灯吃面、装死不动的祖师爷",
             "fate": "妙在躺平三十年，大明竟然还在",
             "bai_fate": "神奇的是他躺平的三十年里，明朝居然还在正常运转，装死有时候真扛得过去"},
    "范蠡": {"dyn": "春秋", "tag": "落袋为安",
             "like": "辅越灭吴后急流勇退，下海经商三致千金又三次散财，落袋为安的祖师，后世拜他做财神",
             "bai_like": "范蠡帮越王复国后立刻辞职下海经商，三次赚到千金又三次散掉，赚了就收、绝不贪多的祖师，后人把他当财神拜",
             "fate": "结局：泛舟五湖，善终成神",
             "bai_fate": "他带着家眷泛舟太湖，安享晚年，还被后世尊为财神，落袋为安者善终"},
    "项羽": {"dyn": "秦末", "tag": "割肉离场",
             "like": "垓下一败，无颜见江东父老，自刎乌江，宁可清零，绝不重来",
             "bai_like": "项羽垓下大败，觉得没脸回老家见乡亲，在乌江边自刎，一次大亏就把本金全割光，绝不给自己回本的机会",
             "fate": "夏某劝一句：留得本金在，不怕没行情",
             "bai_fate": "谢知夏劝一句：只要本金还在，将来总有翻身的机会，何必一把亏光"},
    "汉武帝": {"dyn": "西汉", "tag": "让利润奔跑",
               "like": "刘彻内兴功业外事四夷，一路加仓从不言退",
               "bai_like": "汉武帝一辈子对内对外连番大手笔投入，从不停手，像极了盈利后让利润奔跑、不断加码的打法",
               "fate": "晚年轮台罪己诏，史上最著名的一次止盈认错",
               "bai_fate": "晚年他下《轮台罪己诏》公开认错、收手休养，史上最著名的一次高位止盈"},
    "崇祯": {"dyn": "明", "tag": "频繁交易",
             "like": "朱由检勤政没错，错在频繁换将，换一任亏一任，越努力越亏",
             "bai_like": "崇祯皇帝又勤快又节俭，坏就坏在频繁换主帅，换一个败一个，越勤快亏得越快，正是频繁交易的通病",
             "fate": "结局：煤山收官。频繁交易，自古就是大忌",
             "bai_fate": "最后闯王破城，他在煤山自缢，频繁进出的账户，自古难有善终"},
    "司马懿": {"dyn": "三国", "tag": "长期主义",
               "like": "不出手则已，一熬熬死曹家三代，最后天下归晋",
               "bai_like": "司马懿不急着出手，装病蛰伏，硬是熬过了曹家三代人，最后天下归了司马家，长期主义的终极赢家",
               "fate": "结局：长期主义的终极赢家",
               "bai_fate": "拿得住的人，最后拿走了全部，他的耐心兑现了复利"},
    "白圭": {"dyn": "战国", "tag": "价值投资",
             "like": "人弃我取，人取我与，价值投资的祖师，早了巴菲特两千年",
             "bai_like": "白圭的名言是别人抛售我买入，别人抢购我卖出，比巴菲特早两千年的价值投资祖师",
             "fate": "结局：善经营而乐施，善终",
             "bai_fate": "他经营有道又乐善好施，安享晚年，逆向投资者的好结局"},
    "和珅": {"dyn": "清", "tag": "内幕消息",
             "like": "身在中枢消息灵通，买卖无往不利，家产折银八亿两",
             "bai_like": "和珅身居权力中枢，消息比谁都灵，靠信息差买卖无往不利，攒下八亿两银子的家产，靠内幕消息获利的典型",
             "fate": "结局：嘉庆一纸诏书全部抄没，内幕的尽头是铁窗",
             "bai_fate": "新皇帝一登基，一纸诏书把家产全部抄没，靠内幕赚的钱，最后连本带利吐出来"},
    "诸葛亮": {"dyn": "三国", "tag": "技术分析",
               "like": "夜观天象掐指算风，靠指标定大事，一生唯谨慎",
               "bai_like": "诸葛亮夜观天象、掐指算风借东风，靠技术指标决定大事，一生谨慎得像轻仓操作",
               "fate": "六出祁山方向都对，仓位太轻粮草跟不上",
               "bai_fate": "六次北伐大方向都看对了，可惜每次投入的兵力粮草都不够，方向对但仓位不足，赢也赢得有限"},
    "苏轼": {"dyn": "北宋", "tag": "随缘",
             "like": "被贬三次，每到一处先研究当地猪肉的做法，亏了也要好好吃饭",
             "bai_like": "苏东坡被贬官三次，每到一个地方先研究怎么把当地猪肉做好吃，账户亏了也照样把日子过好",
             "fate": "结局：一蓑烟雨任平生，心态史上第一",
             "bai_fate": "一蓑烟雨任平生，论投资心态，千古第一"},
    "唐太宗": {"dyn": "唐", "tag": "攻守平衡",
               "like": "李世民能听劝（纳谏止损），也能出手（玄武门毫不手软）",
               "bai_like": "唐太宗既能虚心接受批评、说改就改（及时止损），关键时又敢下重手（玄武门之变毫不迟疑），攻守兼备",
               "fate": "结局：贞观之治，平衡的开创者",
               "bai_fate": "贞观之治名垂青史，攻守平衡者，开创大局"},
    "汉文帝": {"dyn": "西汉", "tag": "守拙",
               "like": "刘恒无为而治轻徭薄赋，舍不得花一分钱，守拙真人版皇帝",
               "bai_like": "汉文帝信奉无为而治，能省就省、连修个露台都嫌贵，历史上把轻仓守拙做到极致的皇帝",
               "fate": "结局：文景之治，善终",
               "bai_fate": "他与儿子共同开创文景之治，国泰民安，守拙者，稳稳的幸福"},
    "王莽": {"dyn": "新", "tag": "激进改制",
             "like": "理想主义激进派，一口气改掉所有旧制度，动了所有人的仓位",
             "bai_like": "王莽是理想主义激进派，上台后一口气把旧制度全改掉，相当于一次性动了所有人的仓位，犯了众怒",
             "fate": "结局：被市场反噬，身死渐台",
             "bai_fate": "天下大乱，他死在渐台，市场用剧烈反弹告诉激进者什么叫反噬"},
    "秦始皇": {"dyn": "秦", "tag": "最强并购",
               "like": "并吞八荒，把七个市场并成一个，史上最强并购案",
               "bai_like": "秦始皇把战国七个市场并购成一个，史上最强也最激进的并购案",
               "fate": "结局：二世而亡，并购做成了，传承没做好",
               "bai_fate": "可惜秦朝二世而亡，并购做成了，接班人没选好，家业没能传下去"},
    "朱元璋": {"dyn": "明", "tag": "绝地复利",
               "like": "本金一只破碗，从底层一路做到天下第一，史上最强复利开局",
               "bai_like": "朱元璋的本金只有一只讨饭的破碗，最后做到了天下第一，史上最强复利开局",
               "fate": "结局：开局一只碗，结局一个国",
               "bai_fate": "起步一只碗，终点一个国，只要人还在、够努力，再小的本金也有奇迹"},
    "武则天": {"dyn": "唐", "tag": "逆势抄底",
               "like": "在最低谷（感业寺）坚定入场，一路做到董事长，逆势抄底的第一人",
               "bai_like": "武则天在人生最低谷（被送去感业寺当尼姑）时没有割肉离场，坚持等到机会回宫，一路做到皇帝，逆势抄底第一人",
               "fate": "结局：无字碑，功过留给市场评说",
               "bai_fate": "她给自己立了块无字碑，功过是非留给后人评说，真正的逆向投资者，不争一时口舌"},
    "霍去病": {"dyn": "西汉", "tag": "短线封神",
               "like": "封狼居胥，重仓快进快出，一战封侯",
               "bai_like": "霍去病十七岁率八百骑兵奔袭立功，封狼居胥，重仓出手、快进快出，一战成名的短线天才",
               "fate": "可惜天不假年，短线赢了名声，没等到复利",
               "bai_fate": "可惜二十三岁就病逝，短线赢下了名声，却没能活到享受复利的年纪"},
    "曹操": {"dyn": "东汉", "tag": "以小博大",
             "like": "挟天子以令诸侯，用最小仓位控制大盘权重股",
             "bai_like": "曹操把汉献帝攥在手里，用最小的仓位控制了最大的权重股，以小博大的控盘大师",
             "fate": "结局：至死不称帝，控盘不摘桃，仓位管理大师",
             "bai_fate": "他到死也不称帝，控制了盘面却不急着收割，仓位纪律堪称大师"},
    "张良": {"dyn": "西汉", "tag": "及时清仓",
             "like": "功成身退，从赤松子游，赚够了立刻清仓离场",
             "bai_like": "张良帮刘邦夺了天下，立刻交出股份、退隐修道，赚够了马上清仓离场的典范",
             "fate": "结局：保住本金也保住性命，汉初三杰唯一善终者",
             "bai_fate": "汉初三杰里只有他善终，会买是徒弟，会卖（离场）才是师父"},
    "萧何": {"dyn": "西汉", "tag": "后勤定投",
             "like": "战功最少，封赏第一，不追热点，稳稳定投后勤",
             "bai_like": "萧何不上前线抢战功，只默默管粮草后勤，最后论功行赏却排第一，不追热点、只做定投的稳健派",
             "fate": "结局：自污名节以自保，连风险控制都做满了",
             "bai_fate": "晚年故意自毁名声让皇帝放心，连功高震主这种尾部风险都提前对冲了"},
    "胡雪岩": {"dyn": "晚清", "tag": "红顶杠杆",
               "like": "红顶商人，钱庄生意加官家靠山，风生水起",
               "bai_like": "胡雪岩是红顶商人，生意搭上官家靠山，钱庄丝绸做得风生水起，资源和杠杆都用到了极致",
               "fate": "结局：靠山一倒，资金链断裂，抄家而终，单一依赖的风险",
               "bai_fate": "靠山倒台后资金链一夜断裂，被抄家而死，把宝全押在一根关系上的下场"},
    "沈万三": {"dyn": "元末明初", "tag": "不知收手",
               "like": "聚宝盆传说，家财万贯，仍要抢先替皇帝犒军",
               "bai_like": "传说沈万三有个聚宝盆，富可敌国，还想抢着替皇帝发军饷，赚了那么多仍不知收手",
               "fate": "结局：露富被忌，充军云南，风控缺失的下场",
               "bai_fate": "露富遭皇帝忌恨，全家充军云南，赚得多但不懂收，终究守不住"},
}


def compute_figure(answers: dict, q: dict, prof: dict) -> dict:
    """主匹配：问卷组合为主、生辰命理为辅，按优先级自上而下精确命中。

    命理参与点（与命帖联动，不再只看问卷）：
    - 属龙且进取 → 秦始皇（最强并购的气魄）
    - 命处死地仍让利润奔跑 → 武则天（谷底逆势持有）
    - 命处囚地而保守 → 司马懿（受制守成 熬字诀）
    """
    def pick(name):
        return {"name": name, **FIGURES[name]}

    ws = prof.get("_wang_shuai")

    if q["leverage"]:
        return pick("吕不韦")
    if answers["q1"] == "A":
        return pick("刘备")
    if answers["q1"] == "B":
        return pick("万历")
    if answers["q1"] == "C" and answers["q3"] == "A":
        return pick("范蠡")
    if answers["q1"] == "C":
        return pick("项羽")
    if answers["q3"] == "A":
        return pick("范蠡")
    if answers["q3"] == "B" and q["style"] == "进取":
        return pick("汉武帝")
    if answers["q5"] == "A":
        return pick("崇祯")
    if q["style"] == "保守" and (answers["q5"] == "C" or ws == "囚"):
        return pick("司马懿")
    if ws == "死" and answers["q3"] == "B":
        return pick("武则天")
    if prof["animal"] == "龙" and q["style"] == "进取":
        return pick("秦始皇")
    if answers["q4"] == "B":
        return pick("白圭")
    if answers["q4"] == "A":
        return pick("和珅")
    if answers["q4"] == "C":
        return pick("诸葛亮")
    if answers["q4"] == "D":
        return pick("苏轼")
    if q["style"] == "中庸":
        return pick("唐太宗")
    if q["style"] == "保守":
        return pick("汉文帝")
    return pick("王莽")


def figure_eggs(answers: dict, q: dict, prof: dict) -> list[dict]:
    """彩蛋旁证：条件叠加触发 0-2 位，与主匹配同页展示（前尘旁证）。"""
    eggs = []

    def hit(name):
        eggs.append({"name": name, **FIGURES[name]})

    if prof.get("_wang_shuai") == "死" and q["style"] == "进取":
        hit("朱元璋")
    if answers["q1"] == "A" and answers["q3"] == "B":
        hit("武则天")
    if q["style"] == "进取" and answers["q5"] == "A":
        hit("霍去病")
    if answers["q4"] == "A" and q["style"] == "进取":
        hit("曹操")
    if answers["q3"] == "A" and answers["q5"] == "D":
        hit("张良")
    if q["style"] == "保守" and answers["q4"] == "D":
        hit("萧何")
    if answers["q2"] == "金" and answers["q4"] == "A":
        hit("胡雪岩")
    if answers["q2"] == "金" and answers["q3"] == "B":
        hit("沈万三")
    return eggs

# ---------------------------------------------------------------- 称号 --
PREFIX_NAME = {"旺": "当令", "相": "得势", "休": "潜修", "囚": "受制", "死": "归藏"}
PREFIX_BAI = {
    "旺": "当令者旺，你的年命五行正是出生季节的主角，状态最旺，前缀当令",
    "相": "令生者相，出生季节的五行正生扶你的五行，得势有力，前缀得势",
    "休": "生令者休，你的五行忙着生养季节，泄了力气，宜静养，前缀潜修",
    "囚": "克令者囚，你的五行与季节相克，被压住难以施展，前缀受制",
    "死": "令克者死，季节的五行克住你的五行，状态最弱，宜藏不宜动，前缀归藏",
}
MAIN_TITLES = {
    ("进取", True): ("天选之韭", "自信满满地追高，被割得明明白白，似验项本是多重比较的错觉，客官却当真了",
                     "性格激进，又碰上一条看似灵验的说法，其实那只是试的次数多了撞上的假显著，当真了就要被割"),
    ("进取", False): ("孤勇散人", "命理无所凭，客官偏要满仓闯荡，是为孤勇",
                      "七问全不验，玄学帮不上忙，你却照样敢满仓冲锋，勇气可嘉，风险自负"),
    ("中庸", True): ("半仙之体", "似有一验，未敢全信，是为半仙",
                     "有一条名义上灵验，你没有全信也没有全不信，半信半疑，故称半仙"),
    ("中庸", False): ("随缘散人", "不验不恼，半仓随缘，心态可嘉",
                      "玄学全不验你也不恼，仓位留一半、心态放平，这样的状态反而最好"),
    ("保守", True): ("稳中带玄", "仓位谨慎，却信玄学，是为稳中带玄",
                     "钱袋子捂得紧，心里却还惦记着算命，仓位是理性的，念头是玄学的"),
    ("保守", False): ("守拙真人", "命理无依，唯仓位管理是真的",
                      "玄学一个都不灵，但你仓位控得好，真正的护身符不是生辰，是仓位"),
}


def compute_titles(prof, summary, q):
    el = prof["nayin_element"]
    ws = pf.wang_shuai(el, prof["birth_month"])
    season = pf.season_of(prof["birth_month"])
    prefix = PREFIX_NAME[ws]
    reasons = ["年命{0}属{1}，生于{2}季（{3}旺之时），五行处{4}地，故得前缀{5}".format(
        prof["nayin"], el, season, pf.SEASON_ELEMENT[season], ws, prefix)]
    reasons.append(PREFIX_BAI[ws])
    sig = summary["n_significant"] > 0
    main, main_r, main_bai = MAIN_TITLES[(q["style"], sig)]
    reasons.append("问卷风格{0}，七问{1}，故授主称号{2}：{3}".format(
        q["style"], "有似验项" if sig else "全无不验", main, main_r))
    reasons.append(main_bai)
    eggs = []
    if q["leverage"]:
        eggs.append(("杠杆仙人", "谢知夏苦劝：杠杆之下，神仙难救"))
    if q["element_pref"]:
        rel = pf.sheng_ke_relation(el, q["element_pref"])
        egg_map = {"我克（妻财）": ("偏财入手", "所选行业五行为年命所克，命书曰我克者为财"),
                   "克我（官杀）": ("迎难而上", "所选行业五行克年命，官杀压顶，客官偏选它"),
                   "生我（印绶）": ("顺风顺水郎", "所选行业五行生年命，如母护子"),
                   "比和": ("本命同行", "所选行业与年命同五行，并肩而行")}
        if rel in egg_map:
            eggs.append(egg_map[rel])
    if prof["birth_day"] == 29 and prof["birth_month"] == 2:
        eggs.append(("四载一逢客", "生辰四载一逢，稀客稀客"))
    if prof["animal"] == "羊":
        eggs.append(("辟谣锦羊", "属羊命苦一说统计已辟，客官自带辟谣体质"))
    if prof["animal"] == "龙" and q["style"] == "进取":
        eggs.append(("飞龙在天", "属龙又进取，飞龙在天，慎防亢龙有悔"))
    if prof["jieqi"]["name"] in ("冬至", "夏至"):
        eggs.append(("阴阳至人", "生于阴阳之至，天地气机转换之客"))
    if ws == "死" and q["style"] == "保守":
        eggs.append(("死地逢生", "命处死地，却选保守，以守为生"))
    if ws == "旺" and q["style"] == "进取":
        eggs.append(("烈火烹油", "当令又进取，烈火烹油之局，夏某劝稳"))
    if q["element_pref"] == "火" and q["style"] == "保守":
        eggs.append(("隔空对冲", "性子保守，偏爱烈火，精神对冲"))
    for name, r in eggs:
        reasons.append("彩蛋{0}：{1}".format(name, r))
    return {"prefix": prefix, "main": main, "eggs": [e[0] for e in eggs],
            "egg_reasons": eggs, "full": "{0}　{1}".format(prefix, main),
            "reasons": reasons, "wang_shuai": ws, "season": season,
            "prefix_bai": PREFIX_BAI[ws], "main_bai": main_bai}


# ---------------------------------------------------------------- 策略殿 --
POSITIONS = {"守拙": 0.25, "中庸": 0.50, "进取": 1.00}


def strategy_suite(mk):
    r = mk.ret[1:]
    m = mk.yi[1:]                                  # 黄历宜纳财开市日
    out = {"signal": "黄历宜纳财开市之日", "positions": {}, "bench": {}}
    step = max(1, len(r) // 600)

    def metrics(rr, curve):
        total = float(curve[-1])
        years = len(rr) / 242
        cagr = total ** (1 / years) - 1 if years > 0 and total > 0 else float("nan")
        peak = np.maximum.accumulate(curve)
        mdd = float(((curve - peak) / peak).min())
        vol = float(np.nanstd(rr, ddof=1) * np.sqrt(242))
        return {"total": round(total, 3), "cagr": round(cagr * 100, 2),
                "mdd": round(mdd * 100, 2), "vol": round(vol * 100, 2),
                "curve": [round(float(x), 4) for x in curve[::step]]}

    out["bench"] = metrics(r, np.cumprod(1 + r))
    for name, pos in POSITIONS.items():
        rr = np.where(m, r, 0.0) * pos
        out["positions"][name] = metrics(rr, np.cumprod(1 + rr))
    out["reverse"] = metrics(np.where(m, 0.0, r), np.cumprod(1 + np.where(m, 0.0, r)))
    out["reverse"].pop("curve", None)
    return out


# ------------------------------------------------ 行为策略（问卷答案→仓位规则） --
WS_RISK = {"旺": 1.15, "相": 1.05, "休": 1.0, "囚": 0.85, "死": 0.75}
Q5_COOLDOWN = {"A": 10, "B": 60, "C": 250, "D": 20}   # 数日 半年 三年 从不看盘


def behavior_strategy(mk: Market, answers: dict, ws: str, hold: np.ndarray = None) -> dict:
    """把问卷答案翻译成逐日仓位规则（状态机），模拟客官自己的操作。

    hold 为 None 时全程可持仓（策略殿的行为策略线）；
    传入掩码时仅在允许日执行（七问与本命合参的 玄学x行为 合体策略）：
    信号（生辰 命运）定何时被允许持仓，客官的规则定押多少 何时加减仓。
    初始仓位 = 第六答乘命格旺衰风偏（上限 1.0）
    浮亏一成（相对最近一次调仓基准）：q1=A 加仓半档（上限满仓） B 不动 C 清仓冷却
    浮盈两成：q3=A 落袋清仓冷却 B 让利润奔跑 C 加杠杆1.5倍（上限 2.0）
    冷却天数按第五答；q2 q4 不进仓位规则。
    """
    r = mk.ret
    pos0 = min(1.0, POS_OF_ANSWER[answers["q6"]] * WS_RISK[ws])
    cap = 2.0 if answers["q3"] == "C" else 1.0
    cd_of = Q5_COOLDOWN[answers["q5"]]
    pos, nav, cost, cooldown = pos0, 1.0, 1.0, 0
    curve = [1.0]
    for i in range(1, len(r)):
        ri = r[i]
        allowed = True if hold is None else bool(hold[i])
        if np.isnan(ri) or not allowed:
            curve.append(nav)
            continue
        if cooldown > 0:
            cooldown -= 1
            if cooldown == 0:
                pos, cost = pos0, nav
            curve.append(nav)
            continue
        nav *= 1 + pos * ri
        pl = nav / cost - 1
        if pl <= -0.10:
            if answers["q1"] == "A":
                pos = min(1.0, pos + 0.5)
                cost = nav
            elif answers["q1"] == "C":
                pos, cooldown, cost = 0.0, cd_of, nav
        elif pl >= 0.20:
            if answers["q3"] == "A":
                pos, cooldown, cost = 0.0, cd_of, nav
            elif answers["q3"] == "C":
                pos = min(cap, pos * 1.5)
                cost = nav
        curve.append(nav)
    q1t = {"A": "浮亏一成加仓半档", "B": "浮亏一成装死不动", "C": "浮亏一成割肉离场"}[answers["q1"]]
    q3t = {"A": "浮盈两成落袋为安", "B": "浮盈两成让利润奔跑", "C": "浮盈两成加杠杆五成（上限两倍）"}[answers["q3"]]
    cd_t = {"A": "离场十日再入场", "B": "离场六十日再入场", "C": "离场二百五十日再入场", "D": "离场二十日再入场"}[answers["q5"]]
    scope = "全程可持仓" if hold is None else "仅在信号允许之日持仓"
    rule = f"{q1t}，{q3t}，{cd_t}；初始仓位为第六答乘{WS_RISK[ws]:.2f}旺衰风偏（{ws}），{scope}，按此规则逐日模拟三十五年"
    step = max(1, len(curve) // 600)
    return {"total": round(float(curve[-1]), 3),
            "curve": [round(float(x), 4) for x in curve[::step]],
            "rule": rule, "pos0": round(pos0, 3)}


def strategy_stats_for_web(mk):
    r = mk.ret[1:]
    m = mk.yi[1:]
    out = {}

    def metrics(rr):
        curve = np.cumprod(1 + rr)
        peak = np.maximum.accumulate(curve)
        return {"total": round(float(curve[-1]), 3),
                "cagr": round((float(curve[-1]) ** (242 / len(rr)) - 1) * 100, 2),
                "mdd": round(float(((curve - peak) / peak).min()) * 100, 2),
                "vol": round(float(np.nanstd(rr, ddof=1) * np.sqrt(242)) * 100, 2)}

    entry = {}
    for name, pos in POSITIONS.items():
        entry[name] = metrics(np.where(m, r, 0.0) * pos)
    entry["反向"] = metrics(np.where(m, 0.0, r))
    out["yi"] = entry
    out["bench"] = metrics(r)
    return out


# ---------------------------------------------------------------- 行业帖 --
def sector_tests(mk):
    import csv
    path = DATA / "sector_indexes.csv"
    if not path.exists():
        return []
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    by_el = {}
    names = {}
    for r0 in rows:
        by_el.setdefault(r0["element"], {})[r0["date"]] = float(r0["close"])
        names[r0["element"]] = r0["name"]
    out = []
    for el, series in by_el.items():
        dates = sorted(series)
        if len(dates) < 1200:
            continue
        closes = np.array([series[d] for d in dates])
        ret = np.concatenate([[np.nan], closes[1:] / closes[:-1] - 1])
        lunar_el = []
        for d in dates:
            y, m0, dd = (int(x) for x in d.split("-"))
            lunar_el.append(pf.Calendar.nayin(mk.cal.solar_to_lunar(dt.date(y, m0, dd))[0])[-1])
        m = np.array([e == el for e in lunar_el])[1:]
        rr = ret[1:]
        a, b = rr[m], rr[~m]
        n1, n0 = len(a), len(b)
        if min(n1, n0) < 100:
            continue
        m1, m0v = float(a.mean()), float(b.mean())
        s1, s0 = float(a.std(ddof=1)), float(b.std(ddof=1))
        t = (m1 - m0v) / math.sqrt(s1 * s1 / n1 + s0 * s0 / n0)
        df = (s1 * s1 / n1 + s0 * s0 / n0) ** 2 / ((s1 * s1 / n1) ** 2 / (n1 - 1) + (s0 * s0 / n0) ** 2 / (n0 - 1))
        p = t_sf_two_sided(t, df)
        out.append({"element": el, "name": names[el], "start": dates[0], "end": dates[-1],
                    "n1": n1, "mean1_bp": round(m1 * 1e4, 2), "mean0_bp": round(m0v * 1e4, 2),
                    "t": round(t, 3), "p": round(p, 4),
                    "verdict": "似验" if p < P_CUTOFF else "不验"})
    return out


# ---------------------------------------------------------------- 汇总 --
def run_full(birthday: dt.date, answers_raw=None) -> dict:
    mk = Market()
    prof = pf.build_profile(birthday, mk.cal)
    answers = parse_answers(answers_raw)
    q = answers_info(answers)
    tests = personal_tests(mk, prof)
    attach_strategies(mk, tests, prof, answers=answers,
                      ws=pf.wang_shuai(prof["nayin_element"], prof["birth_month"]))
    scans = [scan_family(mk, f) for f in ["day", "jieqi", "month", "animal", "element",
                                          "jianchu", "moonphase"]]
    classic = classic_tests(mk)
    strategy = strategy_suite(mk)
    sectors = sector_tests(mk)
    titles = compute_titles(prof, {"n_significant": sum(1 for t in tests if t["verdict"] == "significant")}, q)
    strategy["behavior"] = behavior_strategy(mk, answers, titles["wang_shuai"])
    birth_rule = birth_strategy_rule(titles["wang_shuai"], prof)
    prof["_wang_shuai"] = titles["wang_shuai"]
    figure = compute_figure(answers, q, prof)
    figure_eggs_list = figure_eggs(answers, q, prof)
    prof.pop("_wang_shuai", None)
    n_sig = sum(1 for t in tests if t["verdict"] == "significant")
    return {
        "disclaimer": DISCLAIMER,
        "meta": {
            "index": "上证指数（000001.SH）收盘价",
            "start": mk.dates[0].isoformat(), "end": mk.dates[-1].isoformat(),
            "n_days": len(mk.dates),
            "method": "玄学组 vs 对照组 日均收益 Welch t 检验（双尾），显著性水平 5%",
            "min_n": MIN_N, "jieqi_window": JIEQI_WINDOW,
        },
        "profile": prof,
        "questionnaire": {"answers": answers, "info": q, "questions": QUESTIONNAIRE},
        "titles": titles,
        "birth_strategy": birth_rule,
        "figure": figure,
        "figure_eggs": figure_eggs_list,
        "strategy": strategy,
        "sectors": sectors,
        "tests": tests,
        "scans": scans,
        "classic": classic,
        "summary": {
            "n_tests": len(tests),
            "n_significant": n_sig,
            "n_null": sum(1 for t in tests if t["verdict"] == "null"),
            "n_insufficient": sum(1 for t in tests if t["verdict"] == "insufficient"),
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="玄学量化实验室 · 统计引擎（仅供研究使用）")
    ap.add_argument("--birthday", required=True, help="生日，如 2003-08-18")
    ap.add_argument("--json", help="把完整结果写入该 JSON 文件")
    ap.add_argument("--answers", default=None, help="问券答案，如 A,火,C（缺省取中庸默认）")
    args = ap.parse_args()

    b = dt.date.fromisoformat(args.birthday)
    result = run_full(b, args.answers)

    print(DISCLAIMER)
    print(f"\n生日 {b} 的命理档案：{result['profile']['constellation']} / "
          f"属{result['profile']['animal']} / {result['profile']['ganzhi']}年 "
          f"{result['profile']['nayin']} / 农历{result['profile']['lunar']['month']}月"
          f"{result['profile']['lunar']['day']} / 出生节气{result['profile']['jieqi']['name']}")
    print(f"数据：{result['meta']['start']} ~ {result['meta']['end']}，{result['meta']['n_days']} 个交易日\n")
    for t in result["tests"]:
        p = "—" if t["p"] is None else f"{t['p']:.3f}"
        print(f"[{t['verdict']:>12}] {t['title']:<22} 玄学组 {t['mean1_bp']:+.2f}bp/日 "
              f"vs 对照组 {t['mean0_bp']:+.2f}bp/日  t={t['t']:+.2f} p={p}  (n={t['n1']}/{t['n0']})")
    for s in result["scans"]:
        print(f"\n◆ 全扫描[{s['family']}] {s['m']} 个取值："
              f"名义显著 {s['n_sig_raw']} 个 {s['sig_raw']}；"
              f"Bonferroni 校正后存活 {s['n_sig_adj']} 个（纯碰运气期望 {s['expected_false_pos']} 个）")
    print()
    for t in result["classic"]:
        p = "—" if t["p"] is None else f"{t['p']:.3f}"
        print(f"[{t['verdict']:>12}] {t['title']:<24} t={t['t']:+.2f} p={p}")

    print()
    fig = result["figure"]
    print("人物：{0}（{1} · {2}），{3}；{4}".format(fig["name"], fig["dyn"], fig["tag"], fig["like"], fig["fate"]))
    if result["figure_eggs"]:
        print("旁证：{0}".format("、".join(e["name"] for e in result["figure_eggs"])))
    print("称号：{0}".format(result["titles"]["full"]) +
          ("（彩蛋：{0}）".format("、".join(result["titles"]["eggs"])) if result["titles"]["eggs"] else ""))
    print("策略殿（信号日 {0}）：一直持有终值 {1} vs ".format(result["strategy"]["signal"], result["strategy"]["bench"]["total"]) +
          " / ".join("{0} {1}".format(k, v["total"]) for k, v in result["strategy"]["positions"].items()))
    for sec in result["sectors"]:
        print("行业帖 {0}({1}) 五行年 {2:+.1f}bp vs 其余 {3:+.1f}bp t={4:+.2f} p={5:.3f} {6}".format(
            sec["name"], sec["element"], sec["mean1_bp"], sec["mean0_bp"], sec["t"], sec["p"], sec["verdict"]))
    if args.json:
        Path(args.json).write_text(json.dumps(result, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
        print(f"\n完整结果已写入 {args.json}")


if __name__ == "__main__":
    main()
