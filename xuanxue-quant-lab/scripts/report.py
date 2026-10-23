# -*- coding: utf-8 -*-
"""生成单人《民间命理说法统计检验报告》（单文件 HTML，双击即开）。

用法：
  python report.py --birthday 2003-08-18 [--out 报告.html]

仅供研究使用：以统计学方法检验民间流传说法，旨在破除封建迷信、弘扬科学精神，
不构成任何投资建议。
"""
import argparse
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import lab


def generate(birthday: dt.date, out: Path, answers: str = None) -> Path:
    import build_web
    result = lab.run_full(birthday, answers)
    html = build_web.render_report_html(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="玄学量化实验室 · 单人检验报告（仅供研究使用）")
    ap.add_argument("--birthday", required=True, help="生日，如 2003-08-18")
    ap.add_argument("--out", help="输出 HTML 路径，默认 检验报告_<生日>.html")
    ap.add_argument("--answers", default=None, help="问券答案如 A,火,C（浮亏处置/行业五行/盈利处置）")
    args = ap.parse_args()

    b = dt.date.fromisoformat(args.birthday)
    out = Path(args.out) if args.out else Path(f"检验报告_{b.isoformat()}.html")
    generate(b, out, args.answers)
    s = lab.run_full(b)["summary"]
    print(lab.DISCLAIMER)
    print(f"\n报告已生成：{out.resolve()}")
    print(f"7 项检验：{s['n_null']} 不显著 / {s['n_significant']} 名义显著 / {s['n_insufficient']} 样本不足")


if __name__ == "__main__":
    main()
