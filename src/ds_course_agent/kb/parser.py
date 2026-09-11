"""
课程 PDF 解析模块

解析策略：
- 默认使用本地 Marker 解析（避免未显式授权时上传 PDF）
- 可显式选择 Datalab 云端 API（Marker 云端版，无需本地 GPU），并支持 auto 回退
- 对已有文本层的 PDF，可使用 PyPDF plain/layout 作为轻量本地基线
- 支持页码范围选择
- 输出 Markdown 格式，保留结构信息
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Literal

ParserMode = Literal["marker", "auto", "datalab", "pypdf-plain", "pypdf-layout"]
PyPDFExtractionMode = Literal["plain", "layout"]
DEFAULT_MARKER_TIMEOUT_SECONDS = 7200
IGNORED_MARKER_BLOCK_TYPES = frozenset(
    {
        "Diagram",
        "Figure",
        "FigureGroup",
        "Handwriting",
        "PageFooter",
        "PageHeader",
        "Picture",
        "PictureGroup",
    }
)
MARKER_REPLACEMENT_GLYPH = "\ufffd\ufffd"
MARKER_TILDE_BASES = "CKϕφ"


def _repair_marker_private_glyphs(text: str) -> str:
    """修复教材内嵌数学字体被 Marker 转成替换字符的问题。"""
    if "\ufffd" not in text:
        return text

    glyph = re.escape(MARKER_REPLACEMENT_GLYPH)

    # PDF 将波浪号存成私有字形。Marker 有时把它放在变量后，有时放在下标后。
    text = re.sub(
        rf"(?P<base>[{MARKER_TILDE_BASES}])(?P<suffix>test|[tiX])\s+{glyph}",
        lambda match: f"{match.group('base')}\u0303{match.group('suffix')}",
        text,
    )
    text = re.sub(
        rf"(?P<base>[{MARKER_TILDE_BASES}])\s*{glyph}(?:\s*(?P<suffix>test|[tiX]))?",
        lambda match: f"{match.group('base')}\u0303{match.group('suffix') or ''}",
        text,
    )

    # 剩余替换字符来自跨行公式的大型括号分片，本身不承载公式语义。
    text = re.sub(r"(?:\ufffd\s*)+", " ", text)
    return re.sub(r"[ \t]+", " ", text).strip()


class HTMLTextExtractor(HTMLParser):
    """从 HTML 中提取纯文本"""

    BLOCK_TAGS = {
        "blockquote",
        "br",
        "div",
        "figcaption",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "p",
        "pre",
        "table",
        "tr",
    }
    CELL_TAGS = {"td", "th"}

    def __init__(self) -> None:
        super().__init__()
        self.texts: list[str] = []
        self.skip_depth = 0
        self.math_delimiters: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.skip_depth += 1
        elif not self.skip_depth and tag == "math":
            attributes = dict(attrs)
            delimiter = "$$" if attributes.get("display") == "block" else "$"
            self.math_delimiters.append(delimiter)
            self.texts.append(f"\n{delimiter}" if delimiter == "$$" else delimiter)
        elif not self.skip_depth and tag in self.BLOCK_TAGS:
            self.texts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self.skip_depth = max(0, self.skip_depth - 1)
        elif not self.skip_depth and tag == "math" and self.math_delimiters:
            delimiter = self.math_delimiters.pop()
            self.texts.append(f"{delimiter}\n" if delimiter == "$$" else delimiter)
        elif not self.skip_depth and tag in self.BLOCK_TAGS:
            self.texts.append("\n")
        elif not self.skip_depth and tag in self.CELL_TAGS:
            self.texts.append("\t")

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.texts.append(data)

    def get_text(self) -> str:
        text = "".join(self.texts)
        lines = [re.sub(r"[^\S\n]+", " ", line).strip() for line in text.splitlines()]
        return "\n".join(line for line in lines if line)


@dataclass
class ParsedBlock:
    """Marker/Datalab 页面中的一个可检索内容块。"""

    block_type: str
    text: str
    block_id: str = ""
    bbox: tuple[float, float, float, float] | None = None
    section_hierarchy: tuple[tuple[int, str], ...] = ()


@dataclass
class PageResult:
    """单页解析结果"""

    page_num: int
    text: str
    parser: str = "marker"
    char_count: int = 0
    original_char_count: int = 0
    error: str | None = None
    blocks: list[ParsedBlock] = field(default_factory=list)


@dataclass
class PDFParseResult:
    """PDF 解析结果"""

    file_name: str
    total_pages: int
    pages: list[PageResult]
    marker_pages: int = 0
    success_rate: float = 0.0
    full_text: str = ""
    parser_mode: str = "marker"
    error: str | None = None


@dataclass
class ParseTrace:
    """解析追踪记录"""

    file_name: str
    total_pages: int
    parser_mode: str
    generated_at: str
    pages: list[dict]


def _get_marker_executable() -> str:
    """获取当前 Python 环境对应的 marker_single 可执行文件路径"""
    import sys

    python_dir = Path(sys.executable).resolve().parent
    # marker_single 与当前环境的 Python 可执行文件位于同一 Scripts/bin 目录。
    candidates = [
        python_dir / "marker_single.exe",
        python_dir / "marker_single",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return shutil.which("marker_single") or "marker_single"


MARKER_EXE = _get_marker_executable()


def parse_with_datalab(
    pdf_path: str, api_key: str | None = None, max_pages: int = 0, page_start: int = 1, mode: str = "balanced"
) -> tuple[bool, str, dict]:
    """
    使用 Datalab 云端 API 解析 PDF（Marker 云端版）

    Args:
        pdf_path: PDF 文件路径
        api_key: Datalab API Key，为 None 时从环境变量读取
        max_pages: 最大解析页数，0 表示全部
        page_start: 起始页码（1-based）
        mode: 解析模式 - fast / balanced / accurate

    Returns:
        tuple[bool, str, dict]: (成功标志, JSON 字符串, 结构化数据)
        结构化数据与本地 Marker JSON 格式一致，可直接复用逐页解析逻辑。
    """
    if api_key is None:
        try:
            import ds_course_agent.shared.config as config

            api_key = config.DATALAB_API_KEY
        except Exception:
            api_key = os.getenv("DATALAB_API_KEY", "")

    if not api_key or api_key == "your_datalab_api_key_here":
        return False, "DATALAB_API_KEY not set", {}

    if not os.path.exists(pdf_path):
        return False, f"File not found: {pdf_path}", {}

    try:
        import requests
    except ImportError:
        return False, "requests package is not installed", {}

    headers = {"X-API-Key": api_key}
    submit_url = "https://www.datalab.to/api/v1/convert"

    # 使用 JSON 格式，与本地 Marker 输出结构一致，支持逐页解析
    form_data = {
        "output_format": "json",
        "mode": mode,
    }

    if max_pages > 0:
        page_start_idx = page_start - 1
        page_end_idx = page_start_idx + max_pages - 1
        form_data["page_range"] = f"{page_start_idx}-{page_end_idx}"

    try:
        # 1. 提交文件
        print("  [Datalab] 上传并提交解析请求 (JSON 格式)...")
        with open(pdf_path, "rb") as f:
            response = requests.post(
                submit_url,
                headers=headers,
                files={"file": (os.path.basename(pdf_path), f, "application/pdf")},
                data=form_data,
                timeout=60,
            )

        if response.status_code != 200:
            return False, f"Datalab API error {response.status_code}: {response.text}", {}

        submit_data = response.json()
        if not submit_data.get("success"):
            return False, f"Datalab submit failed: {submit_data}", {}

        check_url = submit_data["request_check_url"]
        print("  [Datalab] 请求已提交，轮询结果...")

        # 2. 轮询等待结果
        poll_interval = 3
        max_wait = 600
        elapsed = 0

        while elapsed < max_wait:
            time.sleep(poll_interval)
            elapsed += poll_interval

            poll_resp = requests.get(check_url, headers=headers, timeout=30)
            if poll_resp.status_code != 200:
                return False, f"Datalab poll error {poll_resp.status_code}: {poll_resp.text}", {}

            result = poll_resp.json()
            status = result.get("status", "")

            if status == "complete":
                if not result.get("success"):
                    return False, f"Datalab conversion failed: {result.get('error', 'unknown')}", {}

                page_count = result.get("page_count", 0)
                quality = result.get("parse_quality_score", 0)
                print(f"  [Datalab] 解析完成: {page_count} 页, 质量评分: {quality}")

                # Datalab JSON 格式与 Marker 一致：{"children": [...Page objects...]}
                data = result.get("json", {})
                if not data:
                    return False, "Datalab returned empty JSON", {}

                return True, json.dumps(data, ensure_ascii=False), data

            elif status == "failed":
                return False, f"Datalab processing failed: {result.get('error', 'unknown')}", {}

            # 仍在处理中
            if elapsed % 15 == 0:
                print(f"  [Datalab] 仍在处理... ({elapsed}s)")

        return False, "Datalab timeout after 600s", {}

    except requests.exceptions.Timeout:
        return False, "Datalab request timeout", {}
    except Exception as e:
        return False, f"Datalab error: {str(e)}", {}


def parse_with_marker(
    pdf_path: str,
    output_dir: str | None = None,
    max_pages: int = 0,
    page_start: int = 1,
    timeout_seconds: int = DEFAULT_MARKER_TIMEOUT_SECONDS,
    enable_ocr: bool = False,
    page_numbers: tuple[int, ...] = (),
    equation_ocr_only: bool = False,
) -> tuple[bool, str, dict]:
    """
    使用 Marker 解析 PDF

    Returns:
        tuple[bool, str, dict]: (成功标志, 文本内容, 元数据)
    """
    if not os.path.exists(pdf_path):
        return False, "", {}
    if page_numbers and (max_pages > 0 or page_start != 1):
        return False, "page_numbers cannot be combined with max_pages or page_start", {}
    if any(page_number < 1 for page_number in page_numbers):
        return False, "page_numbers must use 1-based positive indexes", {}
    if equation_ocr_only and not enable_ocr:
        return False, "equation_ocr_only requires enable_ocr=True", {}

    if output_dir is None:
        output_dir = tempfile.mkdtemp()

    cmd = [
        MARKER_EXE,
        pdf_path,
        "--output_dir",
        output_dir,
        "--output_format",
        "json",
        "--mode",
        "fast",
        "--disable_image_extraction",
    ]
    if not enable_ocr:
        # 课程教材已有完整文本层；关闭 OCR 可避免重复文本和额外模型下载。
        cmd.append("--disable_ocr")
    if equation_ocr_only:
        cmd.extend(
            [
                "--converter_cls",
                "scripts.marker_equation_converter.EquationOcrPdfConverter",
            ]
        )

    if page_numbers:
        page_range = ",".join(str(page_number - 1) for page_number in sorted(set(page_numbers)))
        cmd.extend(["--page_range", page_range])
    elif max_pages > 0:
        # Marker 使用 0-based 索引，page_range 格式为 "0-4"
        page_start_idx = page_start - 1
        page_end_idx = page_start_idx + max_pages - 1
        cmd.extend(["--page_range", f"{page_start_idx}-{page_end_idx}"])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_seconds)

        if result.returncode != 0:
            return False, f"Marker failed: {result.stderr}", {}

        # Marker outputs to a subdirectory named after the PDF file
        # Due to encoding issues on Windows, we need to find the JSON file dynamically
        json_files = []
        for root, _dirs, files in os.walk(output_dir):
            for f in files:
                if f.endswith(".json") and not f.endswith("_meta.json"):
                    json_files.append(os.path.join(root, f))

        if not json_files:
            return False, f"Output JSON not found in: {output_dir}", {}

        # Use the first (and usually only) JSON file found
        json_path = json_files[0]

        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)

        return True, json.dumps(data, ensure_ascii=False), data

    except subprocess.TimeoutExpired:
        return False, f"Marker timeout after {timeout_seconds}s", {}
    except Exception as e:
        return False, f"Marker error: {str(e)}", {}


def parse_with_pypdf(
    pdf_path: str,
    max_pages: int = 0,
    page_start: int = 1,
    extraction_mode: PyPDFExtractionMode = "layout",
) -> tuple[bool, str, list[PageResult]]:
    """使用 PDF 自带文本层逐页提取文本，不执行 OCR。"""
    if not os.path.exists(pdf_path):
        return False, f"File not found: {pdf_path}", []
    if page_start < 1:
        return False, "page_start must be >= 1", []

    try:
        from pypdf import PdfReader
    except ImportError:
        return False, "pypdf package is not installed", []

    try:
        reader = PdfReader(pdf_path)
        start_idx = page_start - 1
        end_idx = len(reader.pages) if max_pages <= 0 else min(len(reader.pages), start_idx + max_pages)
        if start_idx >= len(reader.pages):
            return False, f"page_start exceeds PDF page count: {len(reader.pages)}", []

        pages: list[PageResult] = []
        parser_name = f"pypdf-{extraction_mode}"
        for page_idx in range(start_idx, end_idx):
            try:
                text = reader.pages[page_idx].extract_text(extraction_mode=extraction_mode) or ""
                text = text.strip()
                pages.append(
                    PageResult(
                        page_num=page_idx + 1,
                        text=text,
                        parser=parser_name,
                        char_count=len(text),
                        original_char_count=len(text),
                    )
                )
            except Exception as exc:
                pages.append(
                    PageResult(
                        page_num=page_idx + 1,
                        text="",
                        parser=parser_name,
                        error=str(exc),
                    )
                )
        return True, "", pages
    except Exception as exc:
        return False, f"PyPDF error: {exc}", []


def _parse_bbox(value: object) -> tuple[float, float, float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        x1, y1, x2, y2 = (float(item) for item in value)
        return x1, y1, x2, y2
    except (TypeError, ValueError):
        return None


def _parse_section_hierarchy(value: object) -> tuple[tuple[int, str], ...]:
    if not isinstance(value, dict):
        return ()
    hierarchy: list[tuple[int, str]] = []
    for level, heading in value.items():
        try:
            normalized_level = int(level)
        except (TypeError, ValueError):
            continue
        if isinstance(heading, str) and heading.strip():
            hierarchy.append((normalized_level, heading.strip()))
    return tuple(sorted(hierarchy))


def _extract_page_blocks(page_data: dict) -> list[ParsedBlock]:
    """按文档顺序提取 Marker/Datalab 叶子内容块。"""

    def extract_blocks_from_node(node: object) -> list[ParsedBlock]:
        if not isinstance(node, dict):
            return []

        child_blocks = [block for child in node.get("children") or [] for block in extract_blocks_from_node(child)]
        if child_blocks:
            # Marker 风格 JSON 的父节点 HTML 通常是整个子树的渲染结果。
            # 同时抽取父子 HTML 会把段落重复写入页面文本，因此层级节点只取叶子内容。
            return child_blocks

        block_type = str(node.get("block_type") or "Unknown")
        if block_type in IGNORED_MARKER_BLOCK_TYPES:
            return []

        html = node.get("html", "")
        if not isinstance(html, str) or not html or html.startswith("<content-ref"):
            return []

        extractor = HTMLTextExtractor()
        try:
            extractor.feed(html)
            text = _repair_marker_private_glyphs(extractor.get_text())
        except Exception:
            return []
        if not text:
            return []

        return [
            ParsedBlock(
                block_type=block_type,
                text=text,
                block_id=str(node.get("id") or ""),
                bbox=_parse_bbox(node.get("bbox") or node.get("polygon")),
                section_hierarchy=_parse_section_hierarchy(node.get("section_hierarchy")),
            )
        ]

    return extract_blocks_from_node(page_data)


def _extract_page_text(page_data: dict) -> str:
    """从 Marker/Datalab JSON 的 Page 节点中提取纯文本。"""

    return "\n".join(block.text for block in _extract_page_blocks(page_data))


def _extract_pages_from_json(data: dict, max_pages: int = 0, parser: str = "marker") -> list[PageResult]:
    """
    从 Marker/Datalab JSON 结构中提取逐页内容。

    支持两种 JSON 格式：
    - 旧格式: {"pages": [...]}
    - 新格式: {"children": [...], 其中 block_type="Page" 的为页面}
    """
    all_pages = []
    if isinstance(data, dict):
        if "pages" in data:
            all_pages = data["pages"]
        elif "children" in data:
            all_pages = [c for c in data["children"] if isinstance(c, dict) and c.get("block_type") == "Page"]

    if max_pages > 0 and len(all_pages) > max_pages:
        all_pages = all_pages[:max_pages]

    pages_results = []
    for idx, page_data in enumerate(all_pages):
        page_text = ""
        blocks: list[ParsedBlock] = []
        if isinstance(page_data, dict):
            blocks = _extract_page_blocks(page_data)
            page_text = "\n".join(block.text for block in blocks)

        pages_results.append(
            PageResult(
                page_num=_marker_page_number(page_data, fallback=idx + 1),
                text=page_text,
                parser=parser,
                char_count=len(page_text),
                original_char_count=len(page_text),
                blocks=blocks,
            )
        )

    return pages_results


def _marker_page_number(page_data: object, fallback: int) -> int:
    """从 Marker 页面 ID 恢复原 PDF 页码，旧格式缺失时使用顺序页码。"""
    if not isinstance(page_data, dict):
        return fallback

    page_id = page_data.get("page_id")
    if isinstance(page_id, int) and page_id >= 0:
        return page_id + 1

    block_id = page_data.get("id")
    if isinstance(block_id, str):
        match = re.match(r"^/page/(\d+)/", block_id)
        if match:
            return int(match.group(1)) + 1
    return fallback


def _build_result(file_name: str, pages: list[PageResult], parser_mode: str) -> PDFParseResult:
    """从 PageResult 列表构建 PDFParseResult"""
    full_text_parts = []
    for p in pages:
        if p.text:
            full_text_parts.append(f"[第 {p.page_num} 页]\n{p.text}")

    return PDFParseResult(
        file_name=file_name,
        total_pages=len(pages),
        pages=pages,
        marker_pages=sum(page.parser in {"marker", "datalab"} for page in pages),
        success_rate=(sum(page.error is None for page in pages) / len(pages) if pages else 0.0),
        full_text="\n\n".join(full_text_parts),
        parser_mode=parser_mode,
    )


def parse_pdf_file(
    pdf_path: str,
    max_pages: int = 0,
    save_trace: bool = True,
    parser_mode: ParserMode = "marker",
) -> PDFParseResult:
    """
    解析 PDF 文件

    Args:
        pdf_path: PDF 文件路径
        max_pages: 最大解析页数，0 表示全部解析
        save_trace: 是否保存解析追踪记录
        parser_mode: 解析模式 - marker / auto / datalab / pypdf-plain / pypdf-layout
            marker: 使用本地 Marker（默认，避免未显式授权时上传 PDF）
            auto: 优先 Datalab 云端，失败回退本地 Marker
            datalab: 仅用 Datalab
            pypdf-plain: 按 PDF 文本流顺序提取，不执行 OCR
            pypdf-layout: 尽量保留 PDF 文本层版面，不执行 OCR
    """
    file_name = os.path.basename(pdf_path)

    print(f"\n[PDF] {file_name}: 开始解析...")

    if parser_mode in {"pypdf-plain", "pypdf-layout"}:
        extraction_mode: PyPDFExtractionMode = "plain" if parser_mode == "pypdf-plain" else "layout"
        print(f"  解析器: PyPDF ({extraction_mode})")
        success, message, pages = parse_with_pypdf(
            pdf_path,
            max_pages=max_pages,
            extraction_mode=extraction_mode,
        )
        if not success:
            print(f"  [ERROR] {message}")
            return PDFParseResult(
                file_name=file_name,
                total_pages=0,
                pages=[],
                parser_mode=parser_mode,
                error=message,
            )

        result = _build_result(file_name, pages, parser_mode)
        print(f"[PDF] {file_name}: 解析完成")
        print(f"  PyPDF: {result.total_pages} 页, 成功率 {result.success_rate:.1%}")
        if save_trace:
            save_parse_trace(result)
        return result

    # === 尝试 Datalab 云端 API ===
    if parser_mode in ("auto", "datalab"):
        try:
            import ds_course_agent.shared.config as config

            datalab_key = config.DATALAB_API_KEY
        except Exception:
            datalab_key = os.getenv("DATALAB_API_KEY", "")

        if datalab_key and datalab_key != "your_datalab_api_key_here":
            print("  解析器: Datalab 云端 (balanced)")
            success, content, data = parse_with_datalab(
                pdf_path, api_key=datalab_key, max_pages=max_pages, mode="balanced"
            )

            if success:
                pages = _extract_pages_from_json(data, max_pages, parser="datalab")
                print(f"[PDF] {file_name}: 解析完成")
                print(f"  Datalab: {len(pages)} 页")

                result = _build_result(file_name, pages, "datalab")
                if save_trace:
                    save_parse_trace(result)
                return result
            else:
                print(f"  [Datalab 失败] {content}")
                if parser_mode == "datalab":
                    return PDFParseResult(
                        file_name=file_name,
                        total_pages=0,
                        pages=[],
                        parser_mode="datalab",
                        error=content,
                    )
                print("  回退到本地 Marker...")
        elif parser_mode == "datalab":
            error = "DATALAB_API_KEY 未设置"
            print(f"  [ERROR] {error}")
            return PDFParseResult(
                file_name=file_name,
                total_pages=0,
                pages=[],
                parser_mode="datalab",
                error=error,
            )

    # === 本地 Marker 解析 ===
    print("  解析器: 本地 Marker")
    output_dir = tempfile.mkdtemp()

    try:
        success, content, data = parse_with_marker(pdf_path, output_dir=output_dir, max_pages=max_pages)

        if not success:
            print(f"  [ERROR] {content}")
            return PDFParseResult(
                file_name=file_name,
                total_pages=0,
                pages=[],
                parser_mode="marker",
                error=content,
            )

        pages_results = _extract_pages_from_json(data, max_pages, parser="marker")
        print(f"[PDF] {file_name}: 解析完成")
        print(f"  Marker: {len(pages_results)} 页")

        result = _build_result(file_name, pages_results, "marker")
        if save_trace:
            save_parse_trace(result)
        return result

    finally:
        if os.path.exists(output_dir):
            try:
                shutil.rmtree(output_dir)
            except Exception:
                pass


def save_parse_trace(parse_result: PDFParseResult, output_path: str = "var/artifacts/parse_trace.json") -> None:
    """保存解析追踪记录"""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    trace = ParseTrace(
        file_name=parse_result.file_name,
        total_pages=parse_result.total_pages,
        parser_mode=parse_result.parser_mode,
        generated_at=datetime.now().isoformat(),
        pages=[
            {
                "page_num": p.page_num,
                "parser": p.parser,
                "char_count": p.char_count,
                "block_count": len(p.blocks),
                "block_types": sorted({block.block_type for block in p.blocks}),
                "error": p.error,
            }
            for p in parse_result.pages
        ],
    )

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(asdict(trace), f, ensure_ascii=False, indent=2)

    print(f"[TRACE] 解析追踪已保存: {output_path}")


def parse_pdf_directory(directory: str) -> list[PDFParseResult]:
    """批量解析目录下所有 PDF 文件"""
    results = []
    pdf_files = list(Path(directory).glob("*.pdf"))

    if not pdf_files:
        print(f"[PDF] 目录 {directory} 下没有 PDF 文件")
        return results

    print(f"[PDF] 发现 {len(pdf_files)} 个 PDF 文件")

    for pdf_file in pdf_files:
        result = parse_pdf_file(str(pdf_file))
        results.append(result)

    return results


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        pdf_path = sys.argv[1]
        if os.path.isdir(pdf_path):
            results = parse_pdf_directory(pdf_path)
            for r in results:
                print(f"\n{r.file_name}: {r.total_pages} 页, 成功率 {r.success_rate:.1%}")
        else:
            result = parse_pdf_file(pdf_path)
            print(f"\n解析完成: {result.total_pages} 页")
    else:
        print("用法: python course_pdf_parser.py <pdf_path_or_directory>")
