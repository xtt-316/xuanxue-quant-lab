# -*- coding: utf-8 -*-
"""生日 → 命理档案。

只读取 data/ 下的两张历法 CSV（calendar_events.csv / lunar_months.csv），
不依赖 sxtwl / lunardate，任何装了 Python3 的机器都能离线运行。

口径声明：
  * 生肖、纳音按【正月初一】为农历年分界（民间主流口径；另有"立春"口径，本工具予以注明）
  * 出生节气 = 生日当天或之前最近的一个节气
仅供研究使用：以统计学方法检验民间流传说法，旨在破除封建迷信、弘扬科学精神，
不构成任何投资建议。
"""
import csv
import datetime as dt
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"

ANIMALS = ["鼠", "牛", "虎", "兔", "龙", "蛇", "马", "羊", "猴", "鸡", "狗", "猪"]

# 六十甲子纳音（30 项，每项管相邻两年；天干地支从甲子起算）
NAYIN = ["海中金", "炉中火", "大林木", "路旁土", "剑锋金", "山头火", "涧下水", "城头土",
         "白蜡金", "杨柳木", "泉中水", "屋上土", "霹雳火", "松柏木", "长流水", "砂石金",
         "山下火", "平地木", "壁上土", "金箔金", "覆灯火", "天河水", "大驿土", "钗钏金",
         "桑柘木", "大溪水", "沙中土", "天上火", "石榴木", "大海水"]
GAN = ["甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬", "癸"]
ZHI = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"]

# 星座（月, 日）分界：起于当天
CONSTELLATIONS = [
    ((1, 20), "水瓶座"), ((2, 19), "双鱼座"), ((3, 21), "白羊座"), ((4, 20), "金牛座"),
    ((5, 21), "双子座"), ((6, 22), "巨蟹座"), ((7, 23), "狮子座"), ((8, 23), "处女座"),
    ((9, 23), "天秤座"), ((10, 24), "天蝎座"), ((11, 23), "射手座"), ((12, 22), "摩羯座"),
]


def constellation(month: int, day: int) -> str:
    """星座。摩羯座跨年（12.22-1.19）。"""
    md = (month, day)
    if md >= (12, 22) or md < (1, 20):
        return "摩羯座"
    current = "摩羯座"
    for (m, d), name in CONSTELLATIONS:
        if md >= (m, d):
            current = name
        else:
            break
    return current


class Calendar:
    """历法表：公历<->农历换算、节气查询（纯 CSV 驱动）。"""

    def __init__(self, data_dir: Path = DATA):
        # 农历月表按公历起始日排序，便于二分
        self.months = []      # (start: date, lunar_year, lunar_month, is_leap, length)
        with (data_dir / "lunar_months.csv").open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                self.months.append((dt.date.fromisoformat(r["start"]), int(r["lunar_year"]),
                                    int(r["lunar_month"]), int(r["is_leap"]), int(r["length"])))
        self.months.sort(key=lambda x: x[0])
        self._starts = [m[0] for m in self.months]

        self.jieqi = []       # (date, name) 升序
        self.cny = {}         # lunar_year -> date
        with (data_dir / "calendar_events.csv").open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r["type"] == "jieqi":
                    self.jieqi.append((dt.date.fromisoformat(r["date"]), r["name"]))
                else:
                    y, m, d = (int(x) for x in r["date"].split("-"))
                    # 春节所属农历年 = 该公历年的"下一个春节"减一年；直接记录，后面换算
                    self.cny[r["date"]] = dt.date(y, m, d)
        self.jieqi.sort()

    # ---------- 公历 -> 农历 ----------
    def solar_to_lunar(self, d: dt.date):
        """返回 (lunar_year, lunar_month, lunar_day, is_leap)；表外日期抛 ValueError。"""
        import bisect
        i = bisect.bisect_right(self._starts, d) - 1
        if i < 0:
            raise ValueError(f"日期超出历法表范围：{d}")
        start, ly, lm, leap, length = self.months[i]
        off = (d - start).days
        if off >= length:
            raise ValueError(f"日期落在历法表空隙：{d}")
        return ly, lm, off + 1, leap

    def lunar_year_of(self, d: dt.date) -> int:
        return self.solar_to_lunar(d)[0]

    # ---------- 农历 -> 公历 ----------
    def lunar_to_solar(self, ly: int, lm: int, ld: int, leap: int = 0):
        """该农历日不存在（如闰月缺失、大月三十）返回 None。"""
        for start, y, m, is_leap, length in self.months:
            if (y, m, is_leap) == (ly, lm, leap):
                return start + dt.timedelta(days=ld - 1) if ld <= length else None
        return None

    # ---------- 节气 ----------
    def governing_jieqi(self, d: dt.date):
        """生日当天或之前最近的节气 (date, name)；生日恰为节气日则就是它。"""
        import bisect
        dates = [j[0] for j in self.jieqi]
        i = bisect.bisect_right(dates, d) - 1
        if i < 0:
            raise ValueError("日期早于第一个节气")
        j_date, j_name = self.jieqi[i]
        return j_date, j_name, (d - j_date).days

    # ---------- 生肖 / 干支 / 纳音 ----------
    @staticmethod
    def animal(lunar_year: int) -> str:
        return ANIMALS[(lunar_year - 4) % 12]

    @staticmethod
    def ganzhi(lunar_year: int) -> str:
        return GAN[(lunar_year - 4) % 10] + ZHI[(lunar_year - 4) % 12]

    @staticmethod
    def nayin(lunar_year: int) -> str:
        return NAYIN[((lunar_year - 4) % 60) // 2]

    @staticmethod
    def nayin_element(nayin_name: str) -> str:
        return nayin_name[-1]


# ---------------------------------------------------------------- 五行规则 --
ELEMENTS = ["金", "木", "水", "火", "土"]
# 相生：金生水 水生木 木生火 火生土 土生金；相克：金克木 木克土 土克水 水克火 火克金
SHENG = {"金": "土", "木": "水", "水": "金", "火": "木", "土": "火"}      # 我 -> 生我者
SHENG_TO = {"金": "水", "木": "火", "水": "木", "火": "土", "土": "金"}  # 我 -> 我生者
KE = {"金": "火", "木": "金", "水": "土", "火": "水", "土": "木"}        # 我 -> 克我者
KE_TO = {"金": "木", "木": "土", "水": "火", "火": "金", "土": "水"}    # 我 -> 我克者

# 四季当令五行：春木 夏火 秋金 冬水（土旺于四季末，此处按主流简化取季月归土另计）
SEASON_ELEMENT = {"春": "木", "夏": "火", "秋": "金", "冬": "水"}
# 旺相休囚死：当令者旺 令生者相 生令者休 克令者囚 令克者死
WANG_SHUAI = ["旺", "相", "休", "囚", "死"]
WANG_PREFIX = {"旺": "当令", "相": "得势", "休": "潜修", "囚": "受制", "死": "归藏"}


def season_of(month: int) -> str:
    """公历月份 -> 四季（2-4春 5-7夏 8-10秋 11-1冬）。"""
    if 2 <= month <= 4:
        return "春"
    if 5 <= month <= 7:
        return "夏"
    if 8 <= month <= 10:
        return "秋"
    return "冬"


def wang_shuai(element: str, month: int) -> str:
    """年命五行在出生季节的旺衰（真规则：当令者旺 令生者相 生令者休 克令者囚 令克者死）。"""
    ling = SEASON_ELEMENT[season_of(month)]
    if element == ling:
        return "旺"
    if SHENG[element] == ling:      # 令生我
        return "相"
    if SHENG_TO[element] == ling:   # 我生令
        return "休"
    if KE[element] == ling:         # 令克我
        return "死"
    return "囚"                     # 我克令


def sheng_ke_relation(my_element: str, other_element: str) -> str:
    """问卷所选行业五行相对年命五行的生克（十神式命名）。"""
    if other_element == my_element:
        return "比和"
    if other_element == SHENG[my_element]:
        return "生我（印绶）"
    if other_element == SHENG_TO[my_element]:
        return "我生（食伤）"
    if other_element == KE[my_element]:
        return "克我（官杀）"
    return "我克（妻财）"


def build_profile(birthday: dt.date, cal: Calendar = None) -> dict:
    """生日 → 命理档案（民间说法所需的一切属性，仅供统计检验）。"""
    cal = cal or Calendar()
    ly, lm, ld, leap = cal.solar_to_lunar(birthday)
    jq_date, jq_name, jq_gap = cal.governing_jieqi(birthday)
    gz = cal.ganzhi(ly)
    ny = cal.nayin(ly)
    return {
        "birthday": birthday.isoformat(),
        "constellation": constellation(birthday.month, birthday.day),
        "birth_month": birthday.month,
        "birth_day": birthday.day,
        "lunar": {"year": ly, "month": lm, "day": ld, "is_leap": leap},
        "animal": cal.animal(ly),
        "ganzhi": gz,
        "nayin": ny,
        "nayin_element": cal.nayin_element(ny),
        "jieqi": {"name": jq_name, "date": jq_date.isoformat(), "days_after": jq_gap},
        "note": "生肖/纳音以正月初一为农历年分界（主流口径）；出生节气=生日当天或之前最近的节气。",
    }


if __name__ == "__main__":
    # ---- 边界自测 ----
    cal = Calendar()

    # 2003-08-18：狮子座 / 癸未羊年 / 杨柳木 / 农历七月二十（需验证）/ 立秋之后
    p = build_profile(dt.date(2003, 8, 18), cal)
    assert p["constellation"] == "狮子座", p
    assert p["animal"] == "羊" and p["ganzhi"] == "癸未" and p["nayin"] == "杨柳木", p
    assert p["jieqi"]["name"] == "立秋", p["jieqi"]

    # 春节分界：2024-02-09 属兔年（癸卯），2024-02-10 属龙年（甲辰）
    a = build_profile(dt.date(2024, 2, 9), cal)
    b = build_profile(dt.date(2024, 2, 10), cal)
    assert a["animal"] == "兔" and a["ganzhi"] == "癸卯", a
    assert b["animal"] == "龙" and b["ganzhi"] == "甲辰", b

    # 闰月往返：2023 有闰二月，2023-04-19 应为闰二月初一
    s = cal.lunar_to_solar(2023, 2, 1, leap=1)
    assert s == dt.date(2023, 3, 22), s
    assert cal.solar_to_lunar(dt.date(2023, 3, 22)) == (2023, 2, 1, 1)

    # 大年三十不存在时 lunar_to_solar 返回 None（找一个小月腊月：2026 农历腊月？改为通例测试）
    # 2月29日生日可用
    p229 = build_profile(dt.date(2004, 2, 29), cal)
    assert p229["constellation"] == "双鱼座", p229

    # 纳音五行抽查：1984 甲子海中金；1993 癸酉剑锋金；2019 己亥平地木
    assert cal.nayin(1984) == "海中金" and cal.nayin(1993) == "剑锋金" and cal.nayin(2019) == "平地木"

    # 五行规则自测：火命生于夏=旺；木命生于秋（金旺克木）=死；水命生于冬=旺
    assert wang_shuai("火", 6) == "旺" and wang_shuai("木", 9) == "死" and wang_shuai("水", 12) == "旺"
    assert wang_shuai("金", 6) == "死" and wang_shuai("土", 3) == "死"   # 令克者死
    assert wang_shuai("木", 12) == "相" and wang_shuai("金", 12) == "休"  # 令生者相 生令者休
    print("profile.py 自测全部通过 ✓")
    print("示例档案 2003-08-18 →")
    import json
    print(json.dumps(p, ensure_ascii=False, indent=2))
