"""
课程 PDF 解析模块

解析策略：
- 默认使用本地 Marker 解析（避免未显式授权时上传 PDF）
- 可显式选择 Datalab 云端 API（Marker 云端版，无需本地 GPU），并支持 auto 回退
- 支持页码范围选择
- 输出 Markdown 格式，保留结构信息
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path


class HTMLTextExtractor(HTMLParser):
    """从 HTML 中提取纯文本"""

    def __init__(self):
        super().__init__()
        self.texts = []
        self.skip = False

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.skip = True

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.skip = False

    def handle_data(self, data):
        if not self.skip:
            self.texts.append(data)

    def get_text(self):
        text = "".join(self.texts)
        # Clean up whitespace
        text = re.sub(r"\s+", " ", text).strip()
        return text


@dataclass
class PageResult:
    """单页解析结果"""

    page_num: int
    text: str
    parser: str = "marker"
    char_count: int = 0
    original_char_count: int = 0
    error: str | None = None


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

    python_dir = os.path.dirname(sys.executable)
    # Windows: Scripts/marker_single.exe; Unix: bin/marker_single
    candidates = [
        os.path.join(python_dir, "Scripts", "marker_single.exe"),
        os.path.join(python_dir, "bin", "marker_single"),
        "marker_single",
    ]
    for candidate in candidates:
        if os.path.isfile(candidate) or candidate == "marker_single":
            return candidate
    return "marker_single"


MARKER_EXE = _get_marker_executable()


def check_marker_available() -> bool:
    """检查 Marker 是否可用"""
    try:
        result = subprocess.run([MARKER_EXE, "--help"], capture_output=True, timeout=10)
        return result.returncode == 0
    except Exception:
        return False


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
    pdf_path: str, output_dir: str = None, max_pages: int = 0, page_start: int = 1
) -> tuple[bool, str, dict]:
    """
    使用 Marker 解析 PDF

    Returns:
        tuple[bool, str, dict]: (成功标志, 文本内容, 元数据)
    """
    if not os.path.exists(pdf_path):
        return False, "", {}

    if output_dir is None:
        output_dir = tempfile.mkdtemp()

    cmd = [MARKER_EXE, pdf_path, "--output_dir", output_dir, "--output_format", "json"]

    if max_pages > 0:
        # Marker 使用 0-based 索引，page_range 格式为 "0-4"
        page_start_idx = page_start - 1
        page_end_idx = page_start_idx + max_pages - 1
        cmd.extend(["--page_range", f"{page_start_idx}-{page_end_idx}"])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

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
        return False, "Marker timeout", {}
    except Exception as e:
        return False, f"Marker error: {str(e)}", {}


def _extract_page_text(page_data: dict) -> str:
    """从 Marker/Datalab JSON 的 Page 节点中提取纯文本"""

    def extract_text_from_node(node):
        texts = []
        if isinstance(node, dict):
            html = node.get("html", "")
            if html and not html.startswith("<content-ref"):
                extractor = HTMLTextExtractor()
                try:
                    extractor.feed(html)
                    text = extractor.get_text()
                    if text:
                        texts.append(text)
                except Exception:
                    pass
            for child in node.get("children") or []:
                texts.extend(extract_text_from_node(child))
        return texts

    return "\n".join(extract_text_from_node(page_data))


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
        if isinstance(page_data, dict):
            page_text = _extract_page_text(page_data)

        pages_results.append(
            PageResult(
                page_num=idx + 1,
                text=page_text,
                parser=parser,
                char_count=len(page_text),
                original_char_count=len(page_text),
            )
        )

    return pages_results


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
        marker_pages=len(pages),
        success_rate=1.0 if pages else 0.0,
        full_text="\n\n".join(full_text_parts),
        parser_mode=parser_mode,
    )


def parse_pdf_file(
    pdf_path: str, max_pages: int = 0, save_trace: bool = True, parser_mode: str = "marker"
) -> PDFParseResult:
    """
    解析 PDF 文件

    Args:
        pdf_path: PDF 文件路径
        max_pages: 最大解析页数，0 表示全部解析
        save_trace: 是否保存解析追踪记录
        parser_mode: 解析模式 - marker / auto / datalab
            marker: 使用本地 Marker（默认，避免未显式授权时上传 PDF）
            auto: 优先 Datalab 云端，失败回退本地 Marker
            datalab: 仅用 Datalab
    """
    file_name = os.path.basename(pdf_path)

    print(f"\n[PDF] {file_name}: 开始解析...")

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
                    return PDFParseResult(file_name=file_name, total_pages=0, pages=[], parser_mode="datalab")
                print("  回退到本地 Marker...")
        elif parser_mode == "datalab":
            print("  [ERROR] DATALAB_API_KEY 未设置")
            return PDFParseResult(file_name=file_name, total_pages=0, pages=[], parser_mode="datalab")

    # === 本地 Marker 解析 ===
    print("  解析器: 本地 Marker")
    output_dir = tempfile.mkdtemp()

    try:
        success, content, data = parse_with_marker(pdf_path, output_dir=output_dir, max_pages=max_pages)

        if not success:
            print(f"  [ERROR] {content}")
            return PDFParseResult(file_name=file_name, total_pages=0, pages=[], parser_mode="marker")

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


def save_parse_trace(parse_result: PDFParseResult, output_path: str = "artifacts/parse_trace.json"):
    """保存解析追踪记录"""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    trace = ParseTrace(
        file_name=parse_result.file_name,
        total_pages=parse_result.total_pages,
        parser_mode=parse_result.parser_mode,
        generated_at=datetime.now().isoformat(),
        pages=[
            {"page_num": p.page_num, "parser": p.parser, "char_count": p.char_count, "error": p.error}
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
