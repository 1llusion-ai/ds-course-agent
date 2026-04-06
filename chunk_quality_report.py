"""
分块质量报告模块
P2 质检与验收自动化
TEST-P1: 增加质量门槛
输出：章节识别率、小节异常率、断字空格率、乱码率、重复块率
新增：chapter_nonempty、section_nonempty、section_len>40、标点空格率、页码分布
"""
import re
import json
from dataclasses import dataclass, asdict, field
from typing import Optional
from collections import Counter


@dataclass
class QualityThresholds:
    """质量门槛"""
    chapter_nonempty_min: float = 1.0
    section_nonempty_min: float = 0.9
    section_len_over_40_max: float = 0.03
    punctuation_space_rate_max: float = 0.1
    broken_space_rate_max: float = 0.5


@dataclass
class QualityMetrics:
    """质量指标"""
    total_chunks: int
    chapter_recognition_rate: float
    section_recognition_rate: float
    section_anomaly_rate: float
    broken_space_rate: float
    garbage_rate: float
    duplicate_rate: float
    avg_chunk_size: float
    size_distribution: dict[str, int]
    chapter_distribution: dict[str, int]
    page_distribution: dict[int, int]
    section_len_over_40_rate: float
    punctuation_space_rate: float
    warnings: list[str]
    passed: bool = True
    thresholds: dict[str, float] = field(default_factory=dict)


def detect_broken_spaces(text: str) -> int:
    """检测断字空格（汉字-空格-汉字模式残留）"""
    pattern = re.compile(r'[\u4e00-\u9fff]\s+[\u4e00-\u9fff]')
    matches = pattern.findall(text)
    return len(matches)


def detect_punctuation_spaces(text: str) -> int:
    """检测标点前后的多余空格"""
    patterns = [
        re.compile(r'\s+[，。！？；：、）】》」』"\']'),
        re.compile(r'[，。！？；：、（【《「『""]\s+'),
    ]
    
    count = 0
    for pattern in patterns:
        matches = pattern.findall(text)
        count += len(matches)
    
    return count


def detect_garbage(text: str) -> int:
    """检测乱码和异常字符"""
    garbage_patterns = [
        re.compile(r'[\uE000-\uF8FF]'),
        re.compile(r'[\uFFF0-\uFFFF]'),
        re.compile(r'[\U0001F000-\U0001FFFF]'),
        re.compile(r'[\U000F0000-\U000FFFFD]'),
        re.compile(r'[\U00100000-\U0010FFFD]'),
        re.compile(r'�+'),
        re.compile(r'<!--\s*image\s*-->', re.IGNORECASE),
        re.compile(r'<!--\s*table\s*-->', re.IGNORECASE),
    ]
    
    count = 0
    for pattern in garbage_patterns:
        matches = pattern.findall(text)
        count += len(matches)
    
    return count


def is_section_anomaly(section_name: str) -> bool:
    """检测小节名称是否异常"""
    if not section_name or section_name == "(未识别)":
        return False
    
    if len(section_name) > 50:
        return True
    
    if re.search(r'[。！？]', section_name):
        return True
    
    if re.search(r'^(一|二|三|四|五|六|七|八|九|十)$', section_name):
        return False
    
    if not re.search(r'\d', section_name) and not re.search(r'[一二三四五六七八九十]', section_name):
        if len(section_name) > 20:
            return True
    
    return False


def calculate_chunk_hash(content: str) -> str:
    """计算分块内容哈希"""
    import hashlib
    return hashlib.md5(content.encode('utf-8')).hexdigest()


def generate_quality_report(
    chunks: list,
    output_path: Optional[str] = None,
    thresholds: Optional[QualityThresholds] = None
) -> QualityMetrics:
    """
    生成分块质量报告
    
    Args:
        chunks: 分块列表（TextChunk 对象列表）
        output_path: 报告输出路径（可选）
        thresholds: 质量门槛（可选）
        
    Returns:
        QualityMetrics
    """
    if thresholds is None:
        thresholds = QualityThresholds()
    
    if not chunks:
        return QualityMetrics(
            total_chunks=0,
            chapter_recognition_rate=0.0,
            section_recognition_rate=0.0,
            section_anomaly_rate=0.0,
            broken_space_rate=0.0,
            garbage_rate=0.0,
            duplicate_rate=0.0,
            avg_chunk_size=0.0,
            size_distribution={},
            chapter_distribution={},
            page_distribution={},
            section_len_over_40_rate=0.0,
            punctuation_space_rate=0.0,
            warnings=["无分块数据"],
            passed=False,
            thresholds=asdict(thresholds)
        )
    
    total_chunks = len(chunks)
    
    chapters_recognized = sum(1 for c in chunks if c.metadata.chapter and c.metadata.chapter != "(未识别)")
    sections_recognized = sum(1 for c in chunks if c.metadata.section and c.metadata.section != "(未识别)")
    
    section_anomalies = sum(1 for c in chunks if is_section_anomaly(c.metadata.section))
    
    section_len_over_40 = sum(1 for c in chunks if c.metadata.section and len(c.metadata.section) > 40)
    
    total_broken_spaces = sum(detect_broken_spaces(c.content) for c in chunks)
    total_punctuation_spaces = sum(detect_punctuation_spaces(c.content) for c in chunks)
    total_garbage = sum(detect_garbage(c.content) for c in chunks)
    
    content_hashes = [calculate_chunk_hash(c.content) for c in chunks]
    unique_hashes = set(content_hashes)
    duplicates = total_chunks - len(unique_hashes)
    
    total_chars = sum(c.metadata.char_count for c in chunks)
    avg_chunk_size = total_chars / total_chunks if total_chunks > 0 else 0
    
    size_distribution = {
        "tiny (<200)": sum(1 for c in chunks if c.metadata.char_count < 200),
        "small (200-400)": sum(1 for c in chunks if 200 <= c.metadata.char_count < 400),
        "medium (400-600)": sum(1 for c in chunks if 400 <= c.metadata.char_count < 600),
        "large (600-800)": sum(1 for c in chunks if 600 <= c.metadata.char_count < 800),
        "huge (>800)": sum(1 for c in chunks if c.metadata.char_count >= 800),
    }
    
    chapter_distribution = {}
    for c in chunks:
        chapter = c.metadata.chapter or "(未识别)"
        chapter_distribution[chapter] = chapter_distribution.get(chapter, 0) + 1
    
    page_distribution = {}
    for c in chunks:
        page = c.metadata.page
        page_distribution[page] = page_distribution.get(page, 0) + 1
    
    chapter_nonempty = chapters_recognized / total_chunks if total_chunks > 0 else 0
    section_nonempty = sections_recognized / total_chunks if total_chunks > 0 else 0
    section_len_over_40_rate = section_len_over_40 / total_chunks if total_chunks > 0 else 0
    punctuation_space_rate = total_punctuation_spaces / total_chunks if total_chunks > 0 else 0
    
    warnings = []
    passed = True
    
    if chapter_nonempty < thresholds.chapter_nonempty_min:
        warnings.append(f"章节非空率不达标: {chapter_nonempty:.1%} < {thresholds.chapter_nonempty_min:.0%}")
        passed = False
    
    if section_nonempty < thresholds.section_nonempty_min:
        warnings.append(f"小节非空率不达标: {section_nonempty:.1%} < {thresholds.section_nonempty_min:.0%}")
        passed = False
    
    if section_len_over_40_rate > thresholds.section_len_over_40_max:
        warnings.append(f"小节标题过长率超标: {section_len_over_40_rate:.1%} > {thresholds.section_len_over_40_max:.0%}")
        passed = False
    
    if punctuation_space_rate > thresholds.punctuation_space_rate_max:
        warnings.append(f"标点空格率超标: {punctuation_space_rate:.2f} > {thresholds.punctuation_space_rate_max}")
        passed = False
    
    if total_broken_spaces / total_chunks > thresholds.broken_space_rate_max:
        warnings.append(f"断字空格率超标: {total_broken_spaces/total_chunks:.2f} > {thresholds.broken_space_rate_max}")
        passed = False
    
    if total_garbage > total_chunks * 0.05:
        warnings.append(f"乱码/异常标记过多: {total_garbage} 处")
    
    if duplicates > total_chunks * 0.05:
        warnings.append(f"重复分块过多: {duplicates}/{total_chunks} ({duplicates/total_chunks:.1%})")
    
    if avg_chunk_size < 200:
        warnings.append(f"平均分块过小: {avg_chunk_size:.0f} 字")
    elif avg_chunk_size > 800:
        warnings.append(f"平均分块过大: {avg_chunk_size:.0f} 字")
    
    if len(page_distribution) < 3 and total_chunks > 10:
        warnings.append(f"页码分布过于集中: 仅 {len(page_distribution)} 个不同页码")
    
    metrics = QualityMetrics(
        total_chunks=total_chunks,
        chapter_recognition_rate=chapter_nonempty,
        section_recognition_rate=section_nonempty,
        section_anomaly_rate=section_anomalies / total_chunks if total_chunks > 0 else 0,
        broken_space_rate=total_broken_spaces / total_chunks if total_chunks > 0 else 0,
        garbage_rate=total_garbage / total_chunks if total_chunks > 0 else 0,
        duplicate_rate=duplicates / total_chunks if total_chunks > 0 else 0,
        avg_chunk_size=avg_chunk_size,
        size_distribution=size_distribution,
        chapter_distribution=chapter_distribution,
        page_distribution=page_distribution,
        section_len_over_40_rate=section_len_over_40_rate,
        punctuation_space_rate=punctuation_space_rate,
        warnings=warnings,
        passed=passed,
        thresholds=asdict(thresholds)
    )
    
    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(asdict(metrics), f, ensure_ascii=False, indent=2)
    
    return metrics


def print_quality_report(metrics: QualityMetrics):
    """打印质量报告"""
    print("\n" + "=" * 60)
    print("分块质量报告")
    print("=" * 60)
    
    print(f"\n[基础统计]")
    print(f"  总分块数: {metrics.total_chunks}")
    print(f"  平均大小: {metrics.avg_chunk_size:.0f} 字")
    
    print(f"\n[识别率]")
    print(f"  章节非空率: {metrics.chapter_recognition_rate:.1%}")
    print(f"  小节非空率: {metrics.section_recognition_rate:.1%}")
    print(f"  小节异常率: {metrics.section_anomaly_rate:.1%}")
    print(f"  小节标题过长率(>40): {metrics.section_len_over_40_rate:.1%}")
    
    print(f"\n[质量问题]")
    print(f"  断字空格率: {metrics.broken_space_rate:.2f} 处/块")
    print(f"  标点空格率: {metrics.punctuation_space_rate:.2f} 处/块")
    print(f"  乱码/异常率: {metrics.garbage_rate:.2f} 处/块")
    print(f"  重复块率: {metrics.duplicate_rate:.1%}")
    
    print(f"\n[大小分布]")
    for size_range, count in metrics.size_distribution.items():
        pct = count / metrics.total_chunks * 100 if metrics.total_chunks > 0 else 0
        bar = "█" * int(pct / 5)
        print(f"  {size_range}: {count} ({pct:.0f}%) {bar}")
    
    print(f"\n[章节分布]")
    for chapter, count in sorted(metrics.chapter_distribution.items(), key=lambda x: -x[1])[:10]:
        print(f"  {chapter}: {count} 块")
    
    print(f"\n[页码分布]")
    sorted_pages = sorted(metrics.page_distribution.items())[:15]
    for page, count in sorted_pages:
        print(f"  第{page}页: {count} 块")
    if len(metrics.page_distribution) > 15:
        print(f"  ... 共 {len(metrics.page_distribution)} 个不同页码")
    
    print(f"\n[验收门槛]")
    thresholds = metrics.thresholds
    print(f"  章节非空率 >= {thresholds.get('chapter_nonempty_min', 1.0):.0%}: {'✅' if metrics.chapter_recognition_rate >= thresholds.get('chapter_nonempty_min', 1.0) else '❌'}")
    print(f"  小节非空率 >= {thresholds.get('section_nonempty_min', 0.9):.0%}: {'✅' if metrics.section_recognition_rate >= thresholds.get('section_nonempty_min', 0.9) else '❌'}")
    print(f"  标题过长率 <= {thresholds.get('section_len_over_40_max', 0.03):.0%}: {'✅' if metrics.section_len_over_40_rate <= thresholds.get('section_len_over_40_max', 0.03) else '❌'}")
    
    if metrics.warnings:
        print(f"\n[警告] ⚠️")
        for warning in metrics.warnings:
            print(f"  - {warning}")
    
    if metrics.passed:
        print(f"\n[验收结果] ✅ 通过")
    else:
        print(f"\n[验收结果] ❌ 未通过")
    
    print("\n" + "=" * 60)


if __name__ == "__main__":
    import sys
    import os
    
    if len(sys.argv) > 1:
        json_path = sys.argv[1]
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        from course_chunker import TextChunk, ChunkMetadata
        
        chunks = []
        for item in data.get("chunks", []):
            meta = item.get("metadata", {})
            chunks.append(TextChunk(
                content=item.get("content", ""),
                metadata=ChunkMetadata(
                    chunk_id=meta.get("chunk_id", ""),
                    course=meta.get("course", ""),
                    source=meta.get("source", ""),
                    chapter=meta.get("chapter", ""),
                    chapter_no=meta.get("chapter_no", 0),
                    section=meta.get("section", ""),
                    section_no=meta.get("section_no", ""),
                    page=meta.get("page", 0),
                    char_count=meta.get("char_count", 0),
                    position=meta.get("position", 0)
                )
            ))
        
        output_path = json_path.replace(".json", "_quality.json")
        metrics = generate_quality_report(chunks, output_path)
        print_quality_report(metrics)
        print(f"\n报告已保存到: {output_path}")
    else:
        print("用法: python chunk_quality_report.py <chunks_json_path>")
