"""
Streamlit 文件上传应用
支持上传课程资料到知识库
"""
import io
import os
import time
import tempfile
import subprocess
import shutil
import json
import streamlit as st

from Knowledeg_base import KnowledgeBaseService
import config_data as config


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


def extract_text_from_pdf_with_marker(file_bytes: bytes, file_name: str, max_pages: int = 0) -> dict:
    """
    使用 Marker 解析 PDF
    
    Args:
        file_bytes: PDF 文件字节
        file_name: 文件名
        max_pages: 最大页数，0 表示全部
    
    Returns:
        dict: 解析结果
    """
    with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_input:
        tmp_input.write(file_bytes)
        tmp_input_path = tmp_input.name
    
    output_dir = tempfile.mkdtemp()
    
    try:
        cmd = ["marker_single", tmp_input_path, output_dir, "--output_format", "json"]
        
        if max_pages > 0:
            cmd.extend(["--page_range", f"1-{max_pages}"])
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600
        )
        
        if result.returncode != 0:
            return {
                "success": False,
                "file_name": file_name,
                "file_type": "pdf",
                "text": "",
                "pages": [],
                "error": f"Marker 解析失败: {result.stderr}"
            }
        
        pdf_stem = os.path.splitext(os.path.basename(file_name))[0]
        json_path = os.path.join(output_dir, f"{pdf_stem}.json")
        
        if not os.path.exists(json_path):
            return {
                "success": False,
                "file_name": file_name,
                "file_type": "pdf",
                "text": "",
                "pages": [],
                "error": "Marker 输出文件未找到"
            }
        
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        all_pages = []
        full_text_parts = []
        
        if isinstance(data, dict) and "pages" in data:
            pages_data = data["pages"]
            
            for idx, page_data in enumerate(pages_data):
                page_text = ""
                
                if isinstance(page_data, dict):
                    if "markdown" in page_data:
                        page_text = page_data["markdown"]
                    elif "text" in page_data:
                        page_text = page_data["text"]
                    elif "content" in page_data:
                        page_text = page_data["content"]
                
                if isinstance(page_text, dict):
                    page_text = json.dumps(page_text, ensure_ascii=False)
                
                all_pages.append({
                    "page_num": idx + 1,
                    "text": page_text,
                    "parser": "marker"
                })
                
                if page_text:
                    full_text_parts.append(f"[第 {idx + 1} 页]\n{page_text}")
        
        full_text = "\n\n".join(full_text_parts)
        
        print(f"\n✅ {file_name}: Marker 解析完成 ({len(all_pages)} 页)")
        
        return {
            "success": True,
            "file_name": file_name,
            "file_type": "pdf",
            "text": full_text,
            "pages": all_pages,
            "parser": "marker",
            "error": None
        }
        
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "file_name": file_name,
            "file_type": "pdf",
            "text": "",
            "pages": [],
            "error": "Marker 解析超时"
        }
    except Exception as e:
        return {
            "success": False,
            "file_name": file_name,
            "file_type": "pdf",
            "text": "",
            "pages": [],
            "error": f"Marker 解析错误: {str(e)}"
        }
    finally:
        if os.path.exists(tmp_input_path):
            os.remove(tmp_input_path)
        if os.path.exists(output_dir):
            shutil.rmtree(output_dir)


def extract_text_from_file(upload_file):
    """根据文件类型提取文本内容"""
    file_name = upload_file.name
    file_name_lower = file_name.lower()
    file_bytes = upload_file.getvalue()

    if file_name_lower.endswith('.txt'):
        try:
            text = file_bytes.decode('utf-8')
        except UnicodeDecodeError:
            text = file_bytes.decode('gbk', errors='ignore')
        
        paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
        
        return {
            "success": True,
            "file_name": file_name,
            "file_type": "txt",
            "text": text,
            "pages": None,
            "paragraphs": paragraphs,
            "parser": "txt",
            "error": None
        }
    elif file_name_lower.endswith('.pdf'):
        return extract_text_from_pdf_with_marker(file_bytes, file_name)
    elif file_name_lower.endswith('.docx'):
        return extract_text_from_docx(file_bytes, file_name)
    elif file_name_lower.endswith('.doc'):
        return {
            "success": False,
            "file_name": file_name,
            "file_type": "doc",
            "text": "",
            "pages": None,
            "paragraphs": None,
            "error": "暂不支持.doc格式，请转换为.docx或.pdf后上传"
        }
    else:
        return {
            "success": False,
            "file_name": file_name,
            "file_type": "unsupported",
            "text": "",
            "pages": None,
            "paragraphs": None,
            "error": "不支持的文件格式"
        }


def extract_text_from_docx(file_bytes, file_name):
    """从DOCX文件中提取文本"""
    try:
        from docx import Document
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
            "pages": None,
            "paragraphs": paragraphs,
            "parser": "docx",
            "error": None
        }
    except Exception as e:
        return {
            "success": False,
            "file_name": file_name,
            "file_type": "docx",
            "text": "",
            "pages": None,
            "paragraphs": [],
            "error": f"DOCX解析错误: {str(e)}"
        }


st.set_page_config(
    page_title=f"{config.COURSE_NAME} - 知识库上传",
    page_icon="📤",
)

st.title(f"📤 {config.COURSE_NAME} - 知识库上传")
st.caption(f"上传课程资料到知识库，支持 TXT、PDF、DOCX 格式")
st.divider()

with st.sidebar:
    st.header("📊 知识库状态")
    if "service" not in st.session_state:
        st.session_state["service"] = KnowledgeBaseService()
    
    info = st.session_state["service"].get_collection_info()
    st.metric("文档数量", info.get("document_count", 0))
    st.text(f"课程: {info.get('course_name', config.COURSE_NAME)}")
    
    st.divider()
    
    with st.expander("ℹ️ 上传说明"):
        st.markdown("""
        ### 支持的文件格式
        - **TXT**: 纯文本文件
        - **PDF**: PDF文档（Marker 解析）
        - **DOCX**: Word文档
        
        ### 上传流程
        1. 选择要上传的文件
        2. 填写资料来源信息（可选）
        3. 点击"开始上传"
        
        ### 注意事项
        - 重复内容会自动跳过
        - 大文件会自动分批处理
        """)

course_source = st.text_input(
    "资料来源",
    placeholder="如：第一章、课件、实验指导书等",
    help="标记资料的来源，方便后续检索时引用"
)

chapter = st.text_input(
    "章节信息",
    placeholder="如：1.1 数据科学概述",
    help="可选，标记资料所属章节"
)

upload_files = st.file_uploader(
    "请上传文件（支持TXT、PDF、DOCX）",
    type=["txt", "pdf", "docx"],
    accept_multiple_files=True
)

if upload_files:
    st.subheader(f"已选择 {len(upload_files)} 个文件")
    
    for upload_file in upload_files:
        file_name = upload_file.name
        file_type = upload_file.type
        file_size = upload_file.size / 1024
        st.write(f"• {file_name} ({file_type}, {file_size:.2f} KB)")
    
    if st.button("开始上传", type="primary"):
        with st.spinner("正在上传文件到知识库中..."):
            success_count = 0
            skip_count = 0
            error_count = 0
            error_messages = []
            
            for idx, upload_file in enumerate(upload_files):
                file_name = upload_file.name
                st.text(f"处理中 ({idx + 1}/{len(upload_files)}): {file_name}...")
                
                result = extract_text_from_file(upload_file)
                
                if not result["success"]:
                    error_count += 1
                    error_messages.append(f"{file_name}: {result['error']}")
                    continue
                
                parser_name = result.get("parser", "unknown")
                st.success(f"📄 {file_name}: {parser_name} 解析")
                
                text = result["text"]
                res = st.session_state["service"].upload_by_str(
                    text,
                    file_name,
                    course_source=course_source or None,
                    chapter=chapter or None,
                )
                
                if "成功" in res:
                    success_count += 1
                elif "已存在" in res:
                    skip_count += 1
                else:
                    error_count += 1
                    error_messages.append(f"{file_name}: {res}")
                
                time.sleep(0.1)
        
        st.success(f"上传完成！成功: {success_count}, 跳过: {skip_count}, 失败: {error_count}")
        
        if error_messages:
            st.error("错误详情：")
            for msg in error_messages:
                st.write(f"• {msg}")
        
        st.rerun()
