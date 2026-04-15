"""端到端测试：验证 misconception-handling skill 的识别、纠正、画像写入链路。"""

import json
import sys
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch

project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from core.skill_system import SkillRegistry
from core.memory_core import MemoryCore, get_memory_core, aggregate_profile


def test_misconception_skill_end_to_end():
    """测试显式错误认知（C类）被识别、纠正并写入 active weak spots。"""
    # 使用临时目录隔离测试数据
    tmpdir = tempfile.mkdtemp(prefix="misconception_e2e_")
    tmp_path = Path(tmpdir)

    # 替换全局 memory_core 为临时实例
    global _memory_core
    test_core = MemoryCore(base_dir=str(tmp_path))

    # patch get_memory_core 返回临时实例（executor 内部会调用它）
    with patch("core.memory_core.get_memory_core", return_value=test_core):
        with patch("core.memory_core._memory_core", test_core):
            module = SkillRegistry().load_module("misconception-handling")

            fake_json = json.dumps(
                {
                    "classification": "C",
                    "misconception_text": "kNN是无监督算法",
                    "correct_answer": "kNN属于监督学习算法",
                    "severity": "high",
                },
                ensure_ascii=False,
            )

            with patch.object(module, "_call_llm", return_value=fake_json) as mock_llm:
                # 同时 patch answer generator 的 LLM，避免真实调用
                with patch.object(
                    module,
                    "_generate_direct_correction_answer",
                    return_value="这个说法不对。kNN 属于监督学习算法，因为它需要标签来预测新样本。",
                ):
                    result = module.execute(
                        user_question="kNN就是无监督算法",
                        student_id="stu_test_001",
                        session_id="sess_test_001",
                        turn_id="1",
                    )

            # 1. 验证分类 LLM 被调用（说明进入了 detector）
            mock_llm.assert_called_once()

            # 2. 验证回答包含纠正语气
            assert "不对" in result or "错误" in result, f"回答未体现纠正语气: {result}"
            assert "监督学习" in result, f"回答未给出正确概念: {result}"

            # 3. 验证画像聚合后存在 active weak spot
            aggregate_profile("stu_test_001")
            profile = test_core.get_profile("stu_test_001")

            assert len(profile.weak_spot_candidates) > 0, "未生成 active weak spot"

            spot = profile.weak_spot_candidates[0]
            assert spot.concept_id == "knn", f"concept_id 不匹配: {spot.concept_id}"
            assert any(
                s.get("type") == "MISCONCEPTION" for s in spot.signals
            ), f"signals 中缺少 MISCONCEPTION 标记: {spot.signals}"

            print("=" * 60)
            print("测试通过！")
            print(f"回答: {result}")
            print(f"Active weak spots: {len(profile.weak_spot_candidates)}")
            print(f"Spot detail: {spot.to_dict()}")
            print("=" * 60)

    # 清理临时目录
    shutil.rmtree(tmpdir, ignore_errors=True)


def test_misconception_pending_weakness():
    """测试试探性错误（B类）进入 pending weak spots。"""
    tmpdir = tempfile.mkdtemp(prefix="misconception_e2e_")
    tmp_path = Path(tmpdir)

    test_core = MemoryCore(base_dir=str(tmpdir))

    with patch("core.memory_core.get_memory_core", return_value=test_core):
        with patch("core.memory_core._memory_core", test_core):
            module = SkillRegistry().load_module("misconception-handling")

            fake_json = json.dumps(
                {
                    "classification": "B",
                    "misconception_text": "kNN不是无监督算法吗",
                    "correct_answer": "kNN属于监督学习算法",
                    "severity": "medium",
                },
                ensure_ascii=False,
            )

            with patch.object(module, "_call_llm", return_value=fake_json):
                with patch.object(
                    module,
                    "_generate_gentle_correction_answer",
                    return_value="这里有个容易混淆的小点：kNN 其实属于监督学习算法。",
                ):
                    result = module.execute(
                        user_question="kNN不是无监督算法吗？",
                        student_id="stu_test_002",
                        session_id="sess_test_002",
                        turn_id="1",
                    )

            aggregate_profile("stu_test_002")
            profile = test_core.get_profile("stu_test_002")

            assert len(profile.pending_weak_spots) > 0, "未生成 pending weak spot"
            spot = profile.pending_weak_spots[0]
            assert spot.concept_id == "knn", f"concept_id 不匹配: {spot.concept_id}"

            print("=" * 60)
            print("B类测试通过！")
            print(f"回答: {result}")
            print(f"Pending weak spots: {len(profile.pending_weak_spots)}")
            print("=" * 60)

    shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    test_misconception_skill_end_to_end()
    test_misconception_pending_weakness()
