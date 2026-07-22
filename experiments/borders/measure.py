# /// script
# requires-python = ">=3.11"
# ///
"""Score boundary-annotation alignment from out/borders_debug.json.

Prints coverage stats and the worst-aligned runs, so threshold tuning in
render_map.py is driven by numbers rather than squinting. Also writes the
report to measure.txt for build_review.py.
"""

import json
from pathlib import Path

ROOT = Path(__file__).parents[2]
HERE = Path(__file__).parent
BARS = {"street": 8, "path": 8, "water": 8, "waterbody": 8, "rail": 25}


def main():
    lines = []
    emit = lines.append
    runs = json.loads((ROOT / "out/borders_debug.json").read_text())["runs"]
    total = sum(r["run_len"] for r in runs)
    annotated = sum(r["run_len"] for r in runs if r["kind"])
    labeled = sum(r["run_len"] for r in runs if r["kind"] and r["name"])
    emit(f"runs: {len(runs)}   border length: {total:,.0f}px")
    emit(f"annotated: {annotated / total:.0%}   labeled: {labeled / total:.0%}")

    by_kind = {}
    for r in runs:
        by_kind.setdefault(r["kind"] or "(nothing)", []).append(r)
    for kind, rs in sorted(by_kind.items(), key=lambda kv: -len(kv[1])):
        length = sum(r["run_len"] for r in rs)
        devs = [r["mean_dev"] for r in rs if r["kind"]]
        dev = f"  mean_dev avg {sum(devs) / len(devs):5.1f}px" if devs else ""
        emit(f"  {kind:<10} {len(rs):3d} runs {length:8,.0f}px{dev}")

    missed = sorted((r for r in runs
                     if not r["kind"] and r.get("cand_ratio", 0) >= 0.6),
                    key=lambda r: -r["run_len"])
    if missed:
        emit("")
        emit(f"missed annotations — (nothing) runs with a feature covering "
             f"≥60% ({sum(r['run_len'] for r in missed):,.0f}px):")
        emit(f"{'border':<42} {'cand':<7} {'name':<24} {'@24px':>5} "
             f"{'@14px':>5} {'len':>6}")
        for r in missed:
            emit(f"{r['tag'][:41]:<42} {r['cand_kind']:<7} "
                 f"{r['cand_name'][:23]:<24} {r['cand_ratio']:>5.0%} "
                 f"{r.get('cand_r14', 0):>5.0%} {r['run_len']:>6.0f}")

    emit("")
    emit("worst-aligned runs (mean_dev over bar, or top offenders):")
    scored = sorted((r for r in runs if r["kind"]),
                    key=lambda r: r["mean_dev"] / BARS.get(r["kind"], 8),
                    reverse=True)[:15]
    emit(f"{'border':<42} {'kind':<7} {'name':<24} {'mean':>5} {'max':>5} {'len':>6}")
    for r in scored:
        flag = " ⚠" if r["mean_dev"] > BARS.get(r["kind"], 8) else ""
        emit(f"{r['tag'][:41]:<42} {r['kind']:<7} {r['name'][:23]:<24} "
             f"{r['mean_dev']:>5.1f} {r['max_dev']:>5.1f} {r['run_len']:>6.0f}{flag}")

    report = "\n".join(lines)
    print(report)
    (HERE / "measure.txt").write_text(report + "\n")


if __name__ == "__main__":
    main()
