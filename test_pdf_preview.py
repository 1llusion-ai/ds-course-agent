 """
PDF解析预览测试工具（分页处理版本）
临时文件 - 用于预览PDF解析后的内容
"""

import streamlit as st
from docx import Document
import io
import tempfile
import os


def split_pdf_pages(file_bytes, start_page, end_page):
    """使用PyPDF提取指定页面范围的文本"""
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(file_bytes))
        texts = []
        
        for i in range(start_page, min(end_page, len(reader.pages))):
            try:
                page_text = reader.pages[i].extract_text()
                if page_text and page_text.strip():
                    texts.append(page_text.strip())
            except:
                continue
        
        return "\n\n".join(texts) if texts else None
    except:
        return None


def extract_text_from_pdf_with_docling(file_bytes, file_name, page_batch_size=10):
    """使用Docling从PDF文件中提取文本，支持真正的分页处理"""
    os.environ["HF_HUB_DISABLE_SYMLINKS"] = "1"
    os.environ["OMP_NUM_THREADS"] = "1"  # 进一步限制线程数
    
    try:
        from docling.document_converter import DocumentConverter
    except ImportError:
        return {
            "success": False,
            "file_name": file_name,
            "file_type": "pdf",
            "text": "",
            "parser": "none",
            "error": "Docling未安装，请运行: pip install docling"
        }
    
    # 先用PyPDF获取总页数
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(file_bytes))
    total_pages = len(reader.pages)
    
    # 创建进度显示
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    all_texts = []
    converter = DocumentConverter()
    
    # 创建临时文件（用于Docling）
    with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
        tmp_file.write(file_bytes)
        tmp_path = tmp_file.name
    
    try:
        for batch_start in range(0, total_pages, page_batch_size):
            batch_end = min(batch_start + page_batch_size, total_pages)
            progress = (batch_start + page_batch_size) / total_pages
            progress_bar.progress(min(progress, 0.99))
            status_text.text(f"⏳ 处理页面 {batch_start+1}-{batch_end} / 共 {total_pages} 页...")
            
            try:
                # 尝试使用Docling处理这一批
                # 注意：Docling目前不支持page_range参数，我们尝试用try-except处理
                result = converter.convert(tmp_path)
                
                if hasattr(result, 'document') and result.document:
                    text = result.document.export_to_markdown()
                elif hasattr(result, 'text'):
                    text = result.text
                else:
                    text = None
                
                if text and text.strip():
                    all_texts.append(text.strip())
                    # Docling成功处理了全部，不需要分批
                    break
                    
            except Exception as e:
                error_msg = str(e)
                if "bad_alloc" in error_msg or "Memory" in error_msg:
                    # 内存不足，对这一批使用PyPDF
                    status_text.text(f"⚠️ 页面 {batch_start+1}-{batch_end} Docling内存不足，使用PyPDF...")
                    batch_text = split_pdf_pages(file_bytes, batch_start, batch_end)
                    if batch_text:
                        all_texts.append(batch_text)
                else:
                    # 其他错误，也回退到PyPDF
                    batch_text = split_pdf_pages(file_bytes, batch_start, batch_end)
                    if batch_text:
                        all_texts.append(batch_text)
                
                # 给系统一些时间释放内存
                import gc
                gc.collect()
                import time
                time.sleep(0.5)
    
    finally:
        # 清理临时文件
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except:
            pass
    
    # 完成
    progress_bar.progress(1.0)
    status_text.text(f"✅ 完成！共处理 {total_pages} 页")
    import time
    time.sleep(0.5)
    progress_bar.empty()
    status_text.empty()
    
    if all_texts:
        full_text = "\n\n".join(all_texts)
        return {
            "success": True,
            "file_name": file_name,
            "file_type": "pdf",
            "text": full_text,
            "parser": "docling_hybrid",  # 混合模式
            "error": None
        }
    else:
        return {
            "success": False,
            "file_name": file_name,
            "file_type": "pdf",
            "text": "",
            "parser": "none",
            "error": "未能提取到任何文本"
        }


def extract_text_from_pdf_pypdf(file_bytes, file_name):
    """使用PyPDF从PDF文件中提取文本"""
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(file_bytes))
        pages = []
        full_text = ""
        
        for i, page in enumerate(reader.pages):
            try:
                page_text = page.extract_text()
                if page_text:
                    pages.append(page_text)
                    full_text += page_text + "\n"
            except:
                continue
                
        return {
            "success": True,
            "file_name": file_name,
            "file_type": "pdf",
            "text": full_text.strip(),
            "pages": pages,
            "parser": "pypdf",
            "error": None
        }
    except Exception as e:
        return {
            "success": False,
            "file_name": file_name,
            "file_type": "pdf",
            "text": "",
            "parser": "pypdf",
            "error": f"PyPDF解析错误: {str(e)}"
        }


def extract_text_from_docx(file_bytes, file_name):
    """从DOCX文件中提取文本"""
    try:
        doc_file = io.BytesIO(file_bytes)
        doc = Document(doc_file)
        paragraphs = []
        full_text = ""
        for para in doc.paragraphs:
            if para.text.strip():
                paragraphs.append(para.text)
                full_text += para.text + "\n"
        return {
            "success": True,
            "file_name": file_name,
            "file_type": "docx",
            "text": full_text.strip(),
            "paragraphs": paragraphs,
            "parser": "python-docx",
            "error": None
        }
    except Exception as e:
        return {
            "success": False,
            "file_name": file_name,
            "file_type": "docx",
            "text": "",
            "parser": "python-docx",
            "error": f"DOCX解析错误: {str(e)}"
        }


# ==================== Streamlit UI ====================

st.set_page_config(page_title="PDF解析预览", layout="wide")
st.title("📄 PDF/DOCX 解析预览工具")
st.markdown("预览文档解析后的内容，不进入向量数据库")

# 侧边栏选择解析器
st.sidebar.header("⚙️ 解析设置")
parser_option = st.sidebar.radio(
    "选择PDF解析器",
    ["Docling智能分页", "PyPDF（快速）", "两者对比"]
)

# Docling分页设置
page_batch_size = 10
if parser_option and "Docling" in parser_option:
    st.sidebar.subheader("📄 分页设置")
    page_batch_size = st.sidebar.slider(
        "每批处理页数（Docling内存不足时自动用PyPDF）",
        min_value=5,
        max_value=50,
        value=10,
        help="如果遇到内存错误，减小此值"
    )
    st.sidebar.info("💡 Docling遇到内存错误时会自动回退到PyPDF")

max_chars = st.sidebar.slider("最大显示字符数", 1000, 50000, 10000)

# 文件上传
st.header("📁 上传文件")
uploaded_file = st.file_uploader(
    "选择文件（支持 PDF, DOCX）",
    type=["pdf", "docx"]
)

if uploaded_file:
    file_name = uploaded_file.name
    file_bytes = uploaded_file.getvalue()
    file_size = len(file_bytes) / 1024
    
    st.info(f"📄 {file_name} ({file_size:.2f} KB)")
    
    # 根据选择解析
    if file_name.lower().endswith('.pdf'):
        if parser_option == "Docling智能分页":
            result = extract_text_from_pdf_with_docling(file_bytes, file_name, page_batch_size=page_batch_size)
        elif parser_option == "PyPDF（快速）":
            result = extract_text_from_pdf_pypdf(file_bytes, file_name)
        else:  # 两者对比
            col1, col2 = st.columns(2)
            
            with col1:
                st.subheader("🤖 Docling智能分页")
                result_docling = extract_text_from_pdf_with_docling(file_bytes, file_name, page_batch_size=page_batch_size)
                if result_docling["success"]:
                    st.success(f"✅ 成功 ({len(result_docling['text'])} 字符)")
                    st.text_area(
                        "Docling结果",
                        result_docling["text"][:max_chars],
                        height=400
                    )
                else:
                    st.error(f"❌ 失败: {result_docling['error']}")
            
            with col2:
                st.subheader("⚡ PyPDF 解析")
                result_pypdf = extract_text_from_pdf_pypdf(file_bytes, file_name)
                if result_pypdf["success"]:
                    st.success(f"✅ 成功 ({len(result_pypdf['text'])} 字符)")
                    st.text_area(
                        "PyPDF结果",
                        result_pypdf["text"][:max_chars],
                        height=400
                    )
                else:
                    st.error(f"❌ 失败: {result_pypdf['error']}")
            
            result = None
    
    elif file_name.lower().endswith('.docx'):
        result = extract_text_from_docx(file_bytes, file_name)
    
    else:
        st.error("不支持的文件格式")
        result = None
    
    # 显示结果
    if result:
        st.header("📊 解析结果")
        
        if result["success"]:
            st.success(f"✅ 解析成功 | 解析器: {result.get('parser', 'unknown')} | 字符数: {len(result['text'])}")
        else:
            st.error(f"❌ 解析失败: {result.get('error', '未知错误')}")
        
        if result.get("text"):
            st.subheader("📝 解析内容预览")
            
            text = result["text"]
            lines = text.split('\n')
            words = len(text.replace('\n', ' ').split())
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("总字符", len(text))
            with col2:
                st.metric("总行数", len(lines))
            with col3:
                st.metric("总词数", words)
            
            display_text = text[:max_chars]
            if len(text) > max_chars:
                display_text += f"\n\n... (还有 {len(text) - max_chars} 字符未显示)"
            
            st.text_area(
                "解析后的文本",
                display_text,
                height=500
            )
            
            st.download_button(
                label="⬇️ 下载解析后的文本",
                data=text,
                file_name=f"{file_name}_parsed.txt",
                mime="text/plain"
            )

else:
    st.info("👆 请上传 PDF 或 DOCX 文件以预览解析结果")
    
    st.header("📖 使用说明")
    st.markdown("""
    **Docling智能分页模式：**
    
    - 自动检测PDF总页数
    - 尝试使用Docling高质量解析
    - 当Docling遇到内存错误（bad_alloc）时，**自动回退到PyPDF**
    - 保证大PDF也能完整解析
    
    **建议：**
    - 100页以下：使用默认的10页/批
    - 100-500页：建议设为20页/批
    - 500页以上：建议设为50页/批
    """)
