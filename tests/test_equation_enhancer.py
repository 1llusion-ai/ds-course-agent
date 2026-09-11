import pytest

from ds_course_agent.kb.equation_enhancer import EquationReview, merge_marker_equation_ocr
from ds_course_agent.kb.parser import PageResult, ParsedBlock, _build_result


def _result(equations: list[ParsedBlock]):
    page = PageResult(
        page_num=143,
        text="\n".join(block.text for block in equations),
        blocks=equations,
    )
    return _build_result("book.pdf", [page], "marker")


def test_merge_marker_equation_ocr_replaces_only_valid_exact_id_matches():
    baseline = _result(
        [
            ParsedBlock(block_type="Equation", block_id="eq-1", text="W 2 2"),
            ParsedBlock(block_type="Equation", block_id="eq-2", text="x 2"),
            ParsedBlock(block_type="Equation", block_id="eq-3", text="y 2"),
        ]
    )
    ocr = _result(
        [
            ParsedBlock(block_type="Equation", block_id="eq-1", text=r"$$\|W\|_2^2$$"),
            ParsedBlock(block_type="Equation", block_id="eq-2", text=r"$$\frac{x}{2$$"),
            ParsedBlock(block_type="Equation", block_id="other", text=r"$$y^2$$"),
        ]
    )

    review = EquationReview(
        approved_ocr_block_ids=frozenset({"eq-1", "eq-2"}),
        text_overrides={},
        removed_block_ids=frozenset(),
    )
    enhanced = merge_marker_equation_ocr(baseline, ocr, review)

    assert enhanced.source_equations == 3
    assert enhanced.ocr_equations == 3
    assert enhanced.structurally_valid_ocr_equations == 2
    assert enhanced.replaced_equations == 1
    assert enhanced.approved_ocr_replacements == 1
    assert enhanced.manual_replacements == 0
    assert enhanced.removed_equations == 0
    assert enhanced.unreviewed_equations == 1
    assert enhanced.missing_equations == 0
    assert enhanced.rejected_equations == 1
    assert [block.text for block in enhanced.parse_result.pages[0].blocks] == [
        r"$$\|W\|_2^2$$",
        "x 2",
        "y 2",
    ]
    assert enhanced.parse_result.pages[0].text == "$$\\|W\\|_2^2$$\nx 2\ny 2"


def test_merge_marker_equation_ocr_rejects_mixed_prose_and_math():
    baseline = _result([ParsedBlock(block_type="Equation", block_id="eq-1", text="x=9")])
    ocr = _result(
        [
            ParsedBlock(
                block_type="Equation",
                block_id="eq-1",
                text="平均值：\n$$\\bar{x}=9$$\n方差：$S_x^2=11$",
            )
        ]
    )

    review = EquationReview(
        approved_ocr_block_ids=frozenset({"eq-1"}),
        text_overrides={},
        removed_block_ids=frozenset(),
    )
    enhanced = merge_marker_equation_ocr(baseline, ocr, review)

    assert enhanced.replaced_equations == 0
    assert enhanced.rejected_equations == 1
    assert enhanced.parse_result.pages[0].text == "x=9"


def test_merge_marker_equation_ocr_applies_manual_override_and_removal():
    baseline = _result(
        [
            ParsedBlock(block_type="Equation", block_id="eq-1", text="x 2"),
            ParsedBlock(block_type="Equation", block_id="eq-noise", text="0 0 #"),
        ]
    )
    review = EquationReview(
        approved_ocr_block_ids=frozenset(),
        text_overrides={"eq-1": r"$$x^2$$"},
        removed_block_ids=frozenset({"eq-noise"}),
    )

    enhanced = merge_marker_equation_ocr(baseline, _result([]), review)

    assert enhanced.replaced_equations == 1
    assert enhanced.manual_replacements == 1
    assert enhanced.removed_equations == 1
    assert enhanced.unreviewed_equations == 0
    assert enhanced.parse_result.pages[0].text == r"$$x^2$$"


def test_merge_marker_equation_ocr_rejects_overlapping_review_actions():
    baseline = _result([ParsedBlock(block_type="Equation", block_id="eq-1", text="x")])
    review = EquationReview(
        approved_ocr_block_ids=frozenset({"eq-1"}),
        text_overrides={"eq-1": r"$$x$$"},
        removed_block_ids=frozenset(),
    )

    with pytest.raises(ValueError, match="overlap"):
        merge_marker_equation_ocr(baseline, _result([]), review)


def test_merge_marker_equation_ocr_rejects_invalid_manual_override():
    baseline = _result([ParsedBlock(block_type="Equation", block_id="eq-1", text="x")])
    review = EquationReview(
        approved_ocr_block_ids=frozenset(),
        text_overrides={"eq-1": r"$$\frac{x}{2$$"},
        removed_block_ids=frozenset(),
    )

    with pytest.raises(ValueError, match="invalid display-math overrides"):
        merge_marker_equation_ocr(baseline, _result([]), review)
