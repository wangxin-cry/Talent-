"""
阶段五：人岗匹配规则打分评测

用法（项目根目录）：
    python scripts/eval_matching.py
    python scripts/eval_matching.py --data data/eval/matching_labels.json --out docs/TalentMatch_阶段五_匹配评测报告.md

做什么：
1. 读取人工标注集（候选人画像 × 职位，human_label ∈ fit/partial/unfit）；
2. 用真实的特征提取 + 规则打分代码算分（不连数据库、不调 LLM）；
3. 按阈值把分数映射为三档，与人工标注逐条比对，输出一致率、容忍一致率、Cohen's kappa、混淆矩阵；
4. 可选把完整报告写成 Markdown。

分数映射口径（不是拍脑袋，报告里同步写明）：
    score >= 70            -> fit（合适）
    50 <= score < 70       -> partial（一般）
    score < 50             -> unfit（不合适）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.match_features import extract_features  # noqa: E402
from app.services.scorer import compute_scores  # noqa: E402

LABELS = ["fit", "partial", "unfit"]
LABEL_CN = {"fit": "合适", "partial": "一般", "unfit": "不合适"}

FIT_THRESHOLD = 70.0
PARTIAL_THRESHOLD = 50.0


def predict_label(score: float) -> str:
    if score >= FIT_THRESHOLD:
        return "fit"
    if score >= PARTIAL_THRESHOLD:
        return "partial"
    return "unfit"


def _skill_stub(raw: dict) -> SimpleNamespace:
    return SimpleNamespace(
        id=raw["id"],
        name=raw["name"],
        display_name=raw.get("display_name"),
        aliases=raw.get("aliases") or [],
    )


def _job_stub(raw: dict) -> SimpleNamespace:
    return SimpleNamespace(
        title=raw["title"],
        must_have_skills=raw["must_have_skills"],
        skills=raw["skills"],
        min_years=raw["min_years"],
        education_level=raw["education_level"],
        location=raw["location"],
        salary_min=None,
        salary_max=None,
    )


def _candidate_stub(raw: dict) -> SimpleNamespace:
    return SimpleNamespace(
        name=raw.get("name"),
        skills=raw.get("skills") or [],
        years_experience=raw.get("years_experience"),
        education_level=raw.get("education_level"),
        city=raw.get("city"),
        current_title=raw.get("current_title"),
    )


def _confusion_matrix(pairs: list[tuple[str, str]]) -> dict[str, dict[str, int]]:
    matrix = {label: {pred: 0 for pred in LABELS} for label in LABELS}
    for human, pred in pairs:
        matrix[human][pred] += 1
    return matrix


def _cohen_kappa(matrix: dict[str, dict[str, int]], total: int) -> float:
    if total == 0:
        return 0.0
    observed = sum(matrix[label][label] for label in LABELS) / total
    expected = sum(
        sum(matrix[label].values()) * sum(matrix[h][label] for h in LABELS)
        for label in LABELS
    ) / (total * total)
    if expected >= 1.0:
        return 0.0
    return (observed - expected) / (1.0 - expected)


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def evaluate(dataset: dict) -> list[dict]:
    skills = {item["id"]: _skill_stub(item) for item in dataset["skills"]}
    jobs = {item["key"]: _job_stub(item) for item in dataset["jobs"]}

    rows: list[dict] = []
    for sample in dataset["samples"]:
        job = jobs[sample["job"]]
        feats = extract_features(job, _candidate_stub(sample["candidate"]), skills)
        scores = compute_scores(feats)
        predicted = predict_label(scores["score"])
        rows.append(
            {
                "id": sample["id"],
                "job": job.title,
                "candidate": sample["candidate"].get("name") or f"#{sample['id']}",
                "human": sample["human_label"],
                "predicted": predicted,
                "score": scores["score"],
                "skill_score": scores["skill_score"],
                "exp_score": scores["exp_score"],
                "edu_score": scores["edu_score"],
                "other_score": scores["other_score"],
                "hit_must": len(feats.matched_must),
                "total_must": len(feats.must_skill_names),
                "hit_nice": len(feats.matched_nice),
                "total_nice": len(feats.nice_skill_names),
                "years_gap": feats.years_gap,
                "match": sample["human_label"] == predicted,
            }
        )
    return rows


def build_report(rows: list[dict], dataset: dict) -> str:
    total = len(rows)
    correct = sum(1 for row in rows if row["match"])
    adjacent = sum(
        1
        for row in rows
        if abs(LABELS.index(row["human"]) - LABELS.index(row["predicted"])) <= 1
    )
    matrix = _confusion_matrix([(row["human"], row["predicted"]) for row in rows])
    kappa = _cohen_kappa(matrix, total)

    by_job: dict[str, list[dict]] = {}
    for row in rows:
        by_job.setdefault(row["job"], []).append(row)

    score_by_human = {
        label: [row["score"] for row in rows if row["human"] == label]
        for label in LABELS
    }
    mean_score = {
        label: (sum(values) / len(values) if values else 0.0)
        for label, values in score_by_human.items()
    }

    mismatches = [row for row in rows if not row["match"]]

    lines: list[str] = []
    lines.append("# 阶段五 · 人岗匹配评测报告")
    lines.append("")
    lines.append(f"> 数据集版本 {dataset.get('version', '-')} · 生成日期 {dataset.get('created_at', '-')} · "
                 f"样本 {total} 条")
    lines.append("")
    lines.append("## 一、评测口径")
    lines.append("")
    lines.append("- 数据来源：`data/eval/matching_labels.json`，12 份候选人画像 × 2 个职位 = 24 条配对样本。")
    lines.append("- 标注口径：`fit` 合适（核心必备技能齐全、经验学历满足、地点可接受）；"
                 "`partial` 一般（有缺口但有可迁移经验）；`unfit` 不合适（方向或硬性条件明显不符）。")
    lines.append(f"- 分数映射：综合分 ≥ {FIT_THRESHOLD:.0f} 判 `fit`，{PARTIAL_THRESHOLD:.0f}~{FIT_THRESHOLD:.0f} 判 `partial`，"
                 f"< {PARTIAL_THRESHOLD:.0f} 判 `unfit`。")
    lines.append("- 打分实现：直接调用 `app/services/match_features.py` 与 `app/services/scorer.py`，"
                 "不连数据库、不调用 LLM，结果可复现。")
    lines.append("")
    lines.append("## 二、总体结果")
    lines.append("")
    lines.append("| 指标 | 数值 | 说明 |")
    lines.append("|---|---:|---|")
    lines.append(f"| 完全一致率 | **{_pct(correct / total)}**（{correct}/{total}） | 三档标签完全一致 |")
    lines.append(f"| 相邻容忍一致率 | {_pct(adjacent / total)}（{adjacent}/{total}） | 相差不超过一档即算一致 |")
    lines.append(f"| Cohen's kappa | {kappa:.3f} | 扣除随机一致后的标注一致性 |")
    lines.append("")
    lines.append("### 混淆矩阵（行=人工标注，列=规则判定）")
    lines.append("")
    lines.append("| 人工 \\ 规则 | fit 合适 | partial 一般 | unfit 不合适 |")
    lines.append("|---|---:|---:|---:|")
    for label in LABELS:
        cells = " | ".join(str(matrix[label][pred]) for pred in LABELS)
        lines.append(f"| {LABEL_CN[label]} | {cells} |")
    lines.append("")
    lines.append("### 分职位一致率")
    lines.append("")
    lines.append("| 职位 | 一致数 | 一致率 |")
    lines.append("|---|---:|---:|")
    for job_title, job_rows in by_job.items():
        job_correct = sum(1 for row in job_rows if row["match"])
        lines.append(f"| {job_title} | {job_correct}/{len(job_rows)} | {_pct(job_correct / len(job_rows))} |")
    lines.append("")
    lines.append("### 各人工档位的平均分")
    lines.append("")
    lines.append("| 人工标注 | 样本数 | 平均综合分 |")
    lines.append("|---|---:|---:|")
    for label in LABELS:
        lines.append(
            f"| {LABEL_CN[label]} | {len(score_by_human[label])} | {mean_score[label]:.1f} |"
        )
    lines.append("")
    lines.append("## 三、不一致样本分析")
    lines.append("")
    if mismatches:
        lines.append("| # | 职位 | 候选人 | 人工 | 规则 | 综合分 | 必备命中 | 加分命中 | 经验差 |")
        lines.append("|---:|---|---|---|---|---:|---|---|---:|")
        for row in mismatches:
            gap = "-" if row["years_gap"] is None else f"{row['years_gap']:+.1f} 年"
            lines.append(
                f"| {row['id']} | {row['job']} | {row['candidate']} | {LABEL_CN[row['human']]} | "
                f"{LABEL_CN[row['predicted']]} | {row['score']:.1f} | "
                f"{row['hit_must']}/{row['total_must']} | {row['hit_nice']}/{row['total_nice']} | {gap} |"
            )
        lines.append("")
        lines.append("共性原因：经验与学历在公式中合计占 42%，转岗候选人即使必备技能缺口较大，"
                     "也能凭年限和学历拿到中档分；这是当前权重结构最值得优先校准的地方。")
    else:
        lines.append("本次没有不一致样本。")
    lines.append("")
    lines.append("## 四、复现方式")
    lines.append("")
    lines.append("```powershell")
    lines.append("python scripts\\eval_matching.py")
    lines.append("```")
    lines.append("")
    lines.append("## 五、已知局限")
    lines.append("")
    lines.append("1. 标注为 AI 助手按统一口径的初标，需要 HR 抽样复核；复核后替换 JSON 里的 `human_label` 即可重算。")
    lines.append("2. 技能匹配基于标准名/展示名/别名与版本号归一，尚未做同义词表之外的语义匹配（如 Go/Golang）。")
    lines.append("3. 「稳定性」缺少任职时长明细，当前以“有工作年限”作代理指标；行业与期望薪资无字段，给中性分。")
    lines.append("4. 三档阈值（70/50）用于把连续分映射成可比较标签，阈值调整会同时改变一致率，报告中已固化口径。")
    lines.append("")
    lines.append("## 附录：全部样本")
    lines.append("")
    lines.append("| # | 职位 | 候选人 | 人工 | 规则 | 综合分 | 技能 | 经验 | 学历 | 其他 | 经验差 |")
    lines.append("|---:|---|---|---|---|---:|---:|---:|---:|---:|---:|")
    for row in rows:
        gap = "-" if row["years_gap"] is None else f"{row['years_gap']:+.1f}"
        flag = "" if row["match"] else " ⚠️"
        lines.append(
            f"| {row['id']} | {row['job']} | {row['candidate']} | {LABEL_CN[row['human']]} | "
            f"{LABEL_CN[row['predicted']]}{flag} | {row['score']:.1f} | {row['skill_score']:.2f} | "
            f"{row['exp_score']:.2f} | {row['edu_score']:.2f} | {row['other_score']:.2f} | {gap} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="人岗匹配规则打分评测")
    parser.add_argument(
        "--data",
        default=str(PROJECT_ROOT / "data" / "eval" / "matching_labels.json"),
        help="标注集路径（默认 data/eval/matching_labels.json）",
    )
    parser.add_argument("--out", default=None, help="可选：报告输出 Markdown 路径")
    args = parser.parse_args()

    dataset = json.loads(Path(args.data).read_text(encoding="utf-8"))
    rows = evaluate(dataset)

    total = len(rows)
    correct = sum(1 for row in rows if row["match"])
    adjacent = sum(
        1
        for row in rows
        if abs(LABELS.index(row["human"]) - LABELS.index(row["predicted"])) <= 1
    )
    matrix = _confusion_matrix([(row["human"], row["predicted"]) for row in rows])
    kappa = _cohen_kappa(matrix, total)

    print(f"样本 {total} 条 | 完全一致 {correct}/{total} = {_pct(correct / total)} | "
          f"相邻一致 {adjacent}/{total} = {_pct(adjacent / total)} | kappa={kappa:.3f}")
    print()
    for row in rows:
        flag = "OK " if row["match"] else "MISS"
        print(
            f"[{flag}] #{row['id']:>2} {row['job']} / {row['candidate']:<6} "
            f"人工={LABEL_CN[row['human']]:<3} 规则={LABEL_CN[row['predicted']]:<3} "
            f"score={row['score']:>5.1f} 必备 {row['hit_must']}/{row['total_must']} "
            f"加分 {row['hit_nice']}/{row['total_nice']}"
        )

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(build_report(rows, dataset), encoding="utf-8")
        print(f"\n报告已写入 {out_path}")


if __name__ == "__main__":
    main()
