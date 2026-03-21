import time
import streamlit as st
from rag import RAGService
import config_data as config


st.title("RAG Agent Demo")
st.divider()  #添加分割线


if "messages" not in st.session_state:
    st.session_state["messages"] = [
        {"role": "assistant", 
         "content": "您好，我是RAG Agent，有什么我可以帮您的吗？"
        }
    ]  #用于存储对话历史记录

if "rag_service" not in st.session_state:
    st.session_state["rag_service"] = RAGService()  #创建RAGService实例


for message in st.session_state["messages"]:
    st.chat_message(message["role"]).write(message["content"])  #显示对话历史记录

#用户输入栏
prompt = st.chat_input("请输入您的问题：")  #用户输入问题
if prompt:
    st.chat_message("user").write(prompt)  #显示用户输入的消息
    st.session_state["messages"].append({"role": "user", "content": prompt})  #将用户输入添加到对话历史记录中
    ai_res_list = []
    with st.spinner("正在思考..."):  #显示加载动画
        #yield
        res_stream = st.session_state["rag_service"].chain.stream({
            "input": prompt},
             config=config.session_config)
        
        def capture(generator, cache_list):
            for chunk in generator:
                cache_list.append(chunk)
                yield chunk
        
        st.chat_message("assistant").write_stream(capture(res_stream, ai_res_list))  #显示AI回答的流式输出

        st.session_state["messages"].append({"role": "assistant", "content": "".join(ai_res_list)})