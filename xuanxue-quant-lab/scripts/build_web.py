# -*- coding: utf-8 -*-
"""构建互动网页 web/index.html，并为 skill 提供单人报告渲染。

古风宣纸主题 + 乙女式三幕对话剧场（七问快斩 互动问券 策略殿 称号图鉴 遍试诸日）。
两个入口、同一引擎：互动页统计量全部预计算嵌入，JS 只查表与重建掩码画曲线。
本项目以统计学方法检验民间流传说法，坚持弘扬科学精神，不构成任何投资建议。
"""
from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

import lab
import profile as pf

ROOT = Path(__file__).resolve().parent.parent.parent
WEB = ROOT / "web"
EPOCH = dt.date(1899, 12, 31)

FAMILIES = ["day", "jieqi", "month", "animal", "element", "jianchu", "moonphase"]
JIEQI_ORDER = ["冬至", "小寒", "大寒", "立春", "雨水", "惊蛰", "春分", "清明", "谷雨",
               "立夏", "小满", "芒种", "夏至", "小暑", "大暑", "立秋", "处暑", "白露",
               "秋分", "寒露", "霜降", "立冬", "小雪", "大雪"]
# 坊间七问（前三问全市场通行，本命年 三合与生肖挂钩；旧七问族保留供静态卷宗墙使用）
Q7_ORIGINS = {
    "almanac": ("坊间原版：老黄历择日传统，每日建除十二神定宜忌，宜纳财 开市 交易 立券，方能动财",
                "这就是翻黄历看宜字炒股，市面上最正统的择日法，持仓约占三分之一交易日"),
    "retro": ("坊间原版：当代占星水逆论，每年三到四次，每次约三周，星象 App 皆言此间勿做重大决定",
              "水逆不炒股是星座玄学的顶流玩法，天文算法逐日算出 1990 年以来全部水逆期再检验"),
    "moon": ("坊间原版：月相交易法 Lunar Cycle，券商研报亦写过满月效应，新月至上弦下注 满月后收手",
             "跟着月亮做，月亮从新月长到满月的约半个月里持有，其余空仓"),
    "jieqi_all": ("坊间原版：股民圈节气变盘论，江恩理论亦重节气时间窗，二十四节气皆为时间之窗",
                  "一年二十四个节气，每个节气之后的几天都满仓，看节气是不是真带来行情"),
    "digit": ("坊间原版：市井数字禁忌，谐音定吉凶，楼层车牌挑八避四，炒股亦然",
              "检验每月 4 14 24 号与其余日子；逢八满仓的终值附在卡后双向对照"),
}


def precompute(mk: lab.Market) -> dict:
    out: dict[str, dict] = {}

    def fam(name, entries):
        out[name] = {k: _stat_entry(mk, name, t, c, m) for k, t, c, m in entries}

    # ---- 坊间七问 ----
    def q7(key, title, claim, mask):
        o, ob = Q7_ORIGINS.get(key, (None, None))
        e = lab.run_test(mk, key, title, claim, mask, origin=o, origin_bai=ob)
        e.pop("strat_curve", None)
        e.pop("bench_curve", None)
        return e

    out["almanac"] = {"yi": q7("almanac", "坊间七问 其一 黄历宜忌",
                               "民间说法：黄历宜纳财开市之日行情更旺，宜日动仓凶日不动",
                               lab.mask_almanac_yi(mk))}
    out["retro"] = {"r": q7("retro", "坊间七问 其二 水星逆行",
                            "民间说法：水星逆行期间诸事不顺，不宜签约交易，宜空仓观望",
                            lab.mask_mercury_retro(mk))}
    out["moon"] = {"w": q7("moon", "坊间七问 其三 满月效应",
                           "民间说法：新月渐盈行情渐旺，满月之后由盈转亏，买新月 卖满月",
                           lab.mask_moon_waxing(mk))}
    fam("animal", [
        (a, f"坊间七问 其四 本命年避险 属{a}", f"民间主流说法：属{a}之人本命年犯太岁 宜守不宜攻 不宜重仓搏杀",
         lab.mask_animal(mk, a)) for a in pf.ANIMALS])
    out["jieqi_all"] = {"a": q7("jieqi_all", "坊间七问 其五 节气变盘",
                                f"民间说法：节气前后市场易变盘，节气后{lab.JIEQI_ALL_WINDOW}日行情启动",
                                lab.mask_jieqi_all(mk))}
    out["digit"] = {"d4": q7("digit", "坊间七问 其六 数字禁忌 逢四",
                             "市井说法：四谐音死 逢四不发（4 14 24 号勿动）；八谐音发 逢八必发（8 18 28 号宜买）",
                             lab.mask_digit(mk, 4))}
    fam("sanhe", [
        (a, f"坊间七问 其七 三合流年 属{a}", f"命理说法：与属{a}三合之年运势顺遂（合太岁），宜重仓",
         lab.mask_sanhe(mk, a)) for a in pf.ANIMALS])

    # ---- 旧七问族（静态卷宗 p 值墙与典籍对照保留） ----
    fam("sign", [
        (s, f"命理旧问 星座月 {s}", f"民间说法：{s}的月份大盘更容易涨", lab.mask_sign(mk, s))
        for s in ["水瓶座", "双鱼座", "白羊座", "金牛座", "双子座", "巨蟹座",
                  "狮子座", "处女座", "天秤座", "天蝎座", "射手座", "摩羯座"]])
    fam("month", [
        (str(m), f"命理旧问 生日月 {m}月", "民间说法：每年你出生的那个月，大盘胜率更高",
         lab.mask_month(mk, m)) for m in range(1, 13)])
    fam("day", [
        (str(d), f"命理旧问 幸运日 每月{d}号",
         "民间说法：你出生的日号每月都会重演，那天是你的幸运日",
         lab.mask_day(mk, d)) for d in range(1, 32)])
    fam("jieqi", [
        (n, f"命理旧问 出生节气 {n}", f"民间说法：{n}之后 {lab.JIEQI_WINDOW} 天内大盘更容易涨",
         lab.mask_jieqi(mk, n)) for n in JIEQI_ORDER])
    fam("element", [
        (e, f"命理旧问 年命五行 {e}命", f"民间说法：与你年命纳音同五行的年份（{e}年）市场更顺",
         lab.mask_element(mk, e)) for e in ["金", "木", "水", "火", "土"]])
    out["lunar"] = {}
    for lm in range(1, 13):
        for ld in range(1, 31):
            out["lunar"][f"{lm}-{ld}"] = _stat_entry(
                mk, "lunar", f"命理旧问 农历生日 每年农历{lm}月{ld}",
                "民间说法：每年农历生日那天，大盘会给你发红包",
                lab.mask_lunar_birthday(mk, lm, ld, 0))
    out["classic"] = {
        k: _stat_entry(mk, k, t, c, m) for k, t, c, m in [
            ("tom", "典籍对照 月末月初效应",
             "学术文献里的真日历效应：每月前3个+最后1个交易日", lab.mask_turn_of_month(mk)),
            ("precny", "典籍对照 春节前行情",
             "民间与券商都爱说的：春节前5个交易日行情偏暖", lab.mask_pre_cny(mk, 5)),
            *[(f"wd{i}", f"典籍对照 星期效应 {n}", f"民间说法：{n}的大盘有固定脾气", mk.weekday == i)
              for i, n in enumerate(lab.WEEKDAY_NAMES)],
        ]}
    return out

TITLE = "生辰算股"
SUBTITLE = "谢知夏的统计学算命铺"


# ================================================================ 预计算 ==
def _stat_entry(mk: lab.Market, key: str, title: str, claim: str, mask: np.ndarray) -> dict:
    e = lab.run_test(mk, key, title, claim, mask)
    e.pop("strat_curve", None)
    e.pop("bench_curve", None)
    return e


def titles_data() -> dict:
    """称号规则表（网页 JS 与 Python 同源，避免两套文案）。"""
    return {
        "prefixOrder": ["旺", "相", "休", "囚", "死"],
        "prefixName": lab.PREFIX_NAME,
        "prefixBai": lab.PREFIX_BAI,
        "main": {f"{k[0]}|{1 if k[1] else 0}": v for k, v in lab.MAIN_TITLES.items()},
        "questionnaire": lab.QUESTIONNAIRE,
        "figures": lab.FIGURES,
        "posOfAnswer": lab.POS_OF_ANSWER,
        "posName": {str(k): v for k, v in lab.POS_NAME.items()},
        "birthRule": lab.BIRTH_STRATEGY_RULE,
    }


def _strat_tpl_js() -> str:
    """由 lab.STRATEGY_TEMPLATES 单源生成网页端策略文案函数。

    v5 模板占位符：{animal} 取命帖生肖，{window} 内联节气窗口天数。
    生成结果若仍残留 {xx} 占位符，构建直接报错，防止漏到页面。
    """
    expr_of = {"animal": "p.animal"}
    parts = []
    for key, tpl in lab.STRATEGY_TEMPLATES.items():
        js = tpl.replace("{window}", str(lab.JIEQI_ALL_WINDOW))
        for field, expr in expr_of.items():
            js = js.replace("{" + field + "}", '"+' + expr + '+"')
        leftover = re.findall(r"\{[a-z_]+\}", js)
        if leftover:
            raise SystemExit(f"STRAT_TPL 占位符未替换 {key}: {leftover}")
        parts.append(f'{key}:(p)=>"{js}"')
    return "const STRAT_TPL={" + ",".join(parts) + "};"


def day_meta(mk: lab.Market) -> dict:
    return {
        "dates": [d.isoformat() for d in mk.dates],
        "month": [int(x) for x in mk.month],
        "day": [int(x) for x in mk.day],
        "weekday": [int(x) for x in mk.weekday],
        "lunarYear": [int(x) for x in mk.lunar_year],
        "ret": [None if np.isnan(x) else round(float(x), 6) for x in mk.ret],
        "jd": [int(x) for x in mk.jd],
        "jieqiDays": {k: [int(v) for v in vs] for k, vs in mk.jieqi_days.items()},
        "cnyDays": [(d0 - EPOCH).days for d0 in mk.cal.cny.values()],
        "lunarMonths": [[(m[0] - EPOCH).days, m[1], m[2], m[3], m[4]] for m in mk.cal.months],
        "first3": [bool(x) for x in mk.first3],
        "last1": [bool(x) for x in mk.last1],
        # 坊间玄学（构建期黄历/天文计算结果，JS 只查表不做天文计算）
        "yi": [1 if x else 0 for x in mk.yi],
        "retro": [1 if x else 0 for x in mk.retro],
        "moonAge": [None if np.isnan(x) else round(float(x), 1) for x in mk.moon_age],
        "jianchu": [int(x) for x in mk.jianchu],
    }


# ================================================================ JS 核心 ==
CORE_JS = r"""
const ANIMALS=["鼠","牛","虎","兔","龙","蛇","马","羊","猴","鸡","狗","猪"];
const GAN=["甲","乙","丙","丁","戊","己","庚","辛","壬","癸"];
const ZHI=["子","丑","寅","卯","辰","巳","午","未","申","酉","戌","亥"];
const NAYIN=["海中金","炉中火","大林木","路旁土","剑锋金","山头火","涧下水","城头土","白蜡金","杨柳木","泉中水","屋上土","霹雳火","松柏木","长流水","砂石金","山下火","平地木","壁上土","金箔金","覆灯火","天河水","大驿土","钗钏金","桑柘木","大溪水","沙中土","天上火","石榴木","大海水"];
const CONST_START=[[1,20,"水瓶座"],[2,19,"双鱼座"],[3,21,"白羊座"],[4,20,"金牛座"],[5,21,"双子座"],[6,22,"巨蟹座"],[7,23,"狮子座"],[8,23,"处女座"],[9,23,"天秤座"],[10,24,"天蝎座"],[11,23,"射手座"],[12,22,"摩羯座"]];
const CONST_END={"摩羯座":[1,19],"水瓶座":[2,18],"双鱼座":[3,20],"白羊座":[4,19],"金牛座":[5,20],"双子座":[6,21],"巨蟹座":[7,22],"狮子座":[8,22],"处女座":[9,22],"天秤座":[10,23],"天蝎座":[11,22],"射手座":[12,21]};
const SHENG={"金":"土","木":"水","水":"金","火":"木","土":"火"};
const SHENG_TO={"金":"水","木":"火","水":"木","火":"土","土":"金"};
const KE={"金":"火","木":"金","水":"土","火":"水","土":"木"};
const KE_TO={"金":"木","木":"土","水":"火","火":"金","土":"水"};
const SEASON_ELEMENT={"春":"木","夏":"火","秋":"金","冬":"水"};

function constellation(m,d){const md=m*100+d;if(md>=1222||md<120)return"摩羯座";let cur="摩羯座";for(const[sm,sd,name]of CONST_START){if(md>=sm*100+sd)cur=name;else break;}return cur;}
function seasonOf(m){return(m>=2&&m<=4)?"春":((m>=5&&m<=7)?"夏":((m>=8&&m<=10)?"秋":"冬"));}
function wangShuai(el,m){const ling=SEASON_ELEMENT[seasonOf(m)];
 if(el===ling)return"旺"; if(SHENG[el]===ling)return"相";
 if(SHENG_TO[el]===ling)return"休"; if(KE[el]===ling)return"死"; return"囚";}
function shengKe(my,other){if(other===my)return"比和";if(other===SHENG[my])return"生我";
 if(other===SHENG_TO[my])return"我生";if(other===KE[my])return"克我";return"我克";}

let D=null;
function setMeta(meta){D=meta;D._lmStart=D.lunarMonths.map(r=>r[0]);}

function solarToLunar(jd){
  let lo=0,hi=D._lmStart.length-1,i=-1;
  while(lo<=hi){const mid=(lo+hi)>>1;if(D._lmStart[mid]<=jd){i=mid;lo=mid+1;}else hi=mid-1;}
  if(i<0)return null;
  const[s,ly,lm,leap,len]=D.lunarMonths[i];const off=jd-s;
  if(off>=len)return null;return[ly,lm,off+1,leap];
}
function lunarToSolar(ly,lm,ld,leap){
  for(const[s,y,m,lp,len]of D.lunarMonths)if(y===ly&&m===lm&&lp===(leap||0))return ld<=len?s+ld-1:null;
  return null;
}
function ganzhi(ly){return GAN[(ly-4)%10]+ZHI[(ly-4)%12];}
function nayin(ly){return NAYIN[((ly-4)%60)>>1];}
function animal(ly){return ANIMALS[(ly-4)%12];}
function elementOf(n){return n[n.length-1];}
function governingJieqi(jd){
  let best=null;
  for(const name in D.jieqiDays){for(const d of D.jieqiDays[name]){if(d<=jd&&(!best||d>best[1]))best=[name,d];}}
  return best?[best[0],best[1],jd-best[1]]:null;
}
function buildProfile(jd){
  const iso=new Date((jd-25568)*86400000).toISOString().slice(0,10);
  const[mth,dd]=iso.slice(5,10).split("-").map(Number);
  const lun=solarToLunar(jd);const jq=governingJieqi(jd);const ny=nayin(lun[0]);
  return{jd:jd,birthday:iso,constellation:constellation(mth,dd),birth_month:mth,birth_day:dd,
    lunar:{year:lun[0],month:lun[1],day:lun[2],is_leap:lun[3]},animal:animal(lun[0]),
    ganzhi:ganzhi(lun[0]),nayin:ny,nayin_element:elementOf(ny),
    jieqi:{name:jq[0],days_after:jq[2]},
    note:"生肖 纳音以正月初一为农历年分界（主流口径） 出生节气为生日当天或之前最近的节气"};
}

function mkMask(fn){const out=new Array(D.jd.length).fill(false);for(let i=0;i<D.jd.length;i++)out[i]=fn(i);return out;}
function maskSign(sign){const s=CONST_START.find(r=>r[2]===sign),e=CONST_END[sign];
  return mkMask(i=>{const md=D.month[i]*100+D.day[i];const sv=s[0]*100+s[1],ev=e[0]*100+e[1];
    return sv<=ev?(md>=sv&&md<=ev):(md>=sv||md<=ev);});}
function maskMonth(m){return mkMask(i=>D.month[i]===m);}
function maskDay(d){return mkMask(i=>D.day[i]===d);}
function maskAnimal(a){const idx=ANIMALS.indexOf(a);return mkMask(i=>(D.lunarYear[i]-4)%12===idx);}
function maskElement(el){return mkMask(i=>elementOf(nayin(D.lunarYear[i]))===el);}
function maskJieqi(name,window){window=window||15;const days=D.jieqiDays[name]||[];
  return mkMask(i=>{const j=D.jd[i];for(const s of days)if(j>=s&&j<s+window)return true;return false;});}
function maskLunarBirthday(lm,ld){const hit=new Array(D.jd.length).fill(false);
  const years=[...new Set(D.lunarYear)];
  for(const y of years){const s=lunarToSolar(y,lm,ld,0);if(s==null)continue;
    for(let i=0;i<D.jd.length;i++)if(D.jd[i]===s)hit[i]=true;}
  return hit;}
function maskTOM(){return mkMask(i=>D.first3[i]||D.last1[i]);}
function maskPreCny(k){k=k||5;
  const hit=new Array(D.jd.length).fill(false);
  for(const c of D.cnyDays){const idx=[];for(let i=0;i<D.jd.length;i++)if(D.jd[i]<c)idx.push(i);
    for(let j=Math.max(0,idx.length-k);j<idx.length;j++)hit[idx[j]]=true;}
  return hit;}
/* ---- 坊间玄学掩码（数据由构建期黄历/天文计算嵌入，此处只查表） ---- */
const JIANCHU=["建","除","满","平","定","执","破","危","成","收","开","闭"];
const SANHE_GROUPS=[["鼠","龙","猴"],["牛","蛇","鸡"],["虎","马","狗"],["兔","羊","猪"]];
function maskYi(){return mkMask(i=>D.yi[i]===1);}
function maskRetro(){return mkMask(i=>D.retro[i]===1);}
function maskWaxing(){return mkMask(i=>D.moonAge[i]!=null&&D.moonAge[i]<14.765);}
function maskJianchu(jc){const x=JIANCHU.indexOf(jc);return mkMask(i=>D.jianchu[i]===x);}
function maskJieqiAll(win){win=win||5;const days=[];
  for(const name in D.jieqiDays)for(const d of D.jieqiDays[name])days.push(d);
  days.sort((a,b)=>a-b);
  return mkMask(i=>{const j=D.jd[i];for(const s of days)if(j>=s&&j<s+win)return true;return false;});}
function maskDigit(dg){return mkMask(i=>D.day[i]%10===dg||Math.floor(D.day[i]/10)===dg);}
function sanheOf(animal){for(const g of SANHE_GROUPS)if(g.includes(animal))return g;return[animal];}
function maskSanhe(animal){const grp=sanheOf(animal);
  return mkMask(i=>grp.includes(ANIMALS[(D.lunarYear[i]-4)%12]));}
function curve(mask){
  const strat=[1],bench=[1];let s=1,b=1;
  for(let i=1;i<D.ret.length;i++){const r=D.ret[i];if(r==null){strat.push(s);bench.push(b);continue;}
    if(mask[i])s*=1+r;b*=1+r;strat.push(s);bench.push(b);}
  return[strat,bench];}
function curvePos(mask,pos){
  const out=[1];let s=1;
  for(let i=1;i<D.ret.length;i++){const r=D.ret[i];if(r==null){out.push(s);continue;}
    if(mask[i])s*=1+r*pos;out.push(s);}
  return out;}
function curveReverse(mask){
  const out=[1];let s=1;
  for(let i=1;i<D.ret.length;i++){const r=D.ret[i];if(r==null){out.push(s);continue;}
    if(!mask[i])s*=1+r;out.push(s);}
  return out;}
function downsample(arr,n){n=n||600;const step=Math.max(1,Math.floor(arr.length/n));const out=[];
  for(let i=0;i<arr.length;i+=step)out.push(Math.round(arr[i]*1e4)/1e4);out.push(Math.round(arr[arr.length-1]*1e4)/1e4);return out;}
/* ---- 行为策略（问卷答案→仓位规则状态机，与 lab.behavior_strategy 逐日一致） ---- */
const WS_RISK={"旺":1.15,"相":1.05,"休":1.0,"囚":0.85,"死":0.75};
const Q5_COOLDOWN={"A":10,"B":60,"C":250,"D":20};
function curveBehavior(an,ws,hold){
  const pos0=Math.min(1.0,TDATA.posOfAnswer[an.q6]*WS_RISK[ws]);
  const cap=an.q3==="C"?2.0:1.0;
  const cdOf=Q5_COOLDOWN[an.q5];
  let pos=pos0,nav=1,cost=1,cd=0;
  const out=[1];
  for(let i=1;i<D.ret.length;i++){
    const r=D.ret[i];
    const allowed=hold?hold[i]:true;
    if(r==null||!allowed){out.push(nav);continue;}
    if(cd>0){cd--;if(cd===0){pos=pos0;cost=nav;}out.push(nav);continue;}
    nav*=1+pos*r;
    const pl=nav/cost-1;
    if(pl<=-0.10){
      if(an.q1==="A"){pos=Math.min(1.0,pos+0.5);cost=nav;}
      else if(an.q1==="C"){pos=0;cd=cdOf;cost=nav;}}
    else if(pl>=0.20){
      if(an.q3==="A"){pos=0;cd=cdOf;cost=nav;}
      else if(an.q3==="C"){pos=Math.min(cap,pos*1.5);cost=nav;}}
    out.push(nav);}
  return {curve:out,total:out[out.length-1],pos0:pos0};}
function behaviorRuleText(an,ws){
  const q1t={A:"浮亏一成加仓半档",B:"浮亏一成装死不动",C:"浮亏一成割肉离场"}[an.q1];
  const q3t={A:"浮盈两成落袋为安",B:"浮盈两成让利润奔跑",C:"浮盈两成加杠杆五成（上限两倍）"}[an.q3];
  const cdt={A:"离场十日再入场",B:"离场六十日再入场",C:"离场二百五十日再入场",D:"离场二十日再入场"}[an.q5];
  return q1t+"，"+q3t+"，"+cdt+"；初始仓位为第六答乘"+WS_RISK[ws].toFixed(2)+"旺衰风偏（"+ws+"），按此规则逐日模拟三十五年";}

function personalMasksAndKeys(p){
  return[
    ["almanac","坊间七问 其一 黄历宜忌",maskYi()],
    ["retro","坊间七问 其二 水星逆行",maskRetro()],
    ["moon","坊间七问 其三 满月效应",maskWaxing()],
    ["animal","坊间七问 其四 本命年避险 属"+p.animal,maskAnimal(p.animal)],
    ["jieqi_all","坊间七问 其五 节气变盘",maskJieqiAll(5)],
    ["digit","坊间七问 其六 数字禁忌 逢四",maskDigit(4)],
    ["sanhe","坊间七问 其七 三合流年 属"+p.animal,maskSanhe(p.animal)]];}
"""


# ================================================================ 样式 ==
def _corner_uri(rot: int) -> str:
    svg = ("<svg xmlns='http://www.w3.org/2000/svg' width='16' height='16'>"
           f"<g transform='rotate({rot} 8 8)' fill='none' stroke='#5b6b70' stroke-opacity='.5' stroke-width='1.4'>"
           "<path d='M1.5 15 V1.5 H15'/><path d='M5.5 15 V5.5 H15' stroke-opacity='.32'/></g></svg>")
    return "data:image/svg+xml," + svg.replace("#", "%23").replace("<", "%3C").replace(">", "%3E").replace("'", "%27").replace(" ", "%20")


def _css() -> str:
    css = """
:root{--paper:#f4edda;--paper2:#ece1c4;--ink:#2f2a26;--ink2:#6f6353;--verm:#c23b2e;
--zhu:#5a7a6e;--qing:#3d4a52;--card:#faf5e6;--line:#d8cba8;--faint:#e7ddc2;
--ft-kai:"KaiTi","STKaiti","BiauKai","DFKai-SB",serif;
--ft-song:"KaiTi","STKaiti","BiauKai","DFKai-SB",serif;}
*{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
body{background:var(--paper);color:var(--ink);font-family:var(--ft-song);
line-height:1.9;font-size:15px;padding-bottom:150px;position:relative}
body::before{content:"";position:fixed;inset:0;pointer-events:none;z-index:0;opacity:.55;
mix-blend-mode:multiply;
background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='260' height='260'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2' seed='11'/%3E%3CfeColorMatrix values='0 0 0 0 0.62 0 0 0 0 0.56 0 0 0 0 0.46 0 0 0 0.05 0'/%3E%3C/filter%3E%3Crect width='260' height='260' filter='url(%23n)'/%3E%3C/svg%3E")}
body::after{content:"";position:fixed;inset:0;pointer-events:none;z-index:0;
background:radial-gradient(120% 90% at 50% 40%,transparent 60%,rgba(120,100,60,.10) 100%)}
.wrap{max-width:960px;margin:0 auto;padding:0 22px;position:relative;z-index:1}
a{color:var(--verm)}
header{position:relative;text-align:center;padding:46px 0 26px;border-bottom:1px solid var(--line);margin-bottom:8px}
header::after{content:"";position:absolute;left:0;right:0;bottom:-1px;height:54px;pointer-events:none;opacity:.42;
background:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='170' height='54'%3E%3Cg fill='none' stroke='%23b9a878' stroke-width='1.6' stroke-linecap='round'%3E%3Cpath d='M14 42 q-11 -17 8 -24 q15 -5 20 8 q3 9 -6 12 q-8 2 -10 -5 q-2 -8 7 -9'/%3E%3Cpath d='M44 44 q30 -7 96 -3'/%3E%3C/g%3E%3C/svg%3E") left 12px bottom 2px/auto 52px no-repeat,
url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='170' height='54'%3E%3Cg fill='none' stroke='%23b9a878' stroke-width='1.6' stroke-linecap='round'%3E%3Cpath d='M156 42 q11 -17 -8 -24 q-15 -5 -20 8 q-3 9 6 12 q8 2 10 -5 q2 -8 -7 -9'/%3E%3Cpath d='M126 44 q-30 -7 -96 -3'/%3E%3C/g%3E%3C/svg%3E") right 12px bottom 2px/auto 52px no-repeat}
header .brand{display:flex;align-items:center;justify-content:center;gap:22px;position:relative;z-index:2}
h1.site{font-family:var(--ft-kai);font-size:44px;letter-spacing:14px;text-indent:14px;color:var(--ink);font-weight:700;position:relative}
h1.site::after{content:"";position:absolute;left:6px;right:-8px;bottom:6px;height:10px;
background:rgba(194,59,46,.12);z-index:-1;transform:skewX(-8deg)}
.seal{display:inline-flex;align-items:center;justify-content:center;flex-direction:column;
color:#f8f0dc;font-family:var(--ft-kai);font-weight:700;line-height:1.05;
border-radius:7px 9px 6px 8px;transform:rotate(-4deg);
background:radial-gradient(ellipse at 40% 34%,#cf4638,#b73326 62%,#9c2a1f);
box-shadow:inset 0 0 0 2px rgba(248,240,220,.9),inset 0 0 0 4px rgba(157,44,31,.9),0 2px 6px rgba(80,40,20,.25);
filter:url(#seal-rough)}
.seal.md{width:60px;height:60px;font-size:20px}
.seal.lg{width:78px;height:78px;font-size:26px}
header .sub{font-family:var(--ft-kai);color:var(--verm);font-size:19px;letter-spacing:6px;margin-top:12px}
header .lore{color:var(--ink2);font-size:13.5px;margin-top:8px;letter-spacing:1px;position:relative;z-index:2}
.notice{background:#f6ecd2;border:1px solid #d9b98a;border-left:4px solid var(--verm);
border-radius:4px;color:#7c5a2e;padding:9px 18px;font-size:13.5px;margin:16px auto 0;max-width:860px;text-align:center}
h2.sec{font-family:var(--ft-kai);font-size:24px;letter-spacing:4px;margin:44px 0 2px;
display:flex;align-items:center;gap:12px;font-weight:700;flex-wrap:wrap}
h2.sec::before{content:"";width:6px;height:26px;background:var(--verm);border-radius:2px;flex:none;
box-shadow:inset 0 0 0 1.5px var(--paper),inset 0 0 0 3px var(--verm)}
h2.sec::after{content:"";width:20px;height:12px;flex:none;background:var(--qing);opacity:.55;
clip-path:polygon(0 0,100% 0,58% 50%,100% 100%,0 100%,42% 50%)}
h2.sec small{font-family:var(--ft-song);color:var(--ink2);font-weight:400;font-size:13px;letter-spacing:.5px}
.dvh{font-family:var(--ft-song);font-size:13px;color:#8b7d68;line-height:1.9;
margin-top:6px;padding:2px 0 2px 12px;border-left:3px solid var(--faint);letter-spacing:.3px}
.originrow{display:flex;gap:9px;align-items:flex-start;margin:6px 0 2px}
.originrow .otag{flex:none;font-family:var(--ft-kai);font-size:12px;letter-spacing:2px;color:var(--qing);
border:1px solid #9fb0b5;border-radius:3px;padding:1px 8px;margin-top:3px;background:#eef0e6}
.originrow .otext{font-size:13.5px;color:#3d4a52;line-height:1.8}
.dbox .dvh{margin-top:8px;animation:fadein .5s ease}
.couplet{position:fixed;top:120px;writing-mode:vertical-rl;font-family:var(--ft-kai);
color:var(--qing);opacity:.30;letter-spacing:10px;font-size:15px;pointer-events:none;z-index:1;user-select:none}
.couplet.l{left:8px}.couplet.r{right:8px}
@media (max-width:1180px){.couplet{display:none}}
.posize{display:inline-block;font-size:11.5px;color:var(--qing);border:1px dashed #9fb0b5;
border-radius:3px;padding:0 8px;font-family:var(--ft-kai);letter-spacing:1px}
.hui{display:block;width:100%;height:12px;color:#a89a78;margin:4px 0 10px}
.card{background-color:var(--card);border:1px solid var(--line);border-radius:6px;
padding:20px 24px;margin:14px 0;position:relative;
box-shadow:0 1px 3px rgba(90,70,40,.10),inset 0 0 0 1px rgba(255,255,255,.5);
background-image:url("@@CT@@"),url("@@CB@@"),url("@@CTL@@"),url("@@CBR@@");
background-position:right 7px top 7px,left 7px bottom 7px,right 7px bottom 7px,left 7px top 7px;
background-repeat:no-repeat;transition:transform .18s ease,box-shadow .18s ease}
.card:hover{transform:translateY(-1px);
box-shadow:0 4px 12px rgba(90,70,40,.16),inset 0 0 0 1px rgba(255,255,255,.5)}
.card::before{content:"";position:absolute;inset:4px;border:1px solid rgba(200,180,130,.35);border-radius:4px;pointer-events:none}
.card h3{font-family:var(--ft-kai);font-size:18px;margin-bottom:6px;display:flex;
justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;letter-spacing:1px}
.claim{color:var(--ink2);font-size:13.5px;margin-bottom:12px}
.badge{display:inline-block;border-radius:3px;padding:1px 10px;font-size:13px;font-family:var(--ft-kai);letter-spacing:2px;white-space:nowrap}
.b-null{background:#eee6cf;border:1px solid #c4b287;color:#7a6a4d}
.b-sig{background:#f3d9cf;border:1px solid var(--verm);color:#a03327}
.b-ins{background:#ece7db;border:1px solid #b9ad8f;color:#857a68}
.luck{font-size:13px;color:var(--ink2);font-family:var(--ft-kai);letter-spacing:1px}
.luck b{color:var(--verm);font-weight:700}
.chip{display:inline-block;background:var(--faint);border:1px solid var(--line);border-radius:3px;
padding:3px 12px;margin:4px;font-size:13.5px;font-family:var(--ft-kai);letter-spacing:1px}
.chip b{color:var(--verm)}
table.st{width:100%;border-collapse:collapse;font-size:14px;margin:10px 0}
table.st td,table.st th{padding:6px 8px;border-bottom:1px dashed var(--line);text-align:right}
table.st th{color:var(--ink2);font-weight:400;background:#f2e9d0}
table.st tbody tr:nth-child(even) td{background:rgba(238,228,200,.32)}
table.st td:first-child,table.st th:first-child{text-align:left}
.num{font-variant-numeric:tabular-nums}
tr.hl td{background:#f6ecd2}
.vd{font-size:13.5px;color:var(--ink2)}
.vd.warn{color:#a03327}
svg.chart{display:block;width:100%;height:auto}
.chart path.anim{stroke-dasharray:5000;stroke-dashoffset:5000;animation:draw 1.6s ease forwards}
@keyframes draw{to{stroke-dashoffset:0}}
.legend{font-size:12.5px;color:var(--ink2);margin-top:4px;letter-spacing:.5px}
.legend i{display:inline-block;width:20px;height:0;border-top:3px solid;margin:0 5px 3px 10px;vertical-align:middle;border-radius:2px}
.verdict-big{border:1px solid var(--line);border-radius:6px;padding:20px 64px 20px 26px;margin-top:18px;
background:linear-gradient(180deg,#faf3df,#f3ead0);position:relative}
.verdict-big::after{content:"勘";position:absolute;right:20px;top:16px;width:36px;height:36px;
background:radial-gradient(ellipse at 40% 34%,#cf4638,#b73326 65%);color:#f8f0dc;font-family:var(--ft-kai);
font-size:20px;display:flex;align-items:center;justify-content:center;border-radius:6px 8px 5px 7px;
transform:rotate(6deg);filter:url(#seal-rough);
box-shadow:inset 0 0 0 1.5px rgba(248,240,220,.85)}
.verdict-big .vt{font-family:var(--ft-kai);font-size:18px;letter-spacing:3px;color:var(--verm);font-weight:700}
.moral{font-size:15px;margin-top:8px}
.moral2{font-size:13.5px;color:var(--ink2);margin-top:8px}
.wall{display:flex;align-items:flex-end;gap:5px;height:170px;padding:8px 4px 0;position:relative}
.wall .bar{flex:1;min-width:8px;border-radius:2px 2px 0 0;position:relative;cursor:pointer;
background:linear-gradient(180deg,#ddd0ac,#b9a878);transition:filter .15s,box-shadow .15s}
.wall .bar.sig{background:linear-gradient(180deg,#d66a5c,#a92e22)}
.wall .bar.mine{outline:2px solid var(--ink);outline-offset:1px}
.wall .bar:hover{filter:brightness(1.14);box-shadow:0 0 12px rgba(194,59,46,.45)}
.wline{position:absolute;left:0;right:0;border-top:2px dashed var(--ink);opacity:.75}
.wlabel{position:absolute;right:2px;font-size:11.5px;color:var(--ink);font-family:var(--ft-kai);
background:rgba(250,245,230,.94);padding:0 5px;border-radius:3px;border:1px solid rgba(44,36,26,.22)}
.xlab{display:flex;gap:5px;padding-top:4px}
.xlab span{flex:1;min-width:8px;text-align:center;font-size:10.5px;color:var(--ink2);overflow:hidden}
.wnote{font-size:12.5px;color:var(--ink2);margin-top:8px;letter-spacing:.3px}
.tip{position:fixed;background:#fbf5e4;border:1px solid #c9b88b;border-radius:4px;padding:8px 12px;
font-size:12.5px;pointer-events:none;z-index:99;display:none;box-shadow:0 4px 14px rgba(90,70,40,.25);color:var(--ink)}
.formbox{background:var(--card);border:1px solid var(--line);border-radius:6px;
padding:36px 26px 28px;margin:30px 0;text-align:center;position:relative}
.formbox::before{content:"";position:absolute;inset:5px;border:1px solid rgba(200,180,130,.4);border-radius:5px;pointer-events:none}
.formbox .fb-title{font-family:var(--ft-kai);font-size:30px;letter-spacing:8px;font-weight:700}
.formbox .fb-sub{font-family:var(--ft-kai);color:var(--verm);letter-spacing:3px;margin-top:8px;font-size:15px}
.formbox .fb-lore{color:var(--ink2);font-size:13.5px;margin:14px auto 4px;max-width:580px;line-height:2}
.formbox select{background:#fdf9ee;color:var(--ink);border:1px solid var(--line);border-radius:3px;
padding:8px 10px;font-size:15px;margin:8px 3px;font-family:var(--ft-kai)}
.formbox button.go{background:var(--verm);color:#f8f0dc;border:1px solid #9d2f24;border-radius:3px;
padding:11px 40px;font-size:17px;font-family:var(--ft-kai);letter-spacing:8px;text-indent:8px;
cursor:pointer;margin-top:16px;box-shadow:0 2px 5px rgba(140,50,30,.3)}
.formbox button.go:hover{background:#a93527}
.formbox .fb-note{color:#93866f;font-size:12px;margin-top:12px;letter-spacing:1px}
#stage{position:fixed;left:0;right:0;bottom:0;z-index:60;transition:transform .6s ease,opacity .6s ease}
#stage.bye{transform:translateY(112%);opacity:0;pointer-events:none}
.stage-in{max-width:960px;margin:0 auto;position:relative;padding:0 18px 16px}
.dbox{background:#faf4e2;border:1px solid #c9b88b;border-radius:6px;box-shadow:0 6px 24px rgba(80,60,30,.28);
padding:20px 22px 14px 128px;min-height:124px;cursor:pointer;position:relative}
.dbox::before{content:"";position:absolute;top:0;left:0;right:0;height:8px;border-radius:6px 6px 0 0;
background:repeating-linear-gradient(90deg,#b9a878 0 3px,transparent 3px 7px);opacity:.55}
.avatar{position:absolute;left:30px;top:-28px;width:84px;text-align:center;z-index:2}
.avatar .sfig{width:72px;height:72px;display:block;margin:0 auto;
animation:breath 3.2s ease-in-out infinite;filter:drop-shadow(0 2px 4px rgba(90,70,40,.25))}
@keyframes breath{0%,100%{transform:rotate(0) scale(1)}50%{transform:rotate(0) scale(1.045)}}
.avatar .aname{margin-top:5px;font-family:var(--ft-kai);font-size:14px;letter-spacing:2px;
background:#f2e8cf;border:1px solid var(--line);border-radius:3px;padding:2px 0;color:var(--ink)}
.dname{position:absolute;top:8px;left:128px;font-family:var(--ft-kai);color:var(--verm);font-size:14px;letter-spacing:3px}
.dtext{font-family:var(--ft-kai);font-size:16px;line-height:2;letter-spacing:.5px;padding-top:14px;min-height:66px;color:var(--ink)}
.dtext .cursor{display:inline-block;width:9px;height:18px;background:var(--verm);vertical-align:-3px;margin-left:2px;animation:blink .9s steps(1) infinite}
@keyframes blink{50%{opacity:0}}
.dctl{position:absolute;right:14px;bottom:10px;display:flex;gap:10px}
.dctl button{background:none;border:1px solid var(--line);border-radius:3px;color:var(--ink2);
font-family:var(--ft-kai);font-size:13px;letter-spacing:2px;padding:3px 12px;cursor:pointer}
.dctl button.next{border-color:var(--verm);color:var(--verm)}
.dctl button:hover{background:#f1e6c8}
.opts{display:flex;flex-direction:column;gap:8px;margin-top:6px}
.opts button{background:#fdf7e7;border:1px solid #c9b88b;border-radius:4px;color:var(--ink);
font-family:var(--ft-kai);font-size:15px;letter-spacing:1px;padding:7px 14px;cursor:pointer;text-align:left}
.opts button:hover{background:#f3e6c4;border-color:var(--verm);color:var(--verm)}
.veiled{filter:blur(7px) grayscale(.4);opacity:.22;transition:filter .8s ease,opacity .8s ease;pointer-events:none}
.spot{animation:spot 2.2s ease}
@keyframes spot{0%{box-shadow:0 0 0 0 rgba(194,59,46,0)}25%{box-shadow:0 0 0 4px rgba(194,59,46,.45)}100%{box-shadow:0 0 0 0 rgba(194,59,46,0)}}
.fadein{animation:fadein .7s ease}
@keyframes fadein{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
.foot{text-align:center;color:var(--ink2);font-size:12.5px;margin-top:44px;line-height:2.1}
.print-btn{position:fixed;right:18px;bottom:18px;background:#f2e8cf;color:#7a5a2e;
border:1px solid #c9b88b;border-radius:3px;padding:8px 16px;cursor:pointer;font-size:13px;font-family:var(--ft-kai);letter-spacing:2px;z-index:55}
.print-btn:hover{background:#eadfc2}
.xu{background:#f6eed8;border:1px solid var(--line);border-left:4px solid var(--verm);
border-radius:4px;padding:14px 20px;margin:20px 0;font-family:var(--ft-kai);font-size:15px;line-height:2.2;letter-spacing:1px;color:#5a4c38}
.xu .who{text-align:right;color:var(--verm);font-size:13.5px}
.stampbox{display:flex;justify-content:center;margin:18px 0 8px}
.stamp{display:inline-flex;flex-direction:column;align-items:center;justify-content:center;
border:4px solid var(--verm);color:var(--verm);border-radius:10px 7px 11px 6px;padding:16px 30px;
font-family:var(--ft-kai);font-weight:700;transform:rotate(-4deg);position:relative;
background:radial-gradient(ellipse at 42% 36%,rgba(194,59,46,.10),rgba(194,59,46,.03) 72%);
box-shadow:inset 0 0 0 2px rgba(244,237,218,.7),inset 0 0 0 4px rgba(194,59,46,.85);
filter:url(#seal-rough)}
.stamp .sp1{font-size:26px;letter-spacing:6px}
.stamp .sp2{font-size:40px;letter-spacing:10px;margin-top:4px;text-indent:10px}
.stamp .sp1 span,.stamp .sp2 span{display:inline-block}
.stamp.anim{animation:stampin .55s cubic-bezier(.2,1.5,.4,1)}
@keyframes stampin{from{transform:scale(2.1) rotate(-16deg);opacity:0}to{transform:scale(1) rotate(-4deg);opacity:1}}
.eggrow{margin:6px 0}
.eggrow .ename{display:inline-block;background:#f3d9cf;border:1px solid var(--verm);color:#a03327;
border-radius:3px;padding:1px 10px;font-family:var(--ft-kai);letter-spacing:2px;font-size:13.5px}
.reasons{margin-top:10px;padding-left:0;list-style:none}
.reasons li{font-size:13.5px;color:var(--ink2);padding-left:18px;position:relative;line-height:2}
.reasons li::before{content:"";position:absolute;left:2px;top:12px;width:7px;height:7px;background:var(--verm);border-radius:1px;transform:rotate(45deg)}
.coll{margin-top:14px;border-top:1px dashed var(--line);padding-top:12px}
.collbar{height:10px;background:#eee6cf;border-radius:5px;overflow:hidden;border:1px solid var(--line)}
.collbar div{height:100%;background:var(--verm);transition:width .8s ease}
.colltext{font-size:13px;color:var(--ink2);margin:6px 0}
.collchips{display:flex;flex-wrap:wrap;gap:6px;margin:6px 0}
.collchips span{font-size:12.5px;background:var(--faint);border:1px solid var(--line);border-radius:3px;padding:1px 8px;font-family:var(--ft-kai)}
.collchips span.got{background:#f3d9cf;border-color:var(--verm);color:#a03327}
.coll textarea{width:100%;background:#fdf9ee;border:1px solid var(--line);border-radius:3px;
font-size:12px;padding:6px 8px;font-family:monospace;color:var(--ink2);resize:none}
.coll .crow{display:flex;gap:8px;margin-top:8px;flex-wrap:wrap}
.coll input{flex:1;min-width:200px;background:#fdf9ee;border:1px solid var(--line);border-radius:3px;padding:6px 8px;font-family:monospace;font-size:12px}
.coll button{background:#f2e8cf;border:1px solid #c9b88b;border-radius:3px;color:#7a5a2e;
font-family:var(--ft-kai);font-size:13px;letter-spacing:1px;padding:6px 14px;cursor:pointer}
.coll button:hover{background:#eadfc2}
.qrow{margin:8px 0;font-size:14.5px}
.qrow .qq{font-family:var(--ft-kai);letter-spacing:1px}
.qrow .opt{color:var(--ink2);margin:0 6px}
/* ---------- 八卦阵 ---------- */
#bagua-overlay{position:fixed;inset:0;z-index:120;background:rgba(244,237,218,.97);
display:flex;flex-direction:column;align-items:center;justify-content:center;gap:18px;
transition:opacity .6s ease;cursor:pointer}
#bagua-overlay.bye{opacity:0;pointer-events:none}
#bagua-overlay .ov-title{font-family:var(--ft-kai);font-size:30px;letter-spacing:14px;text-indent:14px;color:var(--ink)}
#bagua-overlay .ov-hint{font-size:12.5px;color:#93866f;letter-spacing:2px}
.bagua{display:block}
.bagua .tj{transform-origin:center;animation:baguaspin 26s linear infinite}
.bagua.fast .tj{animation-duration:9s}
@keyframes baguaspin{from{transform:rotate(0)}to{transform:rotate(360deg)}}
.bagua .tg rect{fill:#8a7d63;transition:fill .4s ease}
.bagua .tg.lit rect{fill:#c23b2e}
.bagua .tg.lit .tgname{fill:#c23b2e;opacity:1}
.bagua .tg .tgname{fill:#8a7d63;opacity:.55;transition:fill .4s ease;letter-spacing:1px}
.avatar .bgring{position:absolute;left:50%;top:50%;width:104px;height:104px;margin:-52px 0 0 -52px;
opacity:.32;z-index:-1}
#pb{position:fixed;top:12px;left:50%;transform:translateX(-50%);z-index:70;width:56px;height:56px;
opacity:.92;filter:drop-shadow(0 2px 6px rgba(90,70,40,.3));transition:opacity .6s}
#pb.hide{opacity:0;pointer-events:none}
@media print{
 body{background:#fff;padding-bottom:0}
 body::before,body::after,#stage,.print-btn,#pb,#bagua-overlay{display:none!important}
 .veiled{filter:none;opacity:1}
 .card,.verdict-big,.stamp{break-inside:avoid;box-shadow:none}
}
@media (max-width:760px){
 h1.site{font-size:32px;letter-spacing:8px}
 .dbox{padding-left:22px;padding-top:34px}
 .avatar{position:static;margin-bottom:8px}
 .dname{left:22px}
}
"""
    return (css.replace("@@CT@@", _corner_uri(90)).replace("@@CB@@", _corner_uri(0))
            .replace("@@CTL@@", _corner_uri(270)).replace("@@CBR@@", _corner_uri(180)))


def _huiw_svg() -> str:
    return ('<svg class="hui" viewBox="0 0 960 12" preserveAspectRatio="none" aria-hidden="true">'
            '<defs><pattern id="hp" width="30" height="12" patternUnits="userSpaceOnUse">'
            '<path d="M3 11 V2 H27 V8 H10 V5 H20" fill="none" stroke="currentColor" stroke-width="1.5"/>'
            '</pattern></defs><rect width="960" height="12" fill="url(#hp)"/></svg>')


def _html_shell(title: str, body: str, js: str) -> str:
    seal_defs = ('<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs>'
                 '<filter id="seal-rough" x="-8%" y="-8%" width="116%" height="116%">'
                 '<feTurbulence type="fractalNoise" baseFrequency="0.55" numOctaves="2" seed="7" result="n"/>'
                 '<feDisplacementMap in="SourceGraphic" in2="n" scale="2.4"/>'
                 '</filter></defs></svg>')
    return ("""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>@@TITLE@@</title>
<style>@@CSS@@</style>
</head>
<body>
@@SEALDEFS@@
@@BODY@@
<div class="tip" id="tip"></div>
<button class="print-btn" onclick="window.print()">存档为卷宗</button>
<script>
@@JS@@
</script>
</body>
</html>""").replace("@@TITLE@@", title).replace("@@CSS@@", _css()).replace("@@SEALDEFS@@", seal_defs).replace("@@BODY@@", body).replace("@@JS@@", js)


# ================================================================ 渲染层 ==
def _render_js() -> str:
    return r"""
function fmt(x,d){return x==null?"—":x.toFixed(d==null?2:d);}
function stampChars(s){return[...String(s)].map(ch=>
  '<span style="display:inline-block;transform:rotate('+(Math.random()*8-4).toFixed(1)+'deg) '+
  'translateY('+(Math.random()*3-1.5).toFixed(1)+'px) '+
  'scale('+(0.95+Math.random()*0.1).toFixed(3)+')">'+ch+'</span>').join("");}
function badgeOf(v){return v==="significant"?'<span class="badge b-sig">似验 先莫欢喜</span>':
  v==="insufficient"?'<span class="badge b-ins">数不足</span>':'<span class="badge b-null">不验</span>';}
function luckOf(t){if(t.verdict==="insufficient")return'灵验度 无从谈起';
  if(t.p!=null&&t.p<0.05)return'灵验度 <b>高（慎勿自欺）</b>';
  if(t.p!=null&&t.p<0.30)return'灵验度 <b>中</b>';return'灵验度 <b>低</b>';}

const NICE_TICKS=[0.5,1,2,5,10,20,50,100,200];
function curveSvgLog(lines,opts){
  opts=opts||{};
  const W=860,H=200,PAD=40,RUGH=H-16;
  const all=[];lines.forEach(l=>{if(l.a)all.push.apply(all,l.a);});
  const mn=Math.min.apply(null,all),mx=Math.max.apply(null,all);
  const lo=Math.pow(10,Math.floor(Math.log10(Math.max(mn,0.01)*0.95)));
  const hi=Math.pow(10,Math.ceil(Math.log10(mx*1.05)));
  const n=Math.max.apply(null,lines.map(l=>l.a.length));
  const X=i=>PAD+(W-2*PAD-56)*i/(n-1);
  const Y=v=>H-PAD-(H-2*PAD)*(Math.log(Math.max(v,1e-6)/lo)/Math.log(hi/lo));
  let g="";
  for(const t of NICE_TICKS){if(t<lo*0.98||t>hi*1.02)continue;const gy=Y(t);
    g+='<line x1="'+PAD+'" y1="'+gy+'" x2="'+(W-PAD)+'" y2="'+gy+'" stroke="#ddd0ac" stroke-width="1"/>'+
      '<text x="'+(PAD+2)+'" y="'+(gy-4).toFixed(1)+'" fill="#93866f" font-size="10" font-family="KaiTi,serif">'+t+'</text>';}
  const y1=Y(1);
  g+='<line x1="'+PAD+'" y1="'+y1+'" x2="'+(W-PAD)+'" y2="'+y1+'" stroke="#b9a87f" stroke-dasharray="5 4" stroke-width="1" opacity="0.55"/>';
  let sv='<svg class="chart" viewBox="0 0 '+W+' '+H+'">'+g;
  if(opts.rug){
    const N=opts.rug.length;const XR=i=>PAD+(W-2*PAD-56)*i/(N-1);
    let segs="",i=0;
    while(i<N){
      if(opts.rug[i]){let j=i;while(j+1<N&&opts.rug[j+1])j++;
        const x0=XR(i),x1=Math.max(XR(j)+1.6,x0+1.6);
        segs+='<rect x="'+x0.toFixed(1)+'" y="'+(RUGH)+'" width="'+(x1-x0).toFixed(1)+'" height="7" fill="#c23b2e" opacity="0.6" rx="0.6"/>';
        i=j+1;}else i++;}
    sv+='<line x1="'+PAD+'" y1="'+(RUGH+3.5)+'" x2="'+(W-PAD)+'" y2="'+(RUGH+3.5)+'" stroke="#cbbb92" stroke-width="1"/>'+segs;
    if(opts.nHeld!=null){
      sv+='<text x="'+(W-PAD)+'" y="'+(PAD-16)+'" text-anchor="end" fill="#3d4a52" font-size="11.5" font-family="KaiTi,serif">持仓 '+opts.nHeld+' 天'+(opts.nTotal?' / 共 '+opts.nTotal+' 天（'+(100*opts.nHeld/opts.nTotal).toFixed(1)+'%）':'')+'</text>';
      sv+='<text x="'+PAD+'" y="'+(H-2)+'" fill="#8b7d68" font-size="10" font-family="KaiTi,serif">朱砂条带为该策略的真实持仓日（每一天都计入回测 非只一日）</text>';}
  }
  for(const l of lines){
    if(!l.a)continue;
    const p=l.a.map((v,i)=>(i?"L":"M")+X(i).toFixed(1)+","+Y(v).toFixed(1)).join("");
    sv+='<path class="anim" d="'+p+'" fill="none" stroke="'+l.color+'" stroke-width="'+(l.w||2)+'"'+(l.dash?' stroke-dasharray="'+l.dash+'"':'')+' opacity="'+(l.op||1)+'"/>';
    sv+='<text x="'+(W-PAD-54)+'" y="'+(Y(l.a[l.a.length-1])+4).toFixed(1)+'" fill="'+l.color+'" font-size="11" font-family="KaiTi,serif">'+(l.label||"")+" "+fmt(l.a[l.a.length-1],2)+'</text>';
  }
  return sv+'</svg>';
}

function testCard(t,curves,idAttr,opts){
  opts=opts||{};
  const rows=[["玄学组日均收益",fmt(t.mean1_bp)+" bp/日"],["对照组日均收益",fmt(t.mean0_bp)+" bp/日"],
    ["差值",fmt(t.mean1_bp==null||t.mean0_bp==null?null:t.mean1_bp-t.mean0_bp)+" bp/日"],
    ["t 统计量",fmt(t.t,3)],["p 值（双尾）",t.p==null?"—":t.p.toFixed(4)],
    ["样本天数",t.n1+" 天 / "+t.n0+" 天"]];
  let chart="";
  if(curves&&curves[0]){
    chart=curveSvgLog([
      {a:curves[1],color:"#5a7a6e",w:1.6,op:.9,label:"持有不动"},
      {a:curves[0],color:"#c23b2e",w:2.2,label:"玄学策略"}],
      {rug:opts.rug,nHeld:(t.hold_n!=null?t.hold_n:t.n1),nTotal:opts.nTotal});
    chart+='<div class="legend"><i style="border-color:#c23b2e"></i>玄学x你的行为规则 合体策略（信号定何时可持仓，你的六答定押多少）<i style="border-color:#5a7a6e"></i>持有不动（上证指数买入持有）</div>';
  }
  let stratLine="";
  if(t.strategy){
    const posN=opts.posName;
    const bih=t.strat_total_bih;
    const st=posN!=null?t.strat_total_pos:(t.strat_total_full!=null?t.strat_total_full:(curves&&curves[0]?curves[0][curves[0].length-1]:null));
    const rev=posN!=null?t.strat_total_pos_rev:t.strategy_total_rev;
    const fwd=t.strat_total_fwd!=null?t.strat_total_fwd:t.strategy_total_fwd;
    const bt=curves&&curves[1]?curves[1][curves[1].length-1]:null;
    stratLine='<div class="claim" style="border-left:3px solid #c23b2e;background:#f6ecd2;padding:4px 10px;margin-bottom:10px">对应策略：'+t.strategy+
      (bih!=null?'　（玄学x你的规则 合体终值 <b style="color:#8e1f16">'+fmt(bih,2)+'</b>':'')+
      (st!=null?'，满仓照做 '+fmt(st,2):'')+
      (rev!=null?'，反着做 '+fmt(rev,2):'')+
      (fwd!=null?'，少数派正向 '+fmt(fwd,2):'')+
      ' vs 持有不动 <b>'+fmt(bt,2)+'</b>）</div>';
  }
  return '<div class="card fadein"'+(idAttr?' id="'+idAttr+'"':'')+'><h3><span>'+t.title+'　<em class="luck" style="font-style:normal">'+luckOf(t)+'</em></span>'+badgeOf(t.verdict)+'</h3>'+
    '<div class="claim">坊间说法：'+t.claim.replace(/^民间说法：/,"").replace(/^民间主流说法：/,"")+'</div>'+
    (t.origin?'<div class="originrow"><span class="otag">坊间原版</span><span class="otext">'+
      String(t.origin).replace(/^坊间原版：/,"")+'</span></div>'+
      (t.origin_bai?'<div class="dvh">'+t.origin_bai+'</div>':''):'')+stratLine+
    '<table class="st num">'+rows.map(r=>'<tr><th>'+r[0]+'</th><td>'+r[1]+'</td></tr>').join("")+'</table>'+
    '<div class="vd'+(t.verdict==="significant"?" warn":"")+'">勘验：'+t.verdict_text+'</div>'+
    (t.verdict_bai?'<div class="dvh">'+t.verdict_bai+'</div>':'')+chart+'</div>';
}

function wallBlock(sc,mineKey){
  const hMax=140;
  const dataMax=Math.max.apply(null,sc.items.map(x=>-Math.log10(Math.max(1e-4,x.p))));
  const bonf=-Math.log10(0.05/sc.m);
  const scale=Math.max(dataMax,bonf);
  let bars="",labels="";
  for(const it of sc.items){
    const h=3+(-Math.log10(Math.max(1e-4,it.p)))/scale*(hMax-3);
    const cls="bar"+(it.p<0.05?" sig":"")+(it.key==mineKey?" mine":"");
    bars+='<div class="'+cls+'" data-k="'+it.key+'" style="height:'+h.toFixed(0)+'px"></div>';
    labels+='<span>'+it.key+'</span>';
  }
  const wl=bonf/scale*hMax;
  const famName={day:"每月号数 三十一选一",jieqi:"二十四节气 二十四选一",month:"生辰月份 十二选一",animal:"十二生肖本命年 十二选一",element:"五行年命 五选一",
    jianchu:"建除十二神 十二选一",moonphase:"月相四相 四选一"}[sc.family];
  return '<div class="card fadein" id="id-wall-'+sc.family+'"><h3><span>遍试诸日 '+famName+'</span>'+
    '<span style="font-size:12.5px;color:#6f6353">名义显著 '+sc.n_sig_raw+' / '+sc.m+'，Bonferroni 校正后存活 '+sc.n_sig_adj+'（纯碰运气期望 '+sc.expected_false_pos+' 个）</span></h3>'+
    '<div class="wall">'+bars+'<div class="wline" style="bottom:'+wl.toFixed(0)+'px"></div><div class="wlabel" style="bottom:'+(Math.min(164,wl+3)).toFixed(0)+'px">校正线 之上方作得数</div></div>'+
    '<div class="xlab">'+labels+'</div>'+
    '<div class="wnote">柱高则 p 小，看似愈真。朱砂柱为名义 p&lt;0.05；墨框者为客官自家的属性；墨色虚线为 Bonferroni 校正门槛，柱身不过此线，命运便只是运气。悬停可观各柱数值。</div></div>';
}

function attachWallTips(scans){
  const tip=document.getElementById("tip");
  document.querySelectorAll(".wall .bar").forEach(b=>{
    b.addEventListener("mousemove",e=>{
      const fam=b.closest(".card").id.replace("id-wall-","");
      const sc=scans.find(s=>s.family===fam);
      const it=sc.items.find(x=>String(x.key)===b.dataset.k);if(!it)return;
      tip.innerHTML="<b>"+it.label+"</b><br>p = "+it.p.toFixed(4)+"（校正后 "+it.p_bonf.toFixed(4)+"）<br>日均差 "+fmt(it.diff_bp)+" bp，t = "+fmt(it.t,2)+"，n = "+it.n1;
      tip.style.display="block";tip.style.left=Math.min(window.innerWidth-230,e.clientX+14)+"px";tip.style.top=(e.clientY+14)+"px";
    });
    b.addEventListener("mouseleave",()=>tip.style.display="none");
  });
}


/* ---------- 八卦阵（SVG 生成器 三处复用） ---------- */
const TRIGRAMS=[["乾",1,1,1],["兑",1,1,0],["离",1,0,1],["震",1,0,0],
                ["巽",0,1,1],["坎",0,1,0],["艮",0,0,1],["坤",0,0,0]];
function baguaSvg(idPrefix,size,opt){
  opt=opt||{};
  const R=opt.mini?76:88,ringIn=R-26;
  let g='';
  for(let i=0;i<8;i++){
    const ang=(i*45-90)*Math.PI/180;
    const cx=Math.cos(ang)*((R+ringIn)/2-2),cy=Math.sin(ang)*((R+ringIn)/2-2);
    const deg=i*45-90+90;
    const t=TRIGRAMS[i];
    let bars='';
    for(let b=0;b<3;b++){
      const solid=t[b+1];
      const y=-9+b*8;
      if(solid)bars+='<rect x="-13" y="'+y+'" width="26" height="5" rx="1"/>';
      else bars+='<rect x="-13" y="'+y+'" width="10.5" height="5" rx="1"/><rect x="2.5" y="'+y+'" width="10.5" height="5" rx="1"/>';
    }
    const name=opt.mini?'':'<text class="tgname" x="0" y="'+(R+16)+'" text-anchor="middle" font-size="13" font-family="KaiTi,serif">'+t[0]+'</text>';
    g+='<g class="tg" id="'+idPrefix+'-tg-'+i+'" transform="translate('+cx.toFixed(1)+','+cy.toFixed(1)+') rotate('+deg+')">'+bars+'</g>';
    if(!opt.mini)g+='<text transform="translate('+(cx*1.24).toFixed(1)+','+(cy*1.24+4).toFixed(1)+')" text-anchor="middle" font-size="12" fill="#8a7d63" opacity="0" font-family="KaiTi,serif" id="'+idPrefix+'-tn-'+i+'"></text>';
  }
  const tjR=opt.mini?15:24;
  const tj='<g class="tj"><circle r="'+tjR+'" fill="#2f2a26"/>'
    +'<path d="M0,-'+tjR+' A'+tjR+','+tjR+' 0 0 1 0,'+tjR+' A'+(tjR/2)+','+(tjR/2)+' 0 0 1 0,0 A'+(tjR/2)+','+(tjR/2)+' 0 0 0 0,-'+tjR+' Z" fill="#f4edda"/>'
    +'<circle cx="0" cy="'+(-tjR/2)+'" r="'+(tjR*0.16)+'" fill="#2f2a26"/>'
    +'<circle cx="0" cy="'+(tjR/2)+'" r="'+(tjR*0.16)+'" fill="#f4edda"/></g>';
  return '<svg class="bagua" width="'+size+'" height="'+size+'" viewBox="-110 -110 220 220">'
    +'<circle r="'+(R+6)+'" fill="none" stroke="#c9b88b" stroke-width="1.5"/>'
    +'<circle r="'+(ringIn-8)+'" fill="none" stroke="#c9b88b" stroke-width="1" opacity=".6"/>'
    +g+tj+'</svg>';
}
function lightTrigram(i){["pb"].forEach(pre=>{const n=document.getElementById(pre+"-tg-"+i);
  if(n)n.classList.add("lit");});}
function baguaOverlayPlay(done){
  const ov=document.createElement("div");
  ov.id="bagua-overlay";
  ov.innerHTML='<div class="ov-title">起 卦</div>'+baguaSvg("ov",Math.min(420,window.innerWidth*0.8))
    +'<div class="ov-hint">轻触任意处可跳过</div>';
  document.body.appendChild(ov);
  let fin=false;
  const finish=()=>{if(fin)return;fin=true;
    ov.classList.add("bye");setTimeout(()=>ov.remove(),650);
    document.getElementById("pb").classList.remove("hide");
    done();};
  ov.onclick=finish;
  for(let i=0;i<8;i++)setTimeout(()=>{const n=document.getElementById("ov-tg-"+i);
    if(n&&!fin)n.classList.add("lit");},200+i*270);
  setTimeout(finish,200+8*270+700);
}

/* ---------- 问券 / 策略殿 / 行业帖 / 称号 ---------- */
function quizCard(result){
  const q=result.questionnaire,qs=q.questions,an=q.answers;
  const rows=qs.map((x,i)=>{
    const picked=an[x.key];
    const opts=x.options.map(o=>{
      const on=picked===o[0];
      return '<span class="opt" style="'+(on?"color:#c23b2e;font-weight:700;":"")+'">'+o[0]+' '+o[1]+'</span>';
    }).join("｜");
    return '<div class="qrow"><span class="qq">'+(i+1)+'　'+x.question+'</span><br>　　'+opts+'</div>';
  }).join("");
  const info=q.info;
  return '<div class="card fadein" id="id-sec-quiz"><h3><span>问券答卷　风格判定</span>'+
    '<span class="badge '+(info.style==="进取"?"b-sig":(info.style==="保守"?"b-ins":"b-null"))+'">'+info.style+'</span>'+
    (info.xuan_pos_name?'<span class="posize">玄学仓位 '+info.xuan_pos_name+'</span>':"")+'</h3>'+
    rows+
    (an.defaulted?'<div style="font-size:12px;color:#93866f">（未作答，取中庸默认，互动页答谢知夏六问后此处自动更新）</div>':"")+
    '<div style="font-size:13.5px;color:#6f6353;margin-top:6px">风格分 '+info.score+
    '　五行偏好 '+(info.element_pref||"未选")+'　玄学仓位 '+(info.xuan_pos_name||"半仓（默认）")+(info.leverage?"　<span style=\"color:#a03327\">客官竟要加杠杆，谢知夏已劝</span>":"")+'</div>'+
    '<div class="vd" style="margin-top:4px">定档规则：风格以问卷为主，命格五行旺衰为辅，客官的胆子，问卷说了算，命格只是添头（行为胜于玄学）。第六答的仓位将乘进七问与本命合参的策略回测。</div></div>';
}

function strategyCard(result){
  const st=result.strategy,pos=st.positions,info=result.questionnaire.info;
  const an=result.questionnaire.answers;
  const ws=result.titles?result.titles.wang_shuai:"休";
  // 行为策略：答卷规则逐日模拟（网页端现算，与引擎对拍一致）
  let beh=null,behRule="";
  if(D){
    const b=curveBehavior(an,ws);
    beh={total:b.total,curve:downsample(b.curve)};
    behRule=behaviorRuleText(an,ws);}
  else if(st.behavior){beh=st.behavior;behRule=st.behavior.rule;}
  let table='<table class="st num"><tr><th>策略</th><th>终值</th><th>年化收益</th><th>最大回撤</th><th>年化波动</th></tr>'+
    '<tr><td>持有不动（上证指数本身，对照）</td><td>'+st.bench.total.toFixed(2)+'</td><td>'+st.bench.cagr.toFixed(1)+'%</td><td>'+st.bench.mdd.toFixed(1)+'%</td><td>'+st.bench.vol.toFixed(1)+'%</td></tr>';
  if(beh)table+='<tr class="hl"><td>客官的行为策略（答卷规则模拟）</td><td><b>'+beh.total.toFixed(2)+'</b></td><td>—</td><td>—</td><td>—</td></tr>';
  ["守拙","中庸","进取"].forEach(n=>{const m=pos[n];
    if(m)table+='<tr><td>'+n+'（黄历宜日'+(n==="守拙"?"25%":(n==="中庸"?"50%":"100"))+'仓）</td><td>'+m.total.toFixed(2)+'</td><td>'+m.cagr.toFixed(1)+'%</td><td>'+m.mdd.toFixed(1)+'%</td><td>'+m.vol.toFixed(1)+'%</td></tr>';});
  if(st.reverse)table+='<tr><td>反向操作（宜日空仓）</td><td>'+st.reverse.total.toFixed(2)+'</td><td>'+st.reverse.cagr.toFixed(1)+'%</td><td>'+st.reverse.mdd.toFixed(1)+'%</td><td>'+st.reverse.vol.toFixed(1)+'%</td></tr>';
  table+='</table>';
  const chart=curveSvgLog([
    {a:st.bench.curve,color:"#6f6353",w:1.6,dash:"6 4",op:.85,label:"持有不动"},
    {a:beh?beh.curve:null,color:"#8e1f16",w:2.6,label:"你的行为策略"},
    {a:pos["守拙"]?pos["守拙"].curve:null,color:"#e0a294",w:1.8,label:"守拙"},
    {a:pos["中庸"]?pos["中庸"].curve:null,color:"#d06a58",w:1.8,label:"中庸"},
    {a:pos["进取"]?pos["进取"].curve:null,color:"#c23b2e",w:1.8,label:"进取"}].filter(l=>l.a));
  return '<div class="card fadein" id="id-card-strat"><h3><span>策略殿　你的行为策略对比回测</span>'+
    '<span style="font-size:12.5px;color:#6f6353">行为策略由答卷规则逐日模拟；三档玄学信号为'+st.signal+'</span></h3>'+
    (behRule?'<div class="originrow"><span class="otag">你的规则</span><span class="otext">'+behRule+
      '。第二答（行业偏好）与第四答（赚钱路子）不进仓位规则，分别用于五行行业帖与人物匹配。</span></div>':"")+
    chart+'<div class="legend"><i style="border-color:#8e1f16"></i>你的行为策略<i style="border-color:#6f6353"></i>持有不动（即上证指数买入持有，择时对比的标准基线）<i style="border-color:#e0a294"></i>守拙<i style="border-color:#d06a58"></i>中庸<i style="border-color:#c23b2e"></i>进取<span style="color:#93866f">　对数坐标</span></div>'+
    table+
    '<div class="vd">勘验：行为策略即把客官六问答成真实的加减仓规则放到三十五年行情里跑一遍，盈亏皆如实呈上；玄学三档任选皆难稳赢持有不动，信号若无据，仓位轻重皆空。与其听玄学定仓位，不如纪律定投指数。</div></div>';
}

function sectorCard(result){
  const secs=result.sectors||[];
  const p=result.profile,pref=result.questionnaire.info.element_pref;
  if(!secs.length)return '<div class="card" id="id-card-sector"><h3><span>五行行业帖</span></h3><div class="vd">行业指数数据未取得，此帖无数据可验，仅供一乐。</div></div>';
  const rows=secs.map(s=>{
    const isMine=s.element===p.nayin_element,isPref=s.element===pref;
    return '<tr'+(isMine?' class="hl"':'')+'><td>'+s.element+(isMine?'【命】':"")+(isPref?'【选】':"")+'</td><td style="text-align:left">'+s.name+'</td>'+
    '<td>'+s.start.slice(0,4)+'至'+s.end.slice(0,4)+'</td><td>'+fmt(s.mean1_bp)+'</td><td>'+fmt(s.mean0_bp)+'</td>'+
    '<td>'+fmt(s.t,2)+'</td><td>'+s.p.toFixed(3)+'</td><td>'+s.verdict+'</td></tr>';
  }).join("");
  return '<div class="card fadein" id="id-card-sector"><h3><span>五行行业帖　命属何行 宜何生意</span>'+
    '<span style="font-size:12.5px;color:#6f6353">五行年份中该行业指数日均收益 vs 其余年份（Welch t 检验）</span></h3>'+
    '<table class="st num"><tr><th>五行</th><th style="text-align:left">代表行业指数</th><th>样本</th><th>五行年 bp/日</th><th>其余 bp/日</th><th>t</th><th>p</th><th>裁决</th></tr>'+rows+'</table>'+
    '<div class="vd">【命】为客官年命五行（'+p.nayin_element+'）'+(pref?'，【选】为问卷所偏之行（'+pref+'）':'')+'。勘验：五行选行业之说，五路皆不验，行业涨跌不由生克。帖上五行对照，权当认识行业板块的地图。</div></div>';
}

/* ---------- 本命合参（生辰×问卷 专属策略） ---------- */
function birthCard(result){
  const p=result.profile;
  const ws=result.titles?result.titles.wang_shuai:wangShuai(p.nayin_element,p.birth_month);
  const rule=TDATA.birthRule[ws];
  const ruleWY=rule.wenyan.replace(/\{animal\}/g,p.animal).replace(/\{window\}/g,"5");
  const info=result.questionnaire.info;
  const pos=info.xuan_pos!=null?info.xuan_pos:0.5;
  const posN=info.xuan_pos_name||TDATA.posName[String(pos)]||"半仓";
  const test=result.tests.filter(t=>t.key===rule.family)[0]||result.tests[0];
  const maps=personalMasksAndKeys(p);
  const m=maps.filter(x=>x[0]===rule.family)[0];
  const AVOID={retro:1,digit:1,animal:1};
  const rawMask=m?m[2]:null;
  const mask=(rawMask&&AVOID[rule.family])?rawMask.map(x=>!x):rawMask;
  let chart="",stTotal=null,btTotal=null;
  if(mask&&D){
    const an=Object.assign({q1:"B",q2:null,q3:"A",q4:"D",q5:"B",q6:"C"},result.questionnaire.answers);
    const bh=curveBehavior(an,ws,mask);
    const cb=curve(rawMask||mask);
    stTotal=bh.total;btTotal=cb[1][cb[1].length-1];
    chart=curveSvgLog([
      {a:downsample(cb[1]),color:"#5a7a6e",w:1.6,op:.9,label:"持有不动"},
      {a:downsample(bh.curve),color:"#c23b2e",w:2.4,label:"本命合参"}],
      {rug:mask,nHeld:mask.filter(Boolean).length,nTotal:D.jd.length});
    chart+='<div class="legend"><i style="border-color:#c23b2e"></i>本命合参（命格点主策的允许日 x 你的六答行为规则）<i style="border-color:#5a7a6e"></i>持有不动（上证指数买入持有）</div>';
  }
  const parts=String(test.strategy||"").split(/[：:]/);
  return '<div class="card fadein" id="id-card-birth"><h3><span>本命合参　生辰×问卷 专属策略</span>'+
    '<span class="badge b-ins">'+TDATA.prefixName[ws]+'之策</span></h3>'+
    '<div class="moral" style="font-family:var(--ft-kai);letter-spacing:1px">命理依据：'+ruleWY+'</div>'+
    '<div class="dvh">'+rule.bai+'。持仓时段由生辰定，仓位由问卷定（客官答'+posN+'），这正是生日出掩码 答卷出仓位的合参。</div>'+
    (test.strategy?'<div class="claim" style="border-left:3px solid #3d4a52;background:#eef0e6;padding:4px 10px;margin:8px 0">主打策略：'+parts[0]+'（'+(parts[1]||"按此说法择日持有")+'）　押'+posN+'仓 终值 <b style="color:#c23b2e">'+fmt(stTotal,2)+'</b> vs 持有不动 <b>'+fmt(btTotal,2)+'</b></div>':"")+
    chart+
    '<div class="vd">勘验：本命之策仍是玄学，检验结果与第'+(result.tests.indexOf(test)+1)+'问同宗：'+test.verdict_text+'</div>'+
    (test.verdict_bai?'<div class="dvh">'+test.verdict_bai+'</div>':'')+
    '<div class="vd" style="margin-top:4px;color:#3d4a52">合参之法：旺相休囚死点主策（旺 星座 相 生月 休 节气 囚 幸运日 死 本命年），仓位取问卷第六答。命理出何时，客官出多少，乘起来，掷到三十余年真实行情上。</div></div>';
}

/* ---------- 称号与图鉴 ---------- */
const COLL_KEY="sxsg_collection_v1";
function loadColl(){try{return JSON.parse(localStorage.getItem(COLL_KEY)||"[]");}catch(e){return[];}}
function saveCollIds(ids){try{localStorage.setItem(COLL_KEY,JSON.stringify(ids));}catch(e){}}
const EGG_DEFS=@@EGGS@@;
function allTitleIds(){const t=TDATA,out=[];
  t.prefixOrder.forEach(w=>out.push("P:"+t.prefixName[w]));
  Object.keys(t.main).forEach(k=>out.push("M:"+t.main[k][0]));
  EGG_DEFS.forEach(e=>out.push("E:"+e[0]));
  Object.keys(t.figures).forEach(n=>out.push("F:"+n));return out;}

function computeTitlesJS(p,info,sigCount){
  const T=TDATA,el=p.nayin_element;
  const ws=wangShuai(el,p.birth_month),prefix=T.prefixName[ws];
  const season=seasonOf(p.birth_month);
  const reasons=["年命"+p.nayin+"属"+el+"，生于"+season+"季（"+SEASON_ELEMENT[season]+"旺之时），五行处"+ws+"地，故得前缀"+prefix+""];
  if(T.prefixBai&&T.prefixBai[ws])reasons.push(T.prefixBai[ws]);
  const sig=sigCount>0;
  const mainArr=T.main[info.style+"|"+(sig?1:0)];
  const main=mainArr[0];
  reasons.push("问卷风格"+info.style+"，七问"+(sig?"有似验项":"全无不验")+"，故授主称号"+main+"："+mainArr[1]);
  if(mainArr[2])reasons.push(mainArr[2]);
  const eggs=[];
  if(info.leverage)eggs.push("杠杆仙人");
  if(info.element_pref){const rel=shengKe(el,info.element_pref);
    if(rel==="我克")eggs.push("偏财入手");else if(rel==="克我")eggs.push("迎难而上");
    else if(rel==="生我")eggs.push("顺风顺水郎");else if(rel==="比和")eggs.push("本命同行");}
  if(p.birth_day===29&&p.birth_month===2)eggs.push("四载一逢客");
  if(p.animal==="羊")eggs.push("辟谣锦羊");
  if(p.animal==="龙"&&info.style==="进取")eggs.push("飞龙在天");
  if(p.jieqi.name==="冬至"||p.jieqi.name==="夏至")eggs.push("阴阳至人");
  if(ws==="死"&&info.style==="保守")eggs.push("死地逢生");
  if(ws==="旺"&&info.style==="进取")eggs.push("烈火烹油");
  if(info.element_pref==="火"&&info.style==="保守")eggs.push("隔空对冲");
  for(const en of eggs){const def=EGG_DEFS.find(e=>e[0]===en);
    if(def)reasons.push("彩蛋"+en+"："+def[1]);}
  return{prefix:prefix,main:main,eggs:eggs,full:prefix+"　"+main,reasons:reasons,wang_shuai:ws,season:season};
}

function computeFigureJS(an,info,p,ws){
  const F=TDATA.figures;
  const pick=n=>Object.assign({name:n},F[n]);
  if(info.leverage)return pick("吕不韦");
  if(an.q1==="A")return pick("刘备");
  if(an.q1==="B")return pick("万历");
  if(an.q1==="C"&&an.q3==="A")return pick("范蠡");
  if(an.q1==="C")return pick("项羽");
  if(an.q3==="A")return pick("范蠡");
  if(an.q3==="B"&&info.style==="进取")return pick("汉武帝");
  if(an.q5==="A")return pick("崇祯");
  if(info.style==="保守"&&(an.q5==="C"||ws==="囚"))return pick("司马懿");
  if(ws==="死"&&an.q3==="B")return pick("武则天");
  if(p.animal==="龙"&&info.style==="进取")return pick("秦始皇");
  if(an.q4==="B")return pick("白圭");
  if(an.q4==="A")return pick("和珅");
  if(an.q4==="C")return pick("诸葛亮");
  if(an.q4==="D")return pick("苏轼");
  if(info.style==="中庸")return pick("唐太宗");
  if(info.style==="保守")return pick("汉文帝");
  return pick("王莽");
}
function figureEggsJS(an,info,p,ws){
  const F=TDATA.figures,eggs=[];
  const hit=n=>eggs.push(Object.assign({name:n},F[n]));
  if(ws==="死"&&info.style==="进取")hit("朱元璋");
  if(an.q1==="A"&&an.q3==="B")hit("武则天");
  if(info.style==="进取"&&an.q5==="A")hit("霍去病");
  if(an.q4==="A"&&info.style==="进取")hit("曹操");
  if(an.q3==="A"&&an.q5==="D")hit("张良");
  if(info.style==="保守"&&an.q4==="D")hit("萧何");
  if(an.q2==="金"&&an.q4==="A")hit("胡雪岩");
  if(an.q2==="金"&&an.q3==="B")hit("沈万三");
  return eggs;
}
function figureCard(result,interactive){
  const f=result.figure;if(!f)return"";
  const eggs=result.figure_eggs||[];
  if(interactive&&!result.questionnaire.answers.defaulted){
    const got=loadColl();
    ["F:"+f.name].concat(eggs.map(e=>"F:"+e.name)).forEach(c=>{if(!got.includes(c))got.push(c);});
    saveCollIds(got);
  }
  const eggHtml=eggs.map(e=>'<div class="eggrow"><span class="ename">'+e.dyn+'·'+e.name+'（'+e.tag+'）</span>　<span style="font-size:13px;color:#6f6353">'+e.like+'。'+e.fate+'</span>'+
    (e.bai_like?'<div class="dvh" style="margin-top:2px">'+e.bai_like+'</div>':"")+'</div>').join("");
  return '<div class="card fadein" id="id-card-figure"><h3><span>前生同路　'+f.dyn+'·'+f.name+'</span><span class="badge b-sig">'+f.tag+'</span></h3>'+
    '<div class="stampbox"><div class="stamp anim" style="padding:12px 26px"><span class="sp2" style="font-size:32px">'+stampChars(f.name)+'</span></div></div>'+
    '<div class="moral">为何像客官：'+f.like+'。</div>'+
    (f.bai_like?'<div class="dvh">'+f.bai_like+'</div>':"")+
    '<div class="moral2">'+f.fate+'。</div>'+
    (f.bai_fate?'<div class="dvh">'+f.bai_fate+'</div>':"")+
    (eggs.length?'<div style="margin-top:8px;font-family:var(--ft-kai);letter-spacing:2px;color:#6f6353">前尘旁证</div>'+eggHtml:"")+
    '<div class="vd" style="margin-top:8px">人物由答卷组合与命格属性匹配（规则如上），判词皆取史实，娱乐为表，风控为里。</div></div>';
}
function titleCard(result,interactive){
  const t=result.titles;
  const eggs=t.eggs.map(en=>{const def=EGG_DEFS.find(e=>e[0]===en);
    return '<div class="eggrow"><span class="ename">'+en+'</span>　<span style="font-size:13px;color:#6f6353">'+(def?def[1]:"")+'</span></div>';}).join("");
  let coll="";
  if(interactive){
    const ids=allTitleIds();
    let got=loadColl();
    if(!result.questionnaire.answers.defaulted){ // 默认占位不入图鉴
      const cur=["P:"+t.prefix,"M:"+t.main].concat(t.eggs.map(e=>"E:"+e));
      cur.forEach(c=>{if(!got.includes(c))got.push(c);});saveCollIds(got);}
    const pct=Math.round(got.length/ids.length*100);
    const chips=ids.map(id=>'<span class="'+(got.includes(id)?"got":"")+'">'+id.slice(2)+'</span>').join("");
    const code=btoa(unescape(encodeURIComponent(JSON.stringify(got))));
    coll='<div class="coll"><div class="colltext">称号图鉴　已集 <b style="color:#c23b2e">'+got.length+'</b> / '+ids.length+'　换个生辰 换个答法 称号不同</div>'+
      '<div class="collbar"><div style="width:'+pct+'%"></div></div>'+
      '<div class="collchips">'+chips+'</div>'+
      '<div class="crow"><button onclick="copyCode()">复制图鉴存档码</button>'+
      '<input id="codein" placeholder="粘贴存档码可跨设备恢复图鉴">'+
      '<button onclick="restoreCode()">恢复图鉴</button></div>'+
      '<textarea id="codeout" rows="2" readonly>'+code+'</textarea></div>';
  }
  return '<div class="card fadein" id="id-card-title"><h3><span>称号既定　谢知夏用印</span></h3>'+
    '<div class="stampbox"><div class="stamp anim"><span class="sp1">'+stampChars(t.prefix)+'</span><span class="sp2">'+stampChars(t.main)+'</span></div></div>'+
    (t.eggs.length?'<div style="text-align:center;color:#6f6353;font-size:13px;margin-top:4px">另有彩蛋称号 '+t.eggs.length+' 枚</div>'+eggs:"")+
    '<ol class="reasons">'+t.reasons.map(r=>"<li>"+r+"</li>").join("")+'</ol>'+coll+
    '<div class="vd" style="margin-top:8px">称号由真命理规则（旺相休囚死 五行生克）与问卷选择、统计结果共同裁定，规则透明，缘由如上。娱乐为表，统计为里。</div></div>';
}
function copyCode(){const t=document.getElementById("codeout");t.select();
  if(navigator.clipboard)navigator.clipboard.writeText(t.value);
  try{document.execCommand("copy");}catch(e){}
  alert("存档码已复制，发给朋友或存好即可恢复图鉴");}
function restoreCode(){const v=document.getElementById("codein").value.trim();
  try{const ids=JSON.parse(decodeURIComponent(escape(atob(v))));
    if(!Array.isArray(ids))throw 0;
    const valid=allTitleIds();
    const merged=[...new Set(loadColl().concat(ids.filter(i=>valid.includes(i))))];
    saveCollIds(merged);alert("图鉴已恢复，共 "+merged.length+" / "+valid.length);
    location.reload();}catch(e){alert("存档码无效，请检查是否复制完整");}}

function testsHtml(result){
  return result.tests.map((t,i)=>testCard(t,t.curves,"id-q-"+i,{rug:t.rugMask,nTotal:t.rugMask?t.rugMask.length:null,posName:result.questionnaire&&result.questionnaire.info&&result.questionnaire.info.xuan_pos_name})).join("");
}
function renderAll(result,scans,dialog,interactive){
  const root=document.getElementById("report");
  const p=result.profile;
  const HUI=document.getElementById("hui-tpl").innerHTML;
  let h='<div class="wrap">';
  h+='<div class="couplet l">生辰入铺来 六问答心性</div><div class="couplet r">统计作镜台 七问勘玄机</div>';
  h+='<div id="dyn-quiz">'+quizCard(result)+'</div>';
  h+='<div class="card fadein" id="id-profile" style="text-align:center"><div style="font-family:var(--ft-kai);font-size:16px;letter-spacing:3px;color:#6f6353">生辰命帖　<span style="color:#93866f;font-size:13px">仅作勘验素材</span></div>'+
    '<div style="font-family:var(--ft-kai);font-size:15px;margin:4px 0">客官生于 <b style="color:var(--verm);font-size:18px;letter-spacing:2px">'+p.birthday+'</b></div><div style="margin-top:6px">'+
    '<span class="chip">星座 <b>'+p.constellation+'</b></span><span class="chip">生肖 <b>'+p.animal+'</b>（'+p.ganzhi+'年）</span>'+
    '<span class="chip">年命纳音 <b>'+p.nayin+'</b>（'+p.nayin_element+'命）</span>'+
    '<span class="chip">农历生日 <b>'+p.lunar.month+'月'+p.lunar.day+'</b>'+(p.lunar.is_leap?"（闰月）":"")+'</span>'+
    '<span class="chip">出生节气 <b>'+p.jieqi.name+'</b>（其后'+p.jieqi.days_after+'天）</span></div>'+
    '<div style="font-size:12px;color:#93866f;margin-top:8px">'+p.note+'</div></div>';
  h+='<h2 class="sec" id="id-sec-q">坊间七问<small>'+result.meta.start+' 至 '+result.meta.end+'，'+result.meta.n_days.toLocaleString()+' 个交易日，玄学组对对照组日均收益 Welch t 检验（双尾，5% 水平），黄历 水逆 月相 本命年 节气 数字 三合，全是市面上最通行的说法</small></h2>'+HUI;
  h+='<div id="dyn-tests">'+testsHtml(result)+'</div>';
  h+='<div class="verdict-big fadein" id="id-sec-verdict"><div class="vt">勘验结论</div>'+
    '<div class="moral">七问之中：'+result.summary.n_null+' 问不验，'+result.summary.n_significant+' 问似验，'+result.summary.n_insufficient+' 问数不足。'+
    (result.summary.n_significant>0?'似验之项，到了遍试诸日一章，自会被多重比较打回原形。':'命理之说，于行情无所应验。')+'</div>'+
    '<div class="moral2">客官生辰所带的属性，与大盘涨跌之间，未见经得起统计检验的稳定关系。民间说法之准，多半是幸存者偏差与数据挖掘的错觉，此即本铺以数据说清之事。</div>'+
    '<div class="dvh">图底朱砂条带是每条策略真实持仓的每一天（黄历约每三天持一天、月相约持半个月，全是连续或高频持仓，绝非只回测一天）；策略线看着平，是因为按玄学操作真的赚不到钱，同期拿住不动有三十三倍。</div></div>';
  h+='<h2 class="sec" id="id-sec-inter">合参殿 五行帖 称号印 前生影<small>命理选时段 问卷出仓位 真金白银回测 盖印颁称号 史册寻同路</small></h2>'+HUI;
  h+='<div id="dyn-birth">'+birthCard(result)+'</div>';
  h+='<div id="dyn-strategy">'+strategyCard(result)+'</div>';
  h+='<div id="dyn-sector">'+sectorCard(result)+'</div>';
  h+='<div id="dyn-title">'+titleCard(result,interactive)+'</div>';
  h+='<div id="dyn-figure">'+figureCard(result,interactive)+'</div>';
  const mine={day:String(p.birth_day),month:String(p.birth_month),animal:p.animal,element:p.nayin_element,jieqi:p.jieqi.name};
  if(interactive){
    h+='<h2 class="sec" id="id-sec-wall">遍试诸日<small>建除十二神之墙　黄历吉凶值日全试一遍，看择日如何凭空而生</small></h2>'+HUI;
    const dw=scans.find(x=>x.family==="jianchu");
    if(dw)h+=wallBlock(dw,null);
  }else{
    h+='<h2 class="sec" id="id-sec-wall">遍试诸日<small>p 值之墙　把每个取值都试一遍，看命运如何凭空而生</small></h2>'+HUI;
    for(const sc of scans)h+=wallBlock(sc,mine[sc.family]);
    h+='<h2 class="sec" id="id-sec-classic">典籍对照<small>正经典籍上的日历效应，同法勘验，也不轻纵</small></h2>'+HUI;
    result.classic.forEach((t,k)=>h+=testCard(t,t.curves,"id-c-"+k));
  }
  h+='<div class="foot" id="id-foot">'+result.disclaimer+'<br>数据：'+result.meta.index+'（'+result.meta.start+' 至 '+result.meta.end+'）　行业：中证银行 中证白酒 中证军工 中证医药 房地产　方法：Welch t 检验，Bonferroni 校正　主角：谢知夏（虚构人物）</div>';
  h+='</div>';
  root.innerHTML=h;
  attachWallTips(scans);
  if(dialog){document.querySelectorAll("#report .card,#report h2.sec,#report .verdict-big,#report .foot")
    .forEach(x=>x.classList.add("veiled"));}
  window.__RESULT=result;
}

function refreshDynamic(result,interactive){
  document.getElementById("dyn-quiz").innerHTML=quizCard(result);
  document.getElementById("dyn-birth").innerHTML=birthCard(result);
  document.getElementById("dyn-strategy").innerHTML=strategyCard(result);
  document.getElementById("dyn-sector").innerHTML=sectorCard(result);
  document.getElementById("dyn-title").innerHTML=titleCard(result,interactive);
  document.getElementById("dyn-figure").innerHTML=figureCard(result,interactive);
  document.querySelectorAll("#dyn-quiz .card,#dyn-birth .card,#dyn-strategy .card,#dyn-sector .card,#dyn-title .card,#dyn-figure .card")
    .forEach(x=>x.classList.add("veiled"));
}
"""


# ================================================================ 对话剧场 ==
def _dialogue_js() -> str:
    return r"""
const CN7=["一","二","三","四","五","六","七"];
const DGC=["零","一","二","三","四","五","六","七","八","九"];
function cnInt(n){n=Math.round(n);if(n<0)return"负"+cnInt(-n);
  if(n<10)return DGC[n];if(n<20)return"十"+(n%10?DGC[n%10]:"");
  return DGC[Math.floor(n/10)]+"十"+(n%10?DGC[n%10]:"");}
function cnDec(x){const s=Math.abs(x).toFixed(1).split(".");
  return (x<0?"负":"")+cnInt(+s[0])+"点"+DGC[+s[1]];}
function pCN(p){if(p==null)return"无从算起";
  if(p<0.005)return"不足半厘";
  const s=(p<0.1?p.toFixed(3):p.toFixed(2)).split(".");
  return"零点"+s[1].split("").map(c=>DGC[+c]).join("");}

const ANSWERS={q1:null,q2:null,q3:null,q4:null,q5:null,q6:null};
const DLG={beats:[],i:-1,typing:null,done:false,onChoices:null};

function b0(){
  const B=[];
  B.push({text:"（拱手）客官留步。小女子谢知夏，康熙年间钦天监里观星记历的小吏，一梦三百年，醒在这A股营业部，今日开张。开张第一件事不是算命，先请客官报上生辰，夏某写好命帖，再问你六句话：命理是天定的，答话是你自己定的。答完，夏某合参二者排出策略、掷于真行情验之，末了颁称号、寻前生。",
          vh:"谢知夏先拿到你的生日（用于推导星座、生肖、节气等命理属性），再问你六个投资习惯问题；然后把生日定的持仓时段 × 你答的仓位合成专属策略，用三十多年真实行情回测检验，最后给你颁奖和匹配一位历史人物。"});
  for(let i=0;i<6;i++)B.push({choice:i});
  return B;
}
function b1(result){
  const p=result.profile,T=result.tests;
  const info=result.questionnaire.info;
  const posN=info.xuan_pos_name||"半仓";
  const B=[];
  const b=(text,act,vh)=>B.push({text:text,act:act,vh:vh});
  b("答卷收讫。客官这性子，"+info.style+"，玄学仓位肯押"+posN+(info.element_pref?"，偏爱"+info.element_pref+"行生意":"")+(info.leverage?"，竟还要加杠杆（夏某记下了，待会儿有话要说）":"")+"。命帖在此，七问开斩，每一问都是一条明说的策略，夏某按客官的仓位真金白银回测。","id-sec-quiz",
    "你的答题定出了投资风格与仓位；接下来七个检验，每个都绑定一条具体策略，回测时按你答的仓位计算。");
  b("星座"+p.constellation+"，属"+p.animal+"，"+p.ganzhi+"年"+p.nayin+"，农历"+p.lunar.month+"月"+p.lunar.day+"，生于"+p.jieqi.name+"之后，命帖写就，句句只作勘验素材。","id-profile|id-sec-q",
    "这些属性全部由程序从生日自动推导（星座按日期，生肖纳音按农历年干支，节气按天文历法表），仅作检验素材。");
  T.forEach((t,i)=>{
    const v=t.verdict==="significant"?"似验":(t.verdict==="insufficient"?"数不足":"不验");
    const parts=String(t.strategy||"").split(/[：:]/);
    const sname=parts[0]||"",srule=parts[1]||"";
    const sp=t.strat_total_bih!=null?t.strat_total_bih:t.strat_total_pos,sf=t.strat_total_full;
    let tail;
    if(v==="似验")tail="咦，似验。先记下，容后再表。";
    else if(v==="数不足")tail="数不足，勘不得。";
    else tail="不验，此策略废。";
    b("第"+CN7[i]+"问 策略"+sname+"，"+srule+"。夏某把此信号与客官的加减仓规则合体模拟：终值 "+(sp!=null?sp.toFixed(2):"无从算起")+(sf!=null?"（满仓照做 "+sf.toFixed(2)+"）":"")+"，持有不动三十三倍，p 值 "+pCN(t.p)+"，"+tail,
      "id-q-"+i+"|tg:"+i,
      "红线即玄学信号与你的规则合体：信号允许的日子才可持仓，押多少 怎么加减仓全按你的六答。"+(v==="似验"?"这一问 p 值碰巧小于 0.05，别激动，压轴再算总账。":(v==="数不足"?"满足说法的交易日太少，统计下不了结论。":"p 值远大于 0.05，说法不成立，合体也白搭。")));
  });
  b("七问已毕：不验 "+result.summary.n_null+"，似验 "+result.summary.n_significant+"，数不足 "+result.summary.n_insufficient+"。"+(result.summary.n_significant>0?"似验之项（如水逆）先莫欢喜，本铺前后试了百余种说法，纯凭运气也当撞出几个显著，压轴墙前自见分晓。":"七个玄学策略，全军尽没，客官且看勘验结论，夏某再行合参。"),"id-sec-verdict|tg:7",
    ""+(result.summary.n_significant>0?"有一两条 p 值小于 0.05（水逆就是），但试的说法一多必有假阳性，别急着当真，压轴的建除十二神墙会演示这个道理。":"七条策略没有一条跑赢拿住不动；图底朱砂条带是每条策略真实持仓的日子。"));
  return B;
}

function b2(result){
  const p=result.profile,info=result.questionnaire.info,t=result.titles;
  const posN=info.xuan_pos_name||"半仓";
  const B=[];
  const b=(text,act,vh)=>B.push({text:text,act:act,vh:vh});
  b("（铺开合参卷）七问既验，夏某行合参之法，观客官命格五行处"+t.wang_shuai+"地，点七问之一为你本命之策，再乘你自答的"+posN+"仓位，这便是生辰与心性合出的专属策略。成色如何，卷上见。","id-sec-inter|id-card-birth",
    "本命合参卡=命理决定何时持仓+问卷决定押多少仓。无论怎么合，检验结果与对应那问一样：不灵。");
  const behT=(D&&result.questionnaire&&result.questionnaire.answers&&!result.questionnaire.answers.defaulted)?curveBehavior(result.questionnaire.answers,t.wang_shuai).total.toFixed(2):(result.strategy&&result.strategy.behavior?result.strategy.behavior.total.toFixed(2):null);
  b("再看策略殿。夏某把客官六答写成真实的加减仓规则，逐日放到三十五年行情里跑了一遍，这便是你的行为策略：终值 "+(behT||"见卷")+"，持有不动是三十三倍。玄学信号取黄历宜日，分守拙 中庸 进取三档同场对比，终值皆在原地打转。"+(info.leverage?"至于加杠杆……杠杆仙人，夏某把印都给你刻好了，劝退二字也刻在上面。":"客官若问夏某的策略？纪律定投指数，别听算命的。"),"id-card-strat",
    "行为策略就是把你的答题变成真实规则：浮亏怎么办、浮盈怎么办、离场多久回来、入场押几成，全部按卷上规则逐日模拟，盈亏如实呈上；玄学三档则任选一档都赢不了拿住不动。");
  b("五行行业帖。金木水火土各行其市，夏某已逐一勘验，客官命属"+p.nayin_element+(info.element_pref?"，问卷偏爱"+info.element_pref+"行":"")+"，高亮之处自行观瞧：五路皆不验，行业涨跌不由生克。","id-card-sector",
    "用五行年份对照五个真实行业指数，同样做统计检验，没有一个行业的行情跟着五行走。");
  b("（取出朱印）勘验既毕，称号既定，"+t.prefix+"　"+t.main+""+(t.eggs.length?"，另有彩蛋"+t.eggs.join("")+"":"")+"。缘由卷中写得明白：真命理规则、问卷选择、统计结果，一条不昧。盖印！","id-card-title",
    "称号前缀按真命理旺相休囚死规则由你的五行与出生季节裁定，主称号由问卷风格与检验结果裁定，缘由逐条写在卡片里。");
  const f=result.figure;
  b("（再取一卷）末一桩，夏某翻遍史册，替客官寻了位前生同路人。客官这路数，最像【"+f.dyn+"·"+f.name+"】，"+f.like+"。"+f.fate+"。"+((result.figure_eggs&&result.figure_eggs.length)?"卷中另有旁证：【"+result.figure_eggs.map(e=>e.name).join("】【")+"】的影子也在你答卷里，同一习惯，古人早替你试过结局。":"")+"图鉴在手，换个生辰换个答法，又是别番称号与同路人，客官不妨再访。","id-card-figure",
    "人物由问卷组合与命格属性共同匹配（规则写在卡片里），判词取自教科书级史实；想集齐 47 枚图鉴，就换生日和答法多来几次。");
  return B;
}
function b3(result,scans){
  const dw=scans.find(s=>s.family==="jianchu");
  const sigNames=dw.sig_raw.map(k=>""+k+"值日").join("与");
  const B=[];
  const b=(text,act,vh)=>B.push({text:text,act:act,vh:vh});
  b("客官且留步，还有压轴一手。水逆一问名义似验，正好拿它祭旗，夏某把黄历建除十二神每个值日都当吉日试一遍，十二试，看择日如何凭空而生。看，"+(sigNames?sigNames+"，朱砂高柱，名义显著。若只给客官看这几根柱子，是不是就要专挑这几个值日开仓了？":"十二值日竟无一柱过线，倒是干净。")+"然十二试（连同本铺前后百余试），纯凭运气亦当撞出几个假灵，墨色校正线之上，方作得数。结果："+(dw.n_sig_adj>0?"竟有个别存留，客官好造化，不过夏某仍要再验":"尽数落线，无一幸免")+"。","id-sec-wall|id-wall-jianchu",
    "12 根柱子对应把每个建除值日都检验一遍；总有几根碰巧 p 值小于 0.05，但过 Bonferroni 校正线的：0 根。水逆那个 p=0.03 也是同样的道理，单看一个 p 值不算数。");
  b("至于节气、生肖、五行、月相诸墙，与月末月初、周四魔咒诸典籍之验，卷宗里有档，结论一样：不过线。（合卷）以统计为镜，方不为玄学所惑。卷宗在后，称号在怀，临别一言："+result.disclaimer,"__all__",
    "完整检验档案在页面下方与勘验卷宗里；本铺用统计方法检验民间说法，坚持弘扬科学精神，不构成任何投资建议。");
  return B;
}

function dlReveal(act){
  if(act==="__all__"){document.querySelectorAll(".veiled").forEach(x=>x.classList.remove("veiled"));return;}
  String(act).split("|").forEach(part=>{
    if(part.indexOf("tg:")===0){lightTrigram(+part.slice(3));return;}
    const node=document.getElementById(part);if(!node)return;
    node.classList.remove("veiled");
    node.scrollIntoView({behavior:"smooth",block:"center"});
    node.classList.remove("spot");void node.offsetWidth;node.classList.add("spot");
  });
}
function dlType(text,vh){
  const box=document.getElementById("dtext");
  box.innerHTML='<span class="tt"></span><span class="cursor"></span>';
  const tt=box.querySelector(".tt");let i=0;
  const doneType=()=>{const c=box.querySelector(".cursor");if(c)c.remove();
    if(vh){const d=document.createElement("div");d.className="dvh";d.textContent=vh;box.appendChild(d);}
    DLG.typing=null;};
  return new Promise(res=>{const iv=setInterval(()=>{tt.textContent=text.slice(0,++i);
    if(i>=text.length){clearInterval(iv);doneType();res();}},26);
    DLG.typing={fin(){clearInterval(iv);tt.textContent=text;doneType();res();}};});
}
function dlShowChoices(qi){
  const q=TDATA.questionnaire[qi];
  DLG.awaiting=true;
  const box=document.getElementById("dtext");
  const btns=q.options.map(o=>'<button data-v="'+o[0]+'">'+o[0]+'　'+o[1]+'</button>').join("");
  box.innerHTML='<div style="font-family:var(--ft-kai);letter-spacing:1px">'+q.question+'</div><div class="opts">'+btns+'</div>';
  document.getElementById("dnext").style.display="none";
  box.querySelectorAll(".opts button").forEach(btn=>{
    btn.onclick=e=>{e.stopPropagation();
      document.getElementById("dnext").style.display="";
      ANSWERS[q.key]=btn.dataset.v;
      DLG.awaiting=false;
      if(ANSWERS.q1&&ANSWERS.q2&&ANSWERS.q3&&ANSWERS.q4&&ANSWERS.q5&&ANSWERS.q6&&typeof applyAnswers==="function")applyAnswers(window.__RESULT);
      dlNext();};
  });
}
async function dlNext(){
  if(DLG.done||DLG.awaiting)return;
  if(DLG.typing){DLG.typing.fin();return;}
  DLG.i++;
  if(DLG.i>=DLG.beats.length){dlFinish();return;}
  const bt=DLG.beats[DLG.i];
  if(bt.choice!=null){dlShowChoices(bt.choice);return;}
  if(bt.act)dlReveal(bt.act);
  await dlType(bt.text,bt.vh);
}
function dlFinish(){
  if(DLG.done)return;
  DLG.done=true;
  document.querySelectorAll(".veiled").forEach(x=>x.classList.remove("veiled"));
  const st=document.getElementById("stage");
  st.classList.add("bye");
  setTimeout(()=>st.style.display="none",700);
  const pb=document.getElementById("pb");if(pb)pb.classList.add("hide");
  window.scrollTo({top:0,behavior:"smooth"});
}
function startDialogue(result,scans){
  DLG.beats=b0();
  DLG.i=-1;DLG.done=false;
  DLG.onChoices=null;
  const st=document.getElementById("stage");
  st.style.display="";st.classList.remove("bye");
  document.getElementById("dbox").onclick=e=>{
    if(e.target.closest("button"))return;dlNext();};
  document.getElementById("dnext").onclick=()=>dlNext();
  document.getElementById("dskip").onclick=()=>{dlFinish();};
  dlNext();
}
"""


# ================================================================ 两个入口 ==
def _eggs_json() -> str:
    eggs = [
        ("杠杆仙人", "谢知夏苦劝：杠杆之下，神仙难救"),
        ("偏财入手", "所选行业五行为年命所克，命书曰我克者为财"),
        ("迎难而上", "所选行业五行克年命，官杀压顶，客官偏选它"),
        ("顺风顺水郎", "所选行业五行生年命，如母护子"),
        ("本命同行", "所选行业与年命同五行，并肩而行"),
        ("四载一逢客", "生辰四载一逢，稀客稀客"),
        ("辟谣锦羊", "属羊命苦一说统计已辟，客官自带辟谣体质"),
        ("飞龙在天", "属龙又进取，飞龙在天，慎防亢龙有悔"),
        ("阴阳至人", "生于阴阳之至，天地气机转换之客"),
        ("死地逢生", "命处死地，却选保守，以守为生"),
        ("烈火烹油", "当令又进取，烈火烹油之局，夏某劝稳"),
        ("隔空对冲", "性子保守，偏爱烈火，精神对冲"),
    ]
    return json.dumps(eggs, ensure_ascii=False, separators=(",", ":"))


def build() -> None:
    mk = lab.Market()
    print("预计算全部属性检验……")
    stats = precompute(mk)
    meta = day_meta(mk)
    scans = [lab.scan_family(mk, f) for f in FAMILIES]
    strat_stats = lab.strategy_stats_for_web(mk)
    sectors = lab.sector_tests(mk)

    WEB.mkdir(parents=True, exist_ok=True)
    selftest(stats, meta)

    payload = {"stats": stats, "meta": meta, "scans": scans,
               "strat": strat_stats, "sectors": sectors, "TDATA": titles_data(),
               "metaInfo": {"start": mk.dates[0].isoformat(), "end": mk.dates[-1].isoformat(),
                            "n_days": len(mk.dates),
                            "method": "玄学组对对照组 日均收益 Welch t 检验（双尾） 显著性水平 5%",
                            "index": "上证指数（000001.SH）收盘价",
                            "disclaimer": lab.DISCLAIMER}}
    selftest_rules(payload["TDATA"], meta)

    form = """
<header>
  <div class="brand"><span class="seal lg">知<br>夏</span><h1 class="site">生辰算股</h1><span class="seal lg" style="transform:rotate(4deg)">勘<br>验</span></div>
  <div class="sub">谢知夏的统计学算命铺</div>
  <div class="lore">康熙年间钦天监小吏谢知夏 一梦三百年 醒在A股营业部<br>今日开张 以统计为镜 替客官勘验命理说法 生辰合问卷 六问答心性 卷终颁称号 寻前生</div>
  <div class="notice">@@DISC@@</div>
</header>
<div class="wrap">
<div class="formbox" id="formbox">
  <div class="fb-title">输入生辰 开始勘验</div>
  <div class="fb-sub">生辰定命格 六问定仓位 坊间七问验真章</div>
  <div class="fb-lore">谢知夏把市面上最通行的玄学炒股说法，黄历宜忌 水星逆行 满月效应 本命年 节气变盘 数字禁忌 三合流年，逐条掷于 @@NDAYS@@ 个真实交易日之上，灵与不灵，统计说了算。再答她六问，命理与心性合参成策略，回测、称号、前生同路人一一奉上。</div>
  <div>
    <select id="by"></select>年 <select id="bm"></select>月 <select id="bd"></select>日
  </div>
  <button class="go" onclick="run()">开始勘验</button>
  <div class="fb-note">支持 1900 至 2012 年生人（生辰仅用于推导命理属性 不上传 不留存）</div>
</div>
</div>
<div id="report"></div>
<div id="stage" style="display:none"><div class="stage-in">
  <div class="dbox" id="dbox">
    <div class="avatar"><div class="bgring" id="av-ring"></div><svg class="sfig" viewBox="0 0 100 100" aria-label="谢知夏侧影">
      <circle cx="50" cy="50" r="48" fill="#f6efdc" stroke="#c9b88b" stroke-width="1.5"/>
      <circle cx="50" cy="50" r="43.5" fill="none" stroke="#c9b88b" stroke-width=".8" opacity=".6"/>
      <path d="M28 88 Q36 62 50 60 Q64 62 72 88 Z" fill="#4a4239"/>
      <path d="M43 62 L50 70 L57 62 Q53 60 50 60 Q47 60 43 62 Z" fill="#f6efdc"/>
      <path d="M50 22 q8 0 10 8 q3 9 -1 15 q-2 4 -2 7 q4 2 3 4 q-4 3 -10 3 q-6 0 -10 -3 q-1 -2 3 -4 q0 -3 -2 -7 q-4 -6 -1 -15 q2 -8 10 -8 Z" fill="#4a4239"/>
      <circle cx="46" cy="29" r="7.5" fill="#4a4239"/>
      <line x1="52" y1="22" x2="66" y2="15" stroke="#c23b2e" stroke-width="2" stroke-linecap="round"/>
      <circle cx="66" cy="15" r="2.2" fill="#c23b2e"/>
    </svg><div class="aname">谢知夏</div></div>
    <div class="dname">谢知夏</div>
    <div class="dtext" id="dtext"></div>
    <div class="dctl"><button id="dskip">跳过对话</button><button id="dnext" class="next">继续</button></div>
  </div>
</div></div>
<div style="display:none" id="hui-tpl">@@HUI@@</div>
""".replace("@@DISC@@", lab.DISCLAIMER).replace("@@NDAYS@@", f"{len(mk.dates):,}").replace("@@HUI@@", _huiw_svg())

    page_js = CORE_JS + _render_js().replace("@@EGGS@@", _eggs_json()) + _dialogue_js() + _strat_tpl_js() + """
let DATA=""" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + """;
setMeta(DATA.meta);
const TDATA=DATA.TDATA;
(function fillForm(){
  const by=document.getElementById("by"),bm=document.getElementById("bm"),bd=document.getElementById("bd");
  for(let y=2012;y>=1900;y--)by.add(new Option(y,y));
  for(let m=1;m<=12;m++)bm.add(new Option(m+"月",m));
  for(let d=1;d<=31;d++)bd.add(new Option(d+"日",d));
})();
function jdOf(y,m,d){const ms=Date.UTC(y,m-1,d);return Math.round(ms/86400000)+25568;}

function wsOf(p){return wangShuai(p.nayin_element,p.birth_month);}
function buildResult(p){
  const S=DATA.stats;
  const maps=personalMasksAndKeys(p);
  const pos=(typeof ANSWERS!=="undefined"&&ANSWERS.q6)?TDATA.posOfAnswer[ANSWERS.q6]:0.5;
  const posN=(typeof ANSWERS!=="undefined"&&ANSWERS.q6)?TDATA.posName[String(TDATA.posOfAnswer[ANSWERS.q6])]:null;
  const famKey={almanac:["almanac","yi"],retro:["retro","r"],moon:["moon","w"],
    animal:["animal",p.animal],jieqi_all:["jieqi_all","a"],digit:["digit","d4"],sanhe:["sanhe",p.animal]};
  const AVOID={retro:1,digit:1,animal:1};     // 避险类：掩码=凶日 策略持有非凶日
  const inv=m=>m.map(x=>!x);
  const tests=maps.map(([key,title,mask])=>{
    const[ck,cv]=famKey[key];const t=Object.assign({},S[ck][cv]);
    t.title=title;t.strategy=STRAT_TPL[key](p);
    if(t.mean1_bp!=null){
      const hold=AVOID[key]?inv(mask):mask;
      const fp=curvePos(hold,pos),fpr=curvePos(inv(hold),pos),fh=curvePos(hold,1);
      const c=curve(mask);
      t.strat_total_pos=fp[fp.length-1];
      t.strat_total_pos_rev=fpr[fpr.length-1];
      t.strat_total_full=fh[fh.length-1];
      t.hold_n=hold.filter(Boolean).length;
      // 合体：玄学信号允许日 x 你的行为规则（红线）
      const realAn={q1:ANSWERS.q1||"B",q2:ANSWERS.q2,q3:ANSWERS.q3||"A",q4:ANSWERS.q4,q5:ANSWERS.q5||"B",q6:ANSWERS.q6||"C"};
      const bh=curveBehavior(realAn,wsOf(p),hold);
      t.strat_total_bih=bh.total;
      if(key==="animal"){const g1=curvePos(mask,1);t.strat_total_fwd=g1[g1.length-1];}
      if(key==="digit"){const m8=maskDigit(8),g1=curvePos(m8,1);t.strat_total_fwd=g1[g1.length-1];}
      t.curves=[downsample(bh.curve),downsample(c[1])];
      t.rugMask=hold;}
    return t;});
  const classic=["tom","precny","wd0","wd1","wd2","wd3","wd4"].map(k=>{
    const t=Object.assign({},S.classic[k]);
    const mask=k==="tom"?maskTOM():k==="precny"?maskPreCny(5):mkMask(i=>D.weekday[i]===+k.slice(2));
    if(t.mean1_bp!=null){const c=curve(mask);t.curves=[downsample(c[0]),downsample(c[1])];}return t;});
  const dm=maskYi();
  const stt=DATA.strat.yi||{};
  const positions={};
  [["守拙",0.25],["中庸",0.5],["进取",1.0]].forEach(([n,posX])=>{
    const m=Object.assign({},stt[n]);
    m.curve=downsample(curvePos(dm,posX));positions[n]=m;});
  const allMask=mkMask(()=>true);
  const strategy={signal:"黄历宜纳财开市之日",positions:positions,
    bench:Object.assign({},DATA.strat.bench,{curve:downsample(curvePos(allMask,1.0))}),
    reverse:stt["反向"]||null};
  return{disclaimer:DATA.metaInfo.disclaimer,
    meta:{index:DATA.metaInfo.index,start:DATA.metaInfo.start,end:DATA.metaInfo.end,n_days:DATA.metaInfo.n_days,method:DATA.metaInfo.method},
    profile:p,tests:tests,scans:DATA.scans,classic:classic,strategy:strategy,sectors:DATA.sectors};
}
function answersInfoJS(){
  const scoreMap={A:2.0,B:1.0,C:0.0},scoreMap3={A:0.0,B:1.5,C:3.0};
  const score=scoreMap[ANSWERS.q1]+scoreMap3[ANSWERS.q3];
  const pos=TDATA.posOfAnswer[ANSWERS.q6];
  return{score:score,style:score<=1.0?"保守":(score<=2.5?"中庸":"进取"),
    element_pref:ANSWERS.q2||null,leverage:ANSWERS.q3==="C",
    xuan_pos:pos,xuan_pos_name:TDATA.posName[String(pos)]};
}
function applyAnswers(result){
  const info=answersInfoJS();
  const fresh=buildResult(result.profile);
  result.questionnaire={answers:{q1:ANSWERS.q1,q2:ANSWERS.q2,q3:ANSWERS.q3,q4:ANSWERS.q4,q5:ANSWERS.q5,q6:ANSWERS.q6,defaulted:false},
    info:info,questions:TDATA.questionnaire};
  result.titles=computeTitlesJS(result.profile,info,result.summary.n_significant);
  result.figure=computeFigureJS(ANSWERS,info,result.profile,result.titles.wang_shuai);
  result.figure_eggs=figureEggsJS(ANSWERS,info,result.profile,result.titles.wang_shuai);
  result.tests=fresh.tests;
  document.getElementById("dyn-tests").innerHTML=testsHtml(result);
  document.querySelectorAll("#dyn-tests .card").forEach(x=>x.classList.add("veiled"));
  refreshDynamic(result,true);
  DLG.beats=DLG.beats.concat(b1(result),b2(result),b3(result,DATA.scans));
}
function run(){
  const y=+document.getElementById("by").value,m=+document.getElementById("bm").value,d=+document.getElementById("bd").value;
  const jd=jdOf(y,m,d);
  if(solarToLunar(jd)==null){alert("该日期超出历法表范围（1900年1月31日起） 请换一个");return;}
  const p=buildProfile(jd);
  const result=buildResult(p);
  result.summary={n_tests:result.tests.length,
    n_significant:result.tests.filter(t=>t.verdict==="significant").length,
    n_null:result.tests.filter(t=>t.verdict==="null").length,
    n_insufficient:result.tests.filter(t=>t.verdict==="insufficient").length};
  result.questionnaire={answers:{q1:"B",q2:null,q3:"A",q4:"D",q5:"B",q6:"C",defaulted:true},
    info:{score:2.5,style:"中庸",element_pref:null,leverage:false,xuan_pos:0.5,xuan_pos_name:"半仓"},questions:TDATA.questionnaire};
  result.titles=computeTitlesJS(p,result.questionnaire.info,result.summary.n_significant);
  result.figure=computeFigureJS({q1:"B",q2:null,q3:"A",q4:"D",q5:"B",q6:"C"},result.questionnaire.info,p,result.titles.wang_shuai);
  result.figure_eggs=[];
  document.getElementById("formbox").style.display="none";
  window.scrollTo({top:0});
  renderAll(result,DATA.scans,true,true);
  document.getElementById("av-ring").innerHTML=baguaSvg("av",104,{mini:true});
  if(!document.getElementById("pb")){const pb=document.createElement("div");pb.id="pb";pb.className="hide";
    pb.innerHTML=baguaSvg("pb",56,{mini:true});document.body.appendChild(pb);}
  document.querySelectorAll("#pb .tg").forEach(x=>x.classList.remove("lit"));
  baguaOverlayPlay(()=>startDialogue(result,DATA.scans));
}
"""
    html = _html_shell(f"{TITLE} {SUBTITLE}", form, page_js)
    (WEB / "index.html").write_text(html, encoding="utf-8")
    # 语法检查：抽取页面脚本交 node --check
    js_text = html.split("<script>", 1)[1].rsplit("</script>", 1)[0]
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(js_text)
        tmp = Path(f.name)
    try:
        r = subprocess.run(["node", "--check", str(tmp)], capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            sys.exit("页面脚本语法检查失败：" + (r.stderr or r.stdout)[:800])
        print("PAGE_JS_SYNTAX_OK")
    finally:
        tmp.unlink(missing_ok=True)
    size = (WEB / "index.html").stat().st_size / 1024
    print(f"web/index.html 生成完毕（{size:.0f} KB）")


def render_report_html(result: dict) -> str:
    """skill 用：完整结果渲染成单文件卷宗（含问券 策略 行业 称号）。"""
    for t in result["tests"] + result["classic"]:
        t["curves"] = [t.pop("strat_curve"), t.pop("bench_curve")]
    xu = ("<div class='wrap'><div class='xu'>客官留步。小女子谢知夏，康熙年间钦天监观星记历之小吏，一梦三百年，"
          "醒在此间A股营业部。今将客官命帖上的说法逐条掷于行情之上，以统计为镜，勘验真伪，"
          "七问在前，合参与策略殿居中，遍试诸日与典籍对照殿后。灵与不灵，数字说话。"
          "<div class='dvh'>谢知夏把你生日对应的每条命理说法变成可回测的策略，放到三十多年真实行情里检验；"
          "文言判词下方均附白话解释。</div>"
          "<div class='who'>谢知夏 谨识</div></div></div>")
    body = ("<header><div class='brand'><span class='seal lg'>知<br>夏</span><h1 class='site'>生辰算股</h1>"
            "<span class='seal lg' style='transform:rotate(4deg)'>卷<br>宗</span></div>"
            "<div class='sub'>谢知夏的统计学算命铺　勘验卷宗</div>"
            f"<div class='notice'>{lab.DISCLAIMER}</div></header>" + xu + "<div id='report'></div>")
    js = (CORE_JS + _render_js().replace("@@EGGS@@", _eggs_json())
          + "\nrenderAll(" + json.dumps(result, ensure_ascii=False, separators=(",", ":")) + ","
          + json.dumps(result["scans"], ensure_ascii=False, separators=(",", ":")) + ",false,false);")
    return _html_shell(f"{TITLE} 勘验卷宗 {result['profile']['birthday']}", body, js)


# ================================================================ 自检 ==
def selftest(stats: dict, meta: dict) -> None:
    mk = lab.Market()
    samples = [dt.date(2003, 8, 18), dt.date(1996, 2, 29), dt.date(1985, 12, 25),
               dt.date(2000, 1, 1), dt.date(2008, 8, 8), dt.date(2024, 2, 10),
               dt.date(1999, 7, 1), dt.date(1935, 6, 15)]
    expect = []
    for b in samples:
        p = pf.build_profile(b, mk.cal)
        masks = {
            "yi": int(lab.mask_almanac_yi(mk).sum()),
            "retro": int(lab.mask_mercury_retro(mk).sum()),
            "waxing": int(lab.mask_moon_waxing(mk).sum()),
            "animal": int(lab.mask_animal(mk, p["animal"]).sum()),
            "jieqi_all": int(lab.mask_jieqi_all(mk).sum()),
            "digit4": int(lab.mask_digit(mk, 4).sum()),
            "sanhe": int(lab.mask_sanhe(mk, p["animal"]).sum()),
            "tom": int(lab.mask_turn_of_month(mk).sum()),
            "wangshuai": pf.wang_shuai(p["nayin_element"], p["birth_month"]),
        }
        expect.append({"jd": (b - EPOCH).days,
                       "constellation": p["constellation"], "animal": p["animal"],
                       "ganzhi": p["ganzhi"], "nayin": p["nayin"],
                       "lunar": [p["lunar"]["month"], p["lunar"]["day"]],
                       "jieqi": p["jieqi"]["name"], "masks": masks})

    harness = (
        "const path=require('path');\n"
        f"const meta={json.dumps(meta, ensure_ascii=False, separators=(',', ':'))};\n"
        f"const expect={json.dumps(expect, ensure_ascii=False, separators=(',', ':'))};\n"
        + CORE_JS + "\nsetMeta(meta);\nlet bad=0;\n"
        """
for(const e of expect){
  const p=buildProfile(e.jd);
  const checks=[['constellation',p.constellation,e.constellation],['animal',p.animal,e.animal],
    ['ganzhi',p.ganzhi,e.ganzhi],['nayin',p.nayin,e.nayin],
    ['lunar',p.lunar.month+'-'+p.lunar.day,e.lunar[0]+'-'+e.lunar[1]],['jieqi',p.jieqi.name,e.jieqi],
    ['wangshuai',wangShuai(p.nayin_element,p.birth_month),e.masks.wangshuai]];
  for(const[name,got,want]of checks)if(got!==want){console.log('属性不一致',e.jd,name,got,want);bad++;}
  const maps={yi:maskYi(),retro:maskRetro(),waxing:maskWaxing(),
    animal:maskAnimal(p.animal),jieqi_all:maskJieqiAll(5),digit4:maskDigit(4),
    sanhe:maskSanhe(p.animal),tom:maskTOM()};
  for(const k in maps){const n=maps[k].filter(Boolean).length;
    if(n!==e.masks[k]){console.log('掩码不一致',e.jd,k,n,e.masks[k]);bad++;}}
}
console.log(bad===0?'NODE_SELTTEST_OK ('+expect.length+' 个生日全对)':'NODE_SELFTEST_FAIL bad='+bad);
process.exit(bad===0?0:1);
""")
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(harness)
        tmp = Path(f.name)
    try:
        r = subprocess.run(["node", str(tmp)], capture_output=True, text=True, timeout=120)
        out = (r.stdout + r.stderr).strip()
        print(out[-500:] if len(out) > 500 else out)
        if r.returncode != 0:
            sys.exit("node 一致性自检失败，中止构建")
    finally:
        tmp.unlink(missing_ok=True)


def selftest_rules(tdata: dict, meta: dict) -> None:
    """v4 规则对拍：人物主链/彩蛋链/合参规则/仓位映射 JS 与 Python 逐一一致。"""
    combos = ["A,火,C,B,A,D", "B,金,A,D,C,B", "C,水,B,B,C,A", "B,木,A,C,D,C",
              "C,土,C,A,B,B", "A,水,B,D,A,D", "B,火,C,B,D,C", "C,金,A,A,C,B"]
    days = [dt.date(2003, 8, 18), dt.date(1996, 2, 29), dt.date(1935, 6, 15), dt.date(2000, 1, 1)]
    mk = lab.Market()
    expect = []
    for b in days:
        prof = pf.build_profile(b, mk.cal)
        ws = pf.wang_shuai(prof["nayin_element"], prof["birth_month"])
        rule = lab.birth_strategy_rule(ws, prof)
        for raw in combos:
            answers = lab.parse_answers(raw)
            q = lab.answers_info(answers)
            prof["_wang_shuai"] = ws
            fig = lab.compute_figure(answers, q, prof)
            eggs = lab.figure_eggs(answers, q, prof)
            beh = lab.behavior_strategy(mk, answers, ws)
            hold_yi = lab.mask_almanac_yi(mk)
            hold_sh = lab.mask_sanhe(mk, prof["animal"])
            beh_yi = lab.behavior_strategy(mk, answers, ws, hold=hold_yi)
            beh_sh = lab.behavior_strategy(mk, answers, ws, hold=hold_sh)
            expect.append({"jd": (b - EPOCH).days, "raw": raw,
                           "fig": fig["name"], "eggs": [e["name"] for e in eggs],
                           "rule": rule["family"], "ws": ws,
                           "beh": round(beh["total"], 3),
                           "behyi": round(beh_yi["total"], 3),
                           "behsh": round(beh_sh["total"], 3)})
    harness = (
        "const path=require('path');\n"
        f"const meta={json.dumps(meta, ensure_ascii=False, separators=(',', ':'))};\n"
        f"const TDATA={json.dumps(tdata, ensure_ascii=False, separators=(',', ':'))};\n"
        f"const expect={json.dumps(expect, ensure_ascii=False, separators=(',', ':'))};\n"
        + CORE_JS + "\nsetMeta(meta);let bad=0;\n"
        + _render_js().replace("@@EGGS@@", _eggs_json()) + "\n"
        """
for(const e of expect){
  const p=buildProfile(e.jd);
  const parts=e.raw.split(",");
  const an={q1:parts[0],q2:parts[1]||null,q3:parts[2],q4:parts[3],q5:parts[4],q6:parts[5]};
  const info=answersInfoFrom(an);
  const ws=wangShuai(p.nayin_element,p.birth_month);
  if(ws!==e.ws){console.log('旺衰不一致',e.jd,ws,e.ws);bad++;}
  if(TDATA.birthRule[ws].family!==e.rule){console.log('合参规则不一致',e.jd,ws,TDATA.birthRule[ws].family,e.rule);bad++;}
  const f=computeFigureJS(an,info,p,ws);
  if(f.name!==e.fig){console.log('人物不一致',e.jd,e.raw,f.name,e.fig);bad++;}
  const eg=figureEggsJS(an,info,p,ws).map(x=>x.name).join(",");
  if(eg!==e.eggs.join(",")){console.log('彩蛋不一致',e.jd,e.raw,eg,e.eggs.join(","));bad++;}
  const beh=curveBehavior(an,ws).total;
  if(Math.abs(beh-e.beh)>0.01){console.log('行为策略终值不一致',e.jd,e.raw,beh.toFixed(3),e.beh);bad++;}
  const by=curveBehavior(an,ws,maskYi()).total;
  if(Math.abs(by-e.behyi)>0.01){console.log('合体(黄历)终值不一致',e.jd,e.raw,by.toFixed(3),e.behyi);bad++;}
  const bs=curveBehavior(an,ws,maskSanhe(p.animal)).total;
  if(Math.abs(bs-e.behsh)>0.01){console.log('合体(三合)终值不一致',e.jd,e.raw,bs.toFixed(3),e.behsh);bad++;}
}
function answersInfoFrom(an){
  const scoreMap={A:2.0,B:1.0,C:0.0},scoreMap3={A:0.0,B:1.5,C:3.0};
  const score=scoreMap[an.q1]+scoreMap3[an.q3];
  const pos=TDATA.posOfAnswer[an.q6];
  return{score:score,style:score<=1.0?"保守":(score<=2.5?"中庸":"进取"),
    element_pref:an.q2||null,leverage:an.q3==="C",xuan_pos:pos,xuan_pos_name:TDATA.posName[String(pos)]};
}
console.log(bad===0?'RULE_PARITY_OK ('+expect.length+' 组合全对)':'RULE_PARITY_FAIL bad='+bad);
process.exit(bad===0?0:1);
""")
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(harness)
        tmp = Path(f.name)
    try:
        r = subprocess.run(["node", str(tmp)], capture_output=True, text=True, timeout=120)
        out = (r.stdout + r.stderr).strip()
        print(out[-600:] if len(out) > 600 else out)
        if r.returncode != 0:
            sys.exit("v4 规则对拍失败，中止构建")
    finally:
        tmp.unlink(missing_ok=True)


if __name__ == "__main__":
    build()
