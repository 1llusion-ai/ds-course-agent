"""
幂等性测试
验证 record_event() 和 aggregate_profile() 重复运行不会重复记账
"""
import sys
import os
import json
import tempfile
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.memory_core import MemoryCore
from core.events import build_concept_mentioned_event, build_session_end_event
from core.profile_models import StudentProfile


def test_record_event_idempotency():
    """
    测试：同一事件重复记录不应重复记账
    策略：事件ID唯一，重复写入文件但不影响统计（因为证据链用event_id去重）
    """
    print("=" * 60)
    print("测试 1: record_event 幂等性")
    print("=" * 60)

    # 使用临时目录
    tmpdir = tempfile.mkdtemp()
    try:
        core = MemoryCore(base_dir=tmpdir)

        # 创建同一事件的多个副本（模拟重复调用）
        event = build_concept_mentioned_event(
            session_id="sess_001",
            student_id="stu_001",
            concept_id="svm",
            concept_name="支持向量机",
            chapter="第6章",
            question_type="概念理解",
            matched_score=0.95,
            raw_question="什么是SVM？"
        )

        # 记录3次（模拟重复调用）
        core.record_event(event)
        core.record_event(event)  # 重复
        core.record_event(event)  # 再重复

        # 验证：文件中应有3行（我们允许重复写入，但聚合时应去重）
        events = core.load_events("stu_001")
        print(f"  事件记录次数: {len(events)}")

        # 关键：聚合时应按 event_id 去重
        unique_ids = set(e.event_id for e in events)
        print(f"  唯一事件ID数: {len(unique_ids)}")

        if len(unique_ids) == 1:
            print("  [OK] 重复事件有相同ID，可去重")
        else:
            print("  [WARN] 重复记录产生了不同ID")

        # 聚合后检查
        core.aggregate_profile("stu_001")
        profile = core.get_profile("stu_001")

        svm_concept = profile.get_concept_focus("svm")
        if svm_concept:
            print(f"  SVM mention_count: {svm_concept.mention_count}")
            print(f"  SVM evidence数量: {len(svm_concept.evidence)}")

            # 关键检查：mention_count 应为 1（去重后）
            if svm_concept.mention_count == 1:
                print("  [PASS] mention_count 正确（去重后）")
                return True
            else:
                print(f"  [FAIL] mention_count 错误: 期望 1, 实际 {svm_concept.mention_count}")
                return False
        else:
            print("  [FAIL] 未找到 SVM 概念记录")
            return False

    finally:
        shutil.rmtree(tmpdir)


def test_aggregate_profile_idempotency():
    """
    测试：aggregate_profile 重复运行不应重复统计
    """
    print("\n" + "=" * 60)
    print("测试 2: aggregate_profile 幂等性")
    print("=" * 60)

    tmpdir = tempfile.mkdtemp()
    try:
        core = MemoryCore(base_dir=tmpdir)

        # 记录3个不同事件（手动设置时间戳以确保递增）
        import time
        base_time = int(time.time()) - 10  # 10秒前

        for i, concept_id in enumerate(["svm", "svm", "svm_kernel"]):
            event = build_concept_mentioned_event(
                session_id=f"sess_{i}",
                student_id="stu_002",
                concept_id=concept_id,
                concept_name="支持向量机" if concept_id == "svm" else "核函数",
                chapter="第6章",
                question_type="概念理解",
                matched_score=0.9,
                raw_question=f"问题{i}"
            )
            event.timestamp = base_time + i  # 确保时间戳递增
            core.record_event(event)

        print(f"  记录事件数: 3")

        # 第一次聚合
        core.aggregate_profile("stu_002")
        profile1 = core.get_profile("stu_002")
        count1 = profile1.get_concept_focus("svm").mention_count if profile1.get_concept_focus("svm") else 0
        last_agg_time = profile1.last_aggregate_time
        print(f"  第一次聚合后 SVM mention_count: {count1}, last_aggregate_time: {last_agg_time}")

        # 等待一小段时间，确保 last_aggregate_time > 所有事件时间戳
        time.sleep(0.1)

        # 第二次聚合（应基于上次聚合时间，只处理新事件）
        core.aggregate_profile("stu_002")
        profile2 = core.get_profile("stu_002")
        count2 = profile2.get_concept_focus("svm").mention_count if profile2.get_concept_focus("svm") else 0
        print(f"  第二次聚合后 SVM mention_count: {count2}")

        # 第三次聚合
        core.aggregate_profile("stu_002")
        profile3 = core.get_profile("stu_002")
        count3 = profile3.get_concept_focus("svm").mention_count if profile3.get_concept_focus("svm") else 0
        print(f"  第三次聚合后 SVM mention_count: {count3}")

        if count1 == count2 == count3 == 2:  # 2个svm事件
            print("  [PASS] 重复聚合未重复记账")
            return True
        else:
            print(f"  [FAIL] 计数变化: {count1} -> {count2} -> {count3}")
            return False

    finally:
        shutil.rmtree(tmpdir)


def test_full_recalc_correctness():
    """
    测试：全量重算应得到正确结果
    """
    print("\n" + "=" * 60)
    print("测试 3: full_recalc 正确性")
    print("=" * 60)

    tmpdir = tempfile.mkdtemp()
    try:
        core = MemoryCore(base_dir=tmpdir)

        # 记录事件
        for i in range(5):
            event = build_concept_mentioned_event(
                session_id=f"sess_{i}",
                student_id="stu_003",
                concept_id="overfitting",
                concept_name="过拟合",
                chapter="第8章",
                question_type="概念理解",
                matched_score=0.9,
                raw_question=f"问题{i}"
            )
            core.record_event(event)

        # 增量聚合
        core.aggregate_profile("stu_003")
        profile1 = core.get_profile("stu_003")
        count1 = profile1.get_concept_focus("overfitting").mention_count
        print(f"  增量聚合 mention_count: {count1}")

        # 全量重算
        core.aggregate_profile("stu_003", full_recalc=True)
        profile2 = core.get_profile("stu_003")
        count2 = profile2.get_concept_focus("overfitting").mention_count
        print(f"  全量重算 mention_count: {count2}")

        if count1 == count2 == 5:
            print("  [PASS] 增量和全量结果一致")
            return True
        else:
            print(f"  [FAIL] 结果不一致: {count1} vs {count2}")
            return False

    finally:
        shutil.rmtree(tmpdir)


def test_daily_counter_consistency():
    """
    测试：日计数器滑动窗口逻辑正确
    """
    print("\n" + "=" * 60)
    print("测试 4: 日计数器滑动窗口一致性")
    print("=" * 60)

    tmpdir = tempfile.mkdtemp()
    try:
        core = MemoryCore(base_dir=tmpdir)

        # 模拟31天前的事件（应被滑动窗口排除）
        import time
        now = int(time.time())

        # 创建31天前的事件（直接修改时间戳）
        old_event = build_concept_mentioned_event(
            session_id="sess_old",
            student_id="stu_004",
            concept_id="pca",
            concept_name="PCA",
            chapter="第7章",
            question_type="概念理解",
            matched_score=0.9,
            raw_question="旧问题"
        )
        old_event.timestamp = now - 31 * 86400  # 31天前
        core.record_event(old_event)

        # 创建今天的事件
        new_event = build_concept_mentioned_event(
            session_id="sess_new",
            student_id="stu_004",
            concept_id="pca",
            concept_name="PCA",
            chapter="第7章",
            question_type="概念理解",
            matched_score=0.9,
            raw_question="新问题"
        )
        core.record_event(new_event)

        # 聚合
        core.aggregate_profile("stu_004")
        profile = core.get_profile("stu_004")

        pca_focus = profile.get_concept_focus("pca")
        if pca_focus:
            print(f"  PCA mention_count: {pca_focus.mention_count}")
            print(f"  期望: 1 (旧事件被滑动窗口排除)")

            if pca_focus.mention_count == 1:
                print("  [PASS] 滑动窗口正确排除了旧事件")
                return True
            else:
                print(f"  [FAIL] 计数错误")
                return False
        else:
            print("  [FAIL] 未找到 PCA 记录")
            return False

    finally:
        shutil.rmtree(tmpdir)


def main():
    results = []

    results.append(("record_event 幂等性", test_record_event_idempotency()))
    results.append(("aggregate_profile 幂等性", test_aggregate_profile_idempotency()))
    results.append(("full_recalc 正确性", test_full_recalc_correctness()))
    results.append(("日计数器滑动窗口", test_daily_counter_consistency()))

    print("\n" + "=" * 60)
    print("汇总结果")
    print("=" * 60)
    for name, passed in results:
        status = "[PASS]" if passed else "[FAIL]"
        print(f"  {status} {name}")

    all_passed = all(r[1] for r in results)
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
