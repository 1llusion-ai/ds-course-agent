"""
课程 PDF 解析模块 - Marker 单一路经

解析策略：
- 统一使用 Marker 解析 PDF
- 支持页码范围选择
- 输出 Markdown 格式，保留结构信息
"""
import os
import re
import json
import tempfile
import subprocess
import shutil
from dataclasses import dataclass, asdict
from typing import Optional
from pathlib import Path
from datetime import datetime
from html.parser import HTMLParser


class HTMLTextExtractor(HTMLParser):
    """从 HTML 中提取纯文本"""
    def __init__(self):
        super().__init__()
        self.texts = []
        self.skip = False

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style'}:
            self.skip = True

    def handle_endtag(self, tag):
        if tag in {'script', 'style'}:
            self.skip = False

    def handle_data(self, data):
        if not self.skip:
            self.texts.append(data)

    def get_text(self):
        text = ''.join(self.texts)
        # Clean up whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        return text


@dataclass
class PageResult:
    """单页解析结果"""
    page_num: int
    text: str
    parser: str = "marker"
    char_count: int = 0
    original_char_count: int = 0
    error: Optional[str] = None


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


def check_marker_available() -> bool:
    """检查 Marker 是否可用"""
    try:
        result = subprocess.run(
            ["marker_single", "--help"],
            capture_output=True,
            timeout=10
        )
        return result.returncode == 0
    except Exception:
        return False


def parse_with_marker(
    pdf_path: str,
    output_dir: str = None,
    max_pages: int = 0,
    page_start: int = 1
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
    
    cmd = ["marker_single", pdf_path, "--output_dir", output_dir, "--output_format", "json"]

    if max_pages > 0:
        # Marker 使用 0-based 索引，page_range 格式为 "0-4"
        page_start_idx = page_start - 1
        page_end_idx = page_start_idx + max_pages - 1
        cmd.extend(["--page_range", f"{page_start_idx}-{page_end_idx}"])
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600
        )
        
        if result.returncode != 0:
            return False, f"Marker failed: {result.stderr}", {}
        
        # Marker outputs to a subdirectory named after the PDF file
        # Due to encoding issues on Windows, we need to find the JSON file dynamically
        json_files = []
        for root, dirs, files in os.walk(output_dir):
            for f in files:
                if f.endswith('.json') and not f.endswith('_meta.json'):
                    json_files.append(os.path.join(root, f))

        if not json_files:
            return False, f"Output JSON not found in: {output_dir}", {}

        # Use the first (and usually only) JSON file found
        json_path = json_files[0]

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        return True, json.dumps(data, ensure_ascii=False), data
        
    except subprocess.TimeoutExpired:
        return False, "Marker timeout", {}
    except Exception as e:
        return False, f"Marker error: {str(e)}", {}


def parse_pdf_file(
    pdf_path: str,
    max_pages: int = 0,
    save_trace: bool = True,
    parser_mode: str = "marker"
) -> PDFParseResult:
    """
    解析 PDF 文件
    
    Args:
        pdf_path: PDF 文件路径
        max_pages: 最大解析页数，0 表示全部解析
        save_trace: 是否保存解析追踪记录
        parser_mode: 解析模式（保留参数兼容性，仅支持 marker）
    """
    file_name = os.path.basename(pdf_path)
    
    print(f"\n[PDF] {file_name}: 开始解析...")
    print(f"  解析器: Marker")
    
    output_dir = tempfile.mkdtemp()
    
    try:
        success, content, data = parse_with_marker(
            pdf_path,
            output_dir=output_dir,
            max_pages=max_pages
        )
        
        if not success:
            print(f"  [ERROR] {content}")
            return PDFParseResult(
                file_name=file_name,
                total_pages=0,
                pages=[],
                parser_mode="marker"
            )
        
        pages_results: list[PageResult] = []

        # Handle Marker JSON structure: Document -> children (Pages)
        all_pages = []
        if isinstance(data, dict):
            if "pages" in data:
                # Old format
                all_pages = data["pages"]
            elif "children" in data:
                # New Marker format: Document -> children -> Page objects
                all_pages = [c for c in data["children"] if isinstance(c, dict) and c.get("block_type") == "Page"]

        if max_pages > 0 and len(all_pages) > max_pages:
            all_pages = all_pages[:max_pages]

        for idx, page_data in enumerate(all_pages):
            page_text = ""

            if isinstance(page_data, dict):
                # Extract text from Marker Page structure
                def extract_text_from_node(node):
                    texts = []
                    if isinstance(node, dict):
                        # Try to get HTML content
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

                        # Recurse into children
                        for child in node.get("children") or []:
                            texts.extend(extract_text_from_node(child))
                    return texts

                extracted_texts = extract_text_from_node(page_data)
                page_text = "\n".join(extracted_texts)

            pages_results.append(PageResult(
                page_num=idx + 1,
                text=page_text,
                parser="marker",
                char_count=len(page_text),
                original_char_count=len(page_text)
            ))
        
        full_text_parts = []
        for result in pages_results:
            if result.text:
                full_text_parts.append(f"[第 {result.page_num} 页]\n{result.text}")
        
        full_text = "\n\n".join(full_text_parts)
        
        print(f"[PDF] {file_name}: 解析完成")
        print(f"  Marker: {len(pages_results)} 页")
        
        result = PDFParseResult(
            file_name=file_name,
            total_pages=len(pages_results),
            pages=pages_results,
            marker_pages=len(pages_results),
            success_rate=1.0 if pages_results else 0.0,
            full_text=full_text,
            parser_mode="marker"
        )
        
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
            {
                "page_num": p.page_num,
                "parser": p.parser,
                "char_count": p.char_count,
                "error": p.error
            }
            for p in parse_result.pages
        ]
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
