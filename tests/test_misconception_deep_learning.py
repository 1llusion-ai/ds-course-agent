"""端到端测试：验证 misconception-handling skill 对'深度学习不是机器学习的一种'的识别、纠正和画像写入。"""

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
from core.memory_core import MemoryCore, aggregate_profile


def test_deep_learning_misconception():
    """测试明确错误认知'深度学习不是机器学习的一种'被识别、纠正并写入 active weak spots。"""
    tmpdir = tempfile.mkdtemp(prefix="misconception_e2e_")
    test_core = MemoryCore(base_dir=str(tmpdir))

    with patch("core.memory_core.get_memory_core", return_value=test_core):
        with patch("core.memory_core._memory_core", test_core):
            module = SkillRegistry().load_module("misconception-handling")

            fake_json = json.dumps(
                {
                    "classification": "C",
                    "misconception_text": "深度学习不是机器学习的一种",
                    "correct_answer": "深度学习是机器学习的一个重要分支",
                    "severity": "high",
                },
                ensure_ascii=False,
            )

            with patch.object(module, "_call_llm", return_value=fake_json) as mock_llm:
                with patch.object(
                    module,
                    "_generate_direct_correction_answer",
                    return_value="这个说法不对。深度学习其实是机器学习的一个重要分支，它通过深层神经网络来自动学习数据的特征表示。",
                ):
                    result = module.execute(
                        user_question="深度学习不是机器学习的一种",
                        student_id="stu_test_dl",
                        session_id="sess_test_dl",
                        turn_id="1",
                    )

            # 1. 验证分类 LLM 被调用（说明进入了 detector，因为问题里有"不是"这个 cue）
            mock_llm.assert_called_once()

            # 2. 验证回答包含纠正语气和正确答案
            assert "不对" in result or "错误" in result, f"回答未体现纠正语气: {result}"
            assert "深度学习" in result and "机器学习" in result, f"回答未涉及核心概念: {result}"

            # 3. 验证画像聚合后存在 active weak spot，且 concept_id 不是 knn，而是匹配到的概念
            aggregate_profile("stu_test_dl")
            profile = test_core.get_profile("stu_test_dl")

            assert len(profile.weak_spot_candidates) > 0, "未生成 active weak spot"

            spot = profile.weak_spot_candidates[0]
            # concept_id 应该由 map_question_to_concepts 动态匹配，而不是硬编码
            assert spot.concept_id != "unknown", f"concept_id 未知，说明未匹配到知识点: {spot.concept_id}"
            assert any(
                s.get("type") == "MISCONCEPTION" for s in spot.signals
            ), f"signals 中缺少 MISCONCEPTION 标记: {spot.signals}"

            print("=" * 60)
            print("深度学习 misconception 测试通过！")
            print(f"回答: {result}")
            print(f"匹配到的 concept_id: {spot.concept_id}")
            print(f"Active weak spots: {len(profile.weak_spot_candidates)}")
            print(f"Spot detail: {spot.to_dict()}")
            print("=" * 60)

    shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    test_deep_learning_misconception()
