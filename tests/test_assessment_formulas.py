"""Formula recognition preserves raw bracket widths for strict validation."""

import pytest

from ds_course_agent.assessment.formulas import analyze_formula_quality, extract_formulas
from ds_course_agent.assessment.models import FormulaQuality


@pytest.mark.parametrize("delimiters", [("", ""), ("$", "$"), (r"\(", r"\)"), (r"\[", r"\]")])
@pytest.mark.parametrize(
    ("formula", "quality"),
    [
        ("f(x)=x", FormulaQuality.VALID),
        ("f（x）=x", FormulaQuality.VALID),
        ("f（x)=x", FormulaQuality.MALFORMED),
        ("f(x）=x", FormulaQuality.MALFORMED),
    ],
)
def test_function_equations_are_extracted_verbatim_and_validated_strictly(delimiters, formula, quality):
    opening, closing = delimiters
    text = f"函数的定义为 {opening}{formula}{closing}，用于表示输入与输出的对应关系。"
    assert extract_formulas(text) == (formula,)
    formulas, actual_quality = analyze_formula_quality(text)
    assert actual_quality is quality
    assert formulas == ((formula,) if quality is FormulaQuality.VALID else ())
