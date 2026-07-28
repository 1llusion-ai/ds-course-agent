"""Build the frozen Phase B task, profile, claim, and edge design draft."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

DEFAULT_OUTPUT = Path("benchmarks/data/knowledge_state_search_confirmatory_v3_phase_b_design")


@dataclass(frozen=True)
class ClaimDraft:
    """One claim description prepared before source collection and annotation."""

    concept: str
    description: str
    oracle_query: str


@dataclass(frozen=True)
class EdgeDraft:
    """One directed claim relation assigned to a required path."""

    from_claim: int
    to_claim: int
    edge_type: str
    path_number: int


@dataclass(frozen=True)
class TaskDraft:
    """Complete pre-source design for one Phase B task."""

    task_id: str
    kind: str
    question: str
    target_concepts: tuple[str, ...]
    trigger: str
    no_gap_learning_goal: str
    single_gap_learning_goal: str
    core_claims: tuple[ClaimDraft, ...]
    learner_claim: ClaimDraft
    edges: tuple[EdgeDraft, ...]


@dataclass(frozen=True)
class PhaseBDesign:
    """Deterministic Phase B design records before sources and annotations exist."""

    tasks: tuple[dict[str, object], ...]
    profiles: tuple[dict[str, object], ...]
    claims: tuple[dict[str, object], ...]
    edges: tuple[dict[str, object], ...]
    splits: dict[str, tuple[str, ...]]


def build_phase_b_design() -> PhaseBDesign:
    """Return the twelve-task Phase B design in the frozen roster order."""

    drafts = _task_drafts()
    tasks: list[dict[str, object]] = []
    profiles: list[dict[str, object]] = []
    claims: list[dict[str, object]] = []
    edges: list[dict[str, object]] = []

    for draft in drafts:
        tasks.append(
            {
                "task_id": draft.task_id,
                "question": draft.question,
                "target_concepts": list(draft.target_concepts),
            }
        )
        profiles.extend(_profiles_for(draft))
        claims.extend(_claims_for(draft))
        edges.extend(_edges_for(draft))

    dev_ids = ("pb_t01_cv_variance", "pb_t05_p_value_meaning", "pb_t09_skewed_summary")
    test_ids = tuple(draft.task_id for draft in drafts if draft.task_id not in dev_ids)
    return PhaseBDesign(
        tasks=tuple(tasks),
        profiles=tuple(profiles),
        claims=tuple(claims),
        edges=tuple(edges),
        splits={"phase_b_dev": dev_ids, "phase_b_test": test_ids},
    )


def write_phase_b_design(output_directory: str | Path = DEFAULT_OUTPUT) -> Path:
    """Write the non-schema draft files and return the output directory."""

    root = Path(output_directory)
    root.mkdir(parents=True, exist_ok=True)
    design = build_phase_b_design()
    _write_jsonl(root / "tasks.jsonl", design.tasks)
    _write_jsonl(root / "profiles.jsonl", design.profiles)
    _write_jsonl(root / "claims.jsonl", design.claims)
    _write_jsonl(root / "claim_edges.jsonl", design.edges)
    (root / "splits.json").write_text(
        json.dumps(
            {"splits": {name: list(task_ids) for name, task_ids in design.splits.items()}},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    manifest = {
        "status": "draft_task_design",
        "schema_version": 3,
        "source_collection_started": False,
        "annotation_started": False,
        "method_runs_authorized": False,
        "counts": {
            "tasks": len(design.tasks),
            "profiles": len(design.profiles),
            "claims": len(design.claims),
            "edges": len(design.edges),
            "sources": 0,
            "annotations": 0,
        },
        "file_sha256": {
            filename: _file_sha256(root / filename)
            for filename in ("tasks.jsonl", "profiles.jsonl", "claims.jsonl", "claim_edges.jsonl", "splits.json")
        },
    }
    (root / "design_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text(_readme(), encoding="utf-8")
    return root


def build_parser() -> argparse.ArgumentParser:
    """Build the task-design generation command-line interface."""

    parser = argparse.ArgumentParser(description="Write the Phase B task-design draft.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main() -> int:
    """Generate the Phase B task-design draft."""

    root = write_phase_b_design(build_parser().parse_args().output)
    print(f"wrote Phase B design draft to {root}")
    return 0


def _profiles_for(draft: TaskDraft) -> tuple[dict[str, object], dict[str, object]]:
    """Build matched no-gap and single-gap profiles for one task."""

    mastered = list(draft.target_concepts)
    if draft.kind == "prerequisite":
        mastered = list(dict.fromkeys((*mastered, draft.trigger)))
    no_gap = {
        "task_id": draft.task_id,
        "profile_id": f"{draft.task_id}_profile_00",
        "level": "intermediate",
        "mastered_concepts": mastered,
        "weak_concepts": [],
        "misconceptions": [],
        "learning_goal": draft.no_gap_learning_goal,
    }
    single_gap = {
        **no_gap,
        "profile_id": f"{draft.task_id}_profile_01",
        "mastered_concepts": [item for item in mastered if item != draft.trigger],
    }
    if draft.kind == "prerequisite":
        single_gap["weak_concepts"] = [draft.trigger]
    elif draft.kind == "misconception":
        single_gap["misconceptions"] = [draft.trigger]
    else:
        single_gap["learning_goal"] = draft.single_gap_learning_goal
    return no_gap, single_gap


def _claims_for(draft: TaskDraft) -> tuple[dict[str, object], ...]:
    """Build canonical claim records for one task."""

    records = [
        {
            "task_id": draft.task_id,
            "claim_id": f"{draft.task_id}_c{index:02d}",
            "kind": "core",
            "concept": claim.concept,
            "description": claim.description,
            "hard": True,
            "priority": 3,
            "oracle_query": claim.oracle_query,
            "profile_condition": None,
        }
        for index, claim in enumerate(draft.core_claims, 1)
    ]
    learner = draft.learner_claim
    trigger_field = {
        "prerequisite": "weak_concept",
        "misconception": "misconception",
        "goal": "learning_goal",
    }[draft.kind]
    records.append(
        {
            "task_id": draft.task_id,
            "claim_id": f"{draft.task_id}_c06",
            "kind": draft.kind,
            "concept": learner.concept,
            "description": learner.description,
            "hard": False,
            "priority": 2,
            "oracle_query": learner.oracle_query,
            "profile_condition": {"field": trigger_field, "value": draft.trigger},
        }
    )
    return tuple(records)


def _edges_for(draft: TaskDraft) -> tuple[dict[str, object], ...]:
    """Build the four required directed edges for one task."""

    return tuple(
        {
            "task_id": draft.task_id,
            "edge_id": f"{draft.task_id}_e{index:02d}",
            "from_claim_id": f"{draft.task_id}_c{edge.from_claim:02d}",
            "to_claim_id": f"{draft.task_id}_c{edge.to_claim:02d}",
            "edge_type": edge.edge_type,
            "required": True,
            "path_ids": [f"{draft.task_id}_p{edge.path_number:02d}"],
        }
        for index, edge in enumerate(draft.edges, 1)
    )


def _write_jsonl(path: Path, rows: tuple[dict[str, object], ...]) -> None:
    """Write deterministic UTF-8 JSONL records."""

    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in rows) + "\n",
        encoding="utf-8",
    )


def _file_sha256(path: Path) -> str:
    """Return the SHA-256 digest of one generated design file."""

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _readme() -> str:
    """Return the guardrail README for the draft directory."""

    return """# Phase B Task-Design Draft

This directory is the P1 task/profile/claim/edge design artifact for the
knowledge-state search Phase B benchmark. It is intentionally **not** a
schema-loadable frozen benchmark:

- sources and evidence annotations have not been collected;
- no annotator or adjudicator records exist;
- `design_manifest.json` is a draft manifest, not the v3 release manifest;
- no Phase B method run is authorized by this artifact.

The next authorized step is dev source shakeout for `pb_t01`, `pb_t05`, and
`pb_t09`. If source collection exposes an unsupported claim, reset that task
before annotation rather than editing an annotated task in place.
"""


def _task_drafts() -> tuple[TaskDraft, ...]:
    """Return the frozen 12-task roster and its claim graph design."""

    return (
        TaskDraft(
            task_id="pb_t01_cv_variance",
            kind="prerequisite",
            question="为什么 k 折交叉验证通常比一次训练/测试划分更能稳定估计模型性能？",
            target_concepts=("k 折交叉验证", "抽样变异", "模型评估"),
            trigger="抽样变异与估计方差",
            no_gap_learning_goal="理解模型评估方法",
            single_gap_learning_goal="理解模型评估方法",
            core_claims=(
                ClaimDraft(
                    "交叉验证流程",
                    "k 折交叉验证把数据划分为 k 个折，并轮流将每一折作为验证集、其余折作为训练集。",
                    "k 折交叉验证如何轮流划分训练集和验证集？",
                ),
                ClaimDraft(
                    "折间样本使用",
                    "在标准 k 折交叉验证中，每个样本通常恰好一次作为验证样本，并在其余 k-1 次迭代中用于训练。",
                    "k 折交叉验证中每个样本分别如何用于训练和验证？",
                ),
                ClaimDraft(
                    "多次评估",
                    "不同折产生多个训练/验证划分，因此模型性能可以在多个划分上分别评估。",
                    "为什么交叉验证会得到多个模型性能评估值？",
                ),
                ClaimDraft(
                    "均值与波动",
                    "交叉验证通常报告各折分数的汇总值，并可观察折间分数的波动，而不是只依赖一个划分的分数。",
                    "交叉验证如何汇总多个折的性能以及反映折间波动？",
                ),
                ClaimDraft(
                    "评估隔离",
                    "预处理和模型选择必须在每个训练折内部拟合，不能用验证折的信息泄漏到训练过程。",
                    "交叉验证中为什么预处理也必须在训练折内拟合？",
                ),
            ),
            learner_claim=ClaimDraft(
                "抽样变异与估计方差",
                "不同样本划分会产生不同的性能估计；理解抽样变异有助于解释为什么单次划分的结果可能不稳定。",
                "样本划分的抽样变异为什么会让模型性能估计发生波动？",
            ),
            edges=(
                EdgeDraft(6, 3, "explains", 1),
                EdgeDraft(3, 4, "qualifies", 1),
                EdgeDraft(1, 2, "explains", 2),
                EdgeDraft(2, 4, "causal", 2),
            ),
        ),
        TaskDraft(
            task_id="pb_t02_logistic_log_odds",
            kind="prerequisite",
            question="为什么逻辑回归把线性预测值通过 sigmoid 转成类别概率，而不是直接输出任意实数？",
            target_concepts=("逻辑回归", "sigmoid", "概率与对数几率"),
            trigger="概率与对数几率",
            no_gap_learning_goal="理解分类模型的基本原理",
            single_gap_learning_goal="理解分类模型的基本原理",
            core_claims=(
                ClaimDraft(
                    "线性预测值",
                    "逻辑回归先用特征的线性组合形成可以取任意实数的线性预测值。",
                    "逻辑回归的线性预测值由什么组成？",
                ),
                ClaimDraft(
                    "sigmoid 映射",
                    "sigmoid 函数把任意实数映射到 0 和 1 之间，从而可以解释为二分类概率。",
                    "sigmoid 为什么能把逻辑回归输出转换为概率？",
                ),
                ClaimDraft(
                    "概率解释",
                    "在给定模型和特征的条件下，逻辑回归的输出可解释为样本属于指定类别的估计概率。",
                    "逻辑回归输出的数值如何解释为类别概率？",
                ),
                ClaimDraft(
                    "分类阈值",
                    "将概率转成类别标签还需要选择分类阈值，阈值不等同于概率模型本身。",
                    "逻辑回归如何从概率得到类别标签？",
                ),
                ClaimDraft(
                    "系数尺度",
                    "逻辑回归系数描述特征变化对对数几率的线性影响，而不是直接表示概率变化的固定幅度。",
                    "逻辑回归系数为什么通常解释为对数几率尺度上的影响？",
                ),
            ),
            learner_claim=ClaimDraft(
                "概率与对数几率",
                "对数几率是 log(p/(1-p))，它把 0 到 1 之间的概率变换到整个实数轴，使线性预测成为可能。",
                "概率和对数几率之间的变换关系是什么？",
            ),
            edges=(
                EdgeDraft(6, 1, "prerequisite", 1),
                EdgeDraft(1, 2, "explains", 1),
                EdgeDraft(2, 3, "explains", 2),
                EdgeDraft(3, 4, "qualifies", 2),
            ),
        ),
        TaskDraft(
            task_id="pb_t03_standard_error_ci",
            kind="prerequisite",
            question="为什么样本均值的置信区间会随样本量增大而变窄？",
            target_concepts=("样本均值", "抽样分布", "标准误", "置信区间"),
            trigger="标准误与抽样分布",
            no_gap_learning_goal="理解统计估计的不确定性",
            single_gap_learning_goal="理解统计估计的不确定性",
            core_claims=(
                ClaimDraft(
                    "点估计",
                    "样本均值是用样本对总体均值进行估计的点估计量。",
                    "样本均值为什么可以作为总体均值的点估计？",
                ),
                ClaimDraft(
                    "抽样分布",
                    "如果反复从同一总体抽样，样本均值会形成一个抽样分布，而不是每次都得到同一个数。",
                    "样本均值的抽样分布描述了什么？",
                ),
                ClaimDraft(
                    "标准误",
                    "标准误刻画估计量在重复抽样下的典型波动大小；对均值而言，样本量增大通常会降低标准误。",
                    "标准误如何表示样本均值在重复抽样中的波动？",
                ),
                ClaimDraft(
                    "区间构造",
                    "置信区间通常由点估计加减一个与标准误和置信水平有关的误差范围构成。",
                    "置信区间如何由点估计和标准误构造？",
                ),
                ClaimDraft(
                    "样本量效应",
                    "在方差有限且其他条件相近时，增加样本量会降低均值估计的不确定性，使置信区间平均更窄。",
                    "为什么增加样本量通常会使均值置信区间变窄？",
                ),
            ),
            learner_claim=ClaimDraft(
                "标准误与抽样分布",
                "标准误描述样本统计量在重复抽样中的波动，抽样分布则展示这种波动的整体形状和范围。",
                "标准误和抽样分布分别如何描述估计的不确定性？",
            ),
            edges=(
                EdgeDraft(6, 3, "explains", 1),
                EdgeDraft(3, 4, "explains", 1),
                EdgeDraft(1, 2, "explains", 2),
                EdgeDraft(2, 3, "explains", 2),
            ),
        ),
        TaskDraft(
            task_id="pb_t04_confounding_correlation",
            kind="prerequisite",
            question="为什么观察数据里的相关关系不能直接解释成因果关系？",
            target_concepts=("相关关系", "因果关系", "混杂变量", "观察数据"),
            trigger="混杂变量",
            no_gap_learning_goal="理解数据分析中的因果边界",
            single_gap_learning_goal="理解数据分析中的因果边界",
            core_claims=(
                ClaimDraft(
                    "相关与因果",
                    "观察到两个变量相关，说明它们共同变化，但本身不能确定一个变量导致另一个变量。",
                    "为什么相关关系本身不能证明因果关系？",
                ),
                ClaimDraft(
                    "混杂定义",
                    "混杂变量同时与暴露因素和结果相关，并可能造成暴露与结果之间的表面关联。",
                    "混杂变量如何同时关联暴露和结果？",
                ),
                ClaimDraft(
                    "偏倚方向",
                    "混杂会使观察到的关联偏离真实因果效应，偏离方向和大小取决于数据生成过程。",
                    "混杂变量如何使观察关联偏离因果效应？",
                ),
                ClaimDraft(
                    "随机化作用",
                    "随机分配可以在期望意义上平衡已测量和未测量的混杂因素，从而支持因果解释。",
                    "随机分配为什么有助于排除混杂？",
                ),
                ClaimDraft(
                    "调整条件",
                    "观察研究中的调整只有在混杂控制和模型设定等识别假设合理时，才有助于因果解释。",
                    "观察数据中调整混杂变量需要满足哪些条件？",
                ),
            ),
            learner_claim=ClaimDraft(
                "混杂变量",
                "一个同时影响或关联解释变量和结果变量的第三变量，可能制造、掩盖或改变两者之间的观察关联。",
                "混杂变量为什么会让相关关系难以解释为因果关系？",
            ),
            edges=(
                EdgeDraft(6, 2, "explains", 1),
                EdgeDraft(2, 3, "causal", 1),
                EdgeDraft(1, 4, "contrasts", 2),
                EdgeDraft(4, 5, "contrasts", 2),
            ),
        ),
        TaskDraft(
            task_id="pb_t05_p_value_meaning",
            kind="misconception",
            question="为什么 p 值很小并不表示“原假设为真的概率很小”？",
            target_concepts=("p 值", "原假设", "统计推断"),
            trigger="p 值是原假设为真的概率",
            no_gap_learning_goal="正确解释统计检验结果",
            single_gap_learning_goal="正确解释统计检验结果",
            core_claims=(
                ClaimDraft(
                    "条件概率方向",
                    "p 值是在原假设及其模型成立的条件下，观察到当前或更极端数据的概率。",
                    "p 值是在什么条件下计算的数据概率？",
                ),
                ClaimDraft(
                    "不等价逆转",
                    "p 值是数据在原假设下的概率，不是原假设在已观测数据条件下为真的概率。",
                    "为什么 p 值不能解释为原假设为真的概率？",
                ),
                ClaimDraft(
                    "证据强度",
                    "在检验模型合理时，较小的 p 值表示数据与原假设的相容性较低，但不单独证明某个替代解释。",
                    "小 p 值通常说明数据对原假设提供了什么信息？",
                ),
                ClaimDraft(
                    "实际重要性",
                    "统计显著性和实际效应大小、实际重要性不是同一个概念，需要结合效应估计和不确定性解释。",
                    "为什么统计显著不等于实际重要？",
                ),
                ClaimDraft(
                    "重复概率边界",
                    "p 值不能单独证明原假设必然错误。",
                    "p 值能否直接表示重复实验显著的概率？",
                ),
            ),
            learner_claim=ClaimDraft(
                "p 值条件性",
                "“原假设为真时数据有多极端”和“给定数据后原假设为真的概率”是方向相反的条件概率，不能混为一谈。",
                "如何纠正把 p 值当成原假设概率的理解？",
            ),
            edges=(
                EdgeDraft(6, 2, "explains", 1),
                EdgeDraft(2, 3, "explains", 1),
                EdgeDraft(1, 2, "explains", 2),
                EdgeDraft(2, 4, "qualifies", 2),
            ),
        ),
        TaskDraft(
            task_id="pb_t06_r2_feature_addition",
            kind="misconception",
            question="为什么在线性回归中加入更多特征可能提高训练 R²，却不一定让模型更好？",
            target_concepts=("线性回归", "训练 R²", "泛化", "模型选择"),
            trigger="训练 R² 越高模型越好",
            no_gap_learning_goal="理解拟合优度与泛化的区别",
            single_gap_learning_goal="理解拟合优度与泛化的区别",
            core_claims=(
                ClaimDraft(
                    "训练拟合",
                    "在线性回归中加入预测变量后，最小二乘训练误差不会增加，因此训练 R² 不会下降。",
                    "为什么在线性回归增加特征后训练 R² 不会下降？",
                ),
                ClaimDraft(
                    "训练泛化区别",
                    "训练数据上的 R² 只描述样本内拟合，不能单独代表对未见数据的预测表现。",
                    "训练 R² 为什么不能单独代表泛化性能？",
                ),
                ClaimDraft(
                    "过拟合风险",
                    "无关或噪声特征可能让模型拟合训练样本中的偶然模式，增加过拟合风险。",
                    "加入无关特征为什么可能增加过拟合？",
                ),
                ClaimDraft(
                    "验证评估",
                    "是否保留新增特征应使用独立验证、交叉验证或其他面向未见数据的评估，而不能只看训练 R²。",
                    "如何评估新增特征是否改善模型？",
                ),
                ClaimDraft(
                    "复杂度权衡",
                    "模型选择应把样本内拟合与模型复杂度或验证表现一起考虑，而不能只最大化训练 R²。",
                    "有哪些方法能同时考虑拟合收益和模型复杂度？",
                ),
            ),
            learner_claim=ClaimDraft(
                "训练 R² 的局限",
                "训练 R² 越高只说明模型更贴合当前训练样本，不能推出它在新样本上更准确或更有用。",
                "为什么训练 R² 越高不一定意味着模型越好？",
            ),
            edges=(
                EdgeDraft(6, 2, "explains", 1),
                EdgeDraft(2, 4, "explains", 1),
                EdgeDraft(1, 4, "qualifies", 2),
                EdgeDraft(4, 5, "explains", 2),
            ),
        ),
        TaskDraft(
            task_id="pb_t07_outlier_removal",
            kind="misconception",
            question="为什么不能只因为观测值极端就自动删除异常值？",
            target_concepts=("异常值", "数据质量", "稳健统计", "敏感性分析"),
            trigger="异常值一定是录入错误",
            no_gap_learning_goal="理解异常值处理的证据要求",
            single_gap_learning_goal="理解异常值处理的证据要求",
            core_claims=(
                ClaimDraft(
                    "异常观测定义",
                    "异常值是相对于数据整体模式显得极端或不寻常的观测，并不自动等于错误记录。",
                    "异常值在统计上通常如何定义？",
                ),
                ClaimDraft(
                    "错误与真实",
                    "极端观测可能来自录入、测量或传输错误，也可能是真实且罕见的个体或事件。",
                    "极端观测为什么可能是真实值而不是错误？",
                ),
                ClaimDraft(
                    "调查证据",
                    "删除或修正异常值前，应调查它是否来自记录或测量错误，还是来自真实的数据生成过程。",
                    "处理异常值前应检查哪些数据和领域证据？",
                ),
                ClaimDraft(
                    "删除影响",
                    "无依据地删除真实极端观测会改变目标估计，并可能引入偏倚。",
                    "为什么无依据删除异常值会改变分析结论？",
                ),
                ClaimDraft(
                    "稳健与敏感性",
                    "稳健方法和比较包含或不包含异常值结果的敏感性分析，都可以作为自动删除之外的选择。",
                    "异常值除了删除之外还可以如何处理？",
                ),
            ),
            learner_claim=ClaimDraft(
                "异常值的证据判断",
                "观测值极端只提供了需要调查的信号；只有独立证据表明记录错误时，修正或删除才有充分理由。",
                "为什么异常值不能直接判定为录入错误？",
            ),
            edges=(
                EdgeDraft(6, 2, "qualifies", 1),
                EdgeDraft(2, 3, "explains", 1),
                EdgeDraft(1, 6, "qualifies", 2),
                EdgeDraft(6, 4, "explains", 2),
            ),
        ),
        TaskDraft(
            task_id="pb_t08_label_encoding_order",
            kind="misconception",
            question="为什么对无序类别变量直接使用 1、2、3 编码可能误导某些模型？",
            target_concepts=("类别变量", "标签编码", "虚假顺序", "独热编码"),
            trigger="类别数字编码不会被模型当成大小关系",
            no_gap_learning_goal="理解类别变量的编码选择",
            single_gap_learning_goal="理解类别变量的编码选择",
            core_claims=(
                ClaimDraft(
                    "无序类别",
                    "无序类别变量的取值只有类别身份，没有自然的大小或距离关系。",
                    "无序类别变量和有序变量有什么区别？",
                ),
                ClaimDraft(
                    "数值顺序",
                    "把无序类别编码为 1、2、3 可能让依赖数值大小或距离的模型把编码顺序当成真实关系。",
                    "数字标签如何给无序类别引入虚假顺序？",
                ),
                ClaimDraft(
                    "编码选择",
                    "独热编码可以在不引入任意整数顺序的情况下表示无序类别，但会增加特征列数。",
                    "无序类别变量常用哪些不引入顺序的编码方法？",
                ),
                ClaimDraft(
                    "模型依赖",
                    "编码风险取决于模型如何使用输入数值以及类别是否真正有序，不能脱离模型和变量语义判断。",
                    "类别编码风险为什么取决于模型和变量语义？",
                ),
                ClaimDraft(
                    "编码验证",
                    "编码方案应符合变量语义和下游模型的数值假设。",
                    "如何验证类别变量编码方案是否合适？",
                ),
            ),
            learner_claim=ClaimDraft(
                "虚假顺序",
                "无序类别的数字标签是人为符号；若模型把它们当作大小或距离，就会学习到不存在的类别顺序。",
                "为什么类别数字编码可能造成虚假的大小关系？",
            ),
            edges=(
                EdgeDraft(6, 2, "explains", 1),
                EdgeDraft(2, 3, "explains", 1),
                EdgeDraft(1, 4, "qualifies", 2),
                EdgeDraft(4, 5, "explains", 2),
            ),
        ),
        TaskDraft(
            task_id="pb_t09_skewed_summary",
            kind="goal",
            question="面对偏态收入数据，为什么报告中位数和四分位距通常比只报告均值更稳健？",
            target_concepts=("偏态分布", "中位数", "四分位距", "稳健摘要"),
            trigger="为偏态数据选择稳健摘要",
            no_gap_learning_goal="掌握数据分布的基本描述",
            single_gap_learning_goal="为偏态数据选择稳健摘要",
            core_claims=(
                ClaimDraft(
                    "偏态与尾部",
                    "偏态分布具有不对称的尾部，少量极端值可能远离大多数观测。",
                    "偏态分布和长尾会给收入数据带来什么特征？",
                ),
                ClaimDraft(
                    "均值敏感",
                    "均值会受到极端观测和长尾的较大影响，可能不能代表典型观测的位置。",
                    "为什么收入分布偏态时均值可能不代表典型水平？",
                ),
                ClaimDraft(
                    "中位数位置",
                    "中位数是把排序数据分成两半的位置统计量，对少量极端值通常比均值更不敏感。",
                    "中位数为什么通常比均值更不受极端收入影响？",
                ),
                ClaimDraft(
                    "四分位距",
                    "四分位距是第三四分位数与第一四分位数之差，描述中间一半观测的跨度。",
                    "四分位距如何描述收入数据的离散程度？",
                ),
                ClaimDraft(
                    "报告选择",
                    "摘要统计应结合分布形状和分析目的；偏态收入数据通常优先报告中位数与四分位距。",
                    "偏态收入数据应如何选择和组合摘要统计量？",
                ),
            ),
            learner_claim=ClaimDraft(
                "稳健摘要选择",
                "在偏态且有长尾的收入数据中，中位数和四分位距通常能稳健地描述中心与中间变异。",
                "为什么偏态收入数据适合优先报告中位数和四分位距？",
            ),
            edges=(
                EdgeDraft(6, 2, "explains", 1),
                EdgeDraft(2, 3, "contrasts", 1),
                EdgeDraft(1, 6, "explains", 2),
                EdgeDraft(6, 5, "qualifies", 2),
            ),
        ),
        TaskDraft(
            task_id="pb_t10_residual_diagnostics",
            kind="goal",
            question="如何用残差图判断线性回归模型是否可能违反线性、等方差或独立性假设？",
            target_concepts=("线性回归", "残差", "模型诊断", "等方差"),
            trigger="用诊断图检查模型假设",
            no_gap_learning_goal="掌握回归结果的基本阅读",
            single_gap_learning_goal="用诊断图检查模型假设",
            core_claims=(
                ClaimDraft(
                    "残差定义",
                    "残差是观测响应与模型拟合值之间的差，用来观察模型未解释部分的结构。",
                    "线性回归残差表示什么？",
                ),
                ClaimDraft(
                    "线性诊断",
                    "残差对拟合值或预测变量呈现系统性曲线或趋势，可能说明线性关系假设不合适。",
                    "残差图中的系统性曲线可能说明什么？",
                ),
                ClaimDraft(
                    "等方差诊断",
                    "残差散布随拟合值扩大或缩小形成漏斗形，可能提示误差方差不恒定。",
                    "残差图如何提示异方差？",
                ),
                ClaimDraft(
                    "独立性诊断",
                    "按时间或观测顺序排列的残差若有连续性、周期性或成段模式，可能提示误差并不独立。",
                    "按顺序观察残差时哪些模式可能提示不独立？",
                ),
                ClaimDraft(
                    "诊断边界",
                    "残差图是检查模型假设的诊断工具，未发现明显模式并不等于假设已被严格证明。",
                    "为什么残差诊断不能严格证明回归假设成立？",
                ),
            ),
            learner_claim=ClaimDraft(
                "诊断图检查假设",
                "可以组合残差-拟合值图和按观测顺序的残差图，分别检查线性、等方差和独立性等潜在问题。",
                "如何用残差图检查线性回归的主要假设？",
            ),
            edges=(
                EdgeDraft(3, 6, "explains", 1),
                EdgeDraft(6, 5, "qualifies", 1),
                EdgeDraft(1, 4, "explains", 2),
                EdgeDraft(4, 5, "qualifies", 2),
            ),
        ),
        TaskDraft(
            task_id="pb_t11_missing_data_strategy",
            kind="goal",
            question="如何根据缺失机制选择删除、均值填补或模型化填补策略？",
            target_concepts=("缺失数据", "MCAR/MAR/MNAR", "填补", "敏感性分析"),
            trigger="为缺失数据选择处理策略",
            no_gap_learning_goal="掌握数据清理的基本原则",
            single_gap_learning_goal="为缺失数据选择处理策略",
            core_claims=(
                ClaimDraft(
                    "缺失机制",
                    "缺失数据处理应依据缺失机制及其与分析变量的关系，而不能只依据缺失比例。",
                    "选择缺失数据处理方法为什么要考虑缺失机制？",
                ),
                ClaimDraft(
                    "完整案例删除",
                    "删除含缺失记录会减少样本量，并在缺失不是随机或与分析变量相关时产生偏倚风险。",
                    "完整案例删除缺失记录有什么代价和偏倚风险？",
                ),
                ClaimDraft(
                    "均值填补",
                    "简单均值填补会压缩变量的变异，并且通常没有反映填补值本身的不确定性。",
                    "均值填补为什么可能低估变异和不确定性？",
                ),
                ClaimDraft(
                    "模型化填补",
                    "多重填补或其他模型化方法可以利用协变量预测缺失值，并在合并分析时传播填补不确定性。",
                    "模型化或多重填补如何利用协变量并处理不确定性？",
                ),
                ClaimDraft(
                    "敏感性分析",
                    "当缺失机制无法由数据完全验证时，应比较合理处理假设下的结果，并报告策略选择及其影响。",
                    "缺失机制不确定时为什么要做敏感性分析？",
                ),
            ),
            learner_claim=ClaimDraft(
                "缺失策略选择",
                "删除、简单填补和模型化填补没有普遍最优的固定顺序，应根据缺失机制和分析目标选择。",
                "如何根据缺失机制和分析目标选择缺失数据处理策略？",
            ),
            edges=(
                EdgeDraft(1, 6, "prerequisite", 1),
                EdgeDraft(6, 2, "qualifies", 1),
                EdgeDraft(3, 4, "contrasts", 2),
                EdgeDraft(4, 5, "qualifies", 2),
            ),
        ),
        TaskDraft(
            task_id="pb_t12_ab_test_design",
            kind="goal",
            question="如何设计一个简单 A/B 测试来估计改版是否提升转化率？",
            target_concepts=("A/B 测试", "随机分配", "转化率", "实验设计"),
            trigger="设计随机对照实验并解释结果",
            no_gap_learning_goal="理解实验数据的基本比较",
            single_gap_learning_goal="设计随机对照实验并解释结果",
            core_claims=(
                ClaimDraft(
                    "随机分配",
                    "将符合条件的用户随机分配到控制组和处理组，有助于使两组在期望意义上可比。",
                    "A/B 测试为什么需要把用户随机分配到两组？",
                ),
                ClaimDraft(
                    "组别与指标",
                    "A/B 测试开始前应预先定义控制版本、处理版本和主要转化指标。",
                    "A/B 测试开始前需要预先定义哪些组别和指标？",
                ),
                ClaimDraft(
                    "样本量与功效",
                    "样本量应能支持对预期效应的有信息量估计，不能只根据早期少量数据停止实验。",
                    "A/B 测试如何考虑样本量和统计功效？",
                ),
                ClaimDraft(
                    "效果与不确定性",
                    "结果应报告处理组与控制组转化率之差及其不确定性。",
                    "A/B 测试结果应如何报告转化率差异和不确定性？",
                ),
                ClaimDraft(
                    "实验有效性",
                    "分析应检查组间干扰、提前窥视和执行偏差，因为这些问题会削弱因果解释。",
                    "哪些执行问题会削弱 A/B 测试的因果解释？",
                ),
            ),
            learner_claim=ClaimDraft(
                "随机对照实验解释",
                "随机分配和带不确定性的处理组—控制组比较，是把转化率差异解释为改版因果效果的关键基础。",
                "如何设计并解释一个能支持因果结论的 A/B 测试？",
            ),
            edges=(
                EdgeDraft(1, 6, "prerequisite", 1),
                EdgeDraft(6, 4, "explains", 1),
                EdgeDraft(3, 4, "explains", 2),
                EdgeDraft(4, 5, "qualifies", 2),
            ),
        ),
    )


if __name__ == "__main__":
    raise SystemExit(main())
