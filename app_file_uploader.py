"""
基于Stremlit完成Web网页上传服务。
"""
import streamlit as st
from Knowledeg_base import KnowledgeBaseService
import time

#添加网页标题
st.title("知识库文件上传")
#添加文件上传组件
upload_file = st.file_uploader("请上传上传文件",
                                type=["txt", "pdf", "docx"], 
                                accept_multiple_files=False     #仅接受一个文件上传
                            ) 

#session_state是一个字典

if "service" not in st.session_state:
    st.session_state["service"] = KnowledgeBaseService()

if upload_file is not None:
    #提取文件信息
    file_name = upload_file.name
    file_type = upload_file.type
    file_size = upload_file.size / 1024  #转换为KB

    st.subheader(f"文件名：{file_name}")
    st.write(f"格式：{file_type} | 大小：{file_size:.2f} KB")

    #获取文件内容(get_value -> bytes -> decode('utf-8))
    text = upload_file.getvalue().decode('utf-8')

    #将文件内容上传到知识库中
    if st.button("开始上传"):
        with st.spinner("正在上传文件到知识库中..."):
            time.sleep(2)
            res = st.session_state["service"].upload_by_str(text, file_name)
        st.success(res)