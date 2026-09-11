from ds_course_agent.kb.parser import PageResult, ParsedBlock, _build_result
from ds_course_agent.kb.parser_quality import measure_parser_quality


def test_measure_parser_quality_reports_duplicates_and_private_glyphs():
    repeated = "这是一段足够长的重复文本，用于验证父子节点内容被重复抽取时能够被质量指标识别。" * 2
    result = _build_result(
        "sample.pdf",
        [
            PageResult(
                page_num=1,
                text=(
                    f"{repeated}\n{repeated}\nP a n d a s\U00100948\ufffd\n"
                    "Logo of the book series\nScreenshot of the course website"
                ),
                parser="datalab",
                blocks=[
                    ParsedBlock(block_type="Text", text=f"{repeated}\nP a n d a s\U00100948\ufffd"),
                    ParsedBlock(block_type="Equation", text="w 2 1 + w 2 2"),
                    ParsedBlock(block_type="Table", text="B C D E"),
                ],
            ),
            PageResult(page_num=2, text="", parser="datalab"),
        ],
        "datalab",
    )

    metrics = measure_parser_quality(result, expected_titles=["重复文本", "不存在的标题"])

    assert metrics.total_pages == 2
    assert metrics.nonempty_pages == 1
    assert metrics.page_coverage == 0.5
    assert metrics.duplicate_candidate_chars >= len(repeated.replace(" ", ""))
    assert metrics.duplicate_candidate_ratio > 0
    assert metrics.private_use_chars == 1
    assert metrics.replacement_chars == 1
    assert metrics.spaced_alphanumeric_sequences == 4
    assert metrics.text_spaced_alphanumeric_sequences == 1
    assert metrics.equation_spaced_alphanumeric_sequences == 2
    assert metrics.table_spaced_alphanumeric_sequences == 1
    assert metrics.prose_letter_spacing_candidates == 1
    assert metrics.visual_description_candidates == 2
    assert metrics.title_recall == 0.5


def test_measure_parser_quality_ignores_latex_spacing():
    result = _build_result(
        "sample.pdf",
        [
            PageResult(
                page_num=1,
                text="矩阵表达式 $u^T C u$\n$$L = u^T C u + 1$$",
                blocks=[
                    ParsedBlock(block_type="Text", text="矩阵表达式 $u^T C u$"),
                    ParsedBlock(block_type="Equation", text="$$L = u^T C u + 1$$"),
                ],
            )
        ],
        "marker",
    )

    metrics = measure_parser_quality(result)

    assert metrics.spaced_alphanumeric_sequences == 0
    assert metrics.text_spaced_alphanumeric_sequences == 0
    assert metrics.equation_spaced_alphanumeric_sequences == 0
