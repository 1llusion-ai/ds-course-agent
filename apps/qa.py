"""
Streamlit QA 应用
基于 LangChain Agent 的课程助教系统
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import time
import streamlit as st
import utils.config as config
from core.agent import get_agent_service
from utils.history import get_history, get_all_sessions, delete_session, clear_all_sessions


st.set_page_config(
    page_title=f"{config.COURSE_NAME} - 课程助教",
    page_icon="📚",
    layout="wide",
)

st.title(f"📚 {config.COURSE_NAME} - 课程助教")
st.caption(f"课程范围：{config.COURSE_DESCRIPTION}")
st.divider()

with st.sidebar:
    st.header("💬 历史记录管理")
    
    current_session = config.session_config.get("configurable", {}).get("session_id", "user_001")
    st.text(f"当前会话: {current_session}")
    
    st.divider()
    
    if st.button("🗑️ 删除当前会话历史", type="primary"):
        history = get_history(current_session)
        if history.delete():
            st.success("✅ 当前会话历史已删除")
            st.session_state["messages"] = [
                {"role": "assistant", 
                 "content": f"您好，我是《{config.COURSE_NAME}》课程助教，有什么我可以帮您的吗？"
                }
            ]
            st.rerun()
        else:
            st.info("ℹ️ 当前会话没有历史记录")
    
    st.divider()
    
    st.subheader("📋 所有会话")
    sessions = get_all_sessions()
    if sessions:
        st.text(f"共 {len(sessions)} 个会话")
        for session_id in sessions:
            col1, col2 = st.columns([3, 1])
            with col1:
                st.text(session_id[:20] + "..." if len(session_id) > 20 else session_id)
            with col2:
                if st.button("🗑️", key=f"del_{session_id}", help=f"删除 {session_id}"):
                    if delete_session(session_id):
                        st.success(f"已删除: {session_id}")
                        st.rerun()
        
        st.divider()
        
        if st.button("⚠️ 清空所有会话", type="secondary"):
            count = clear_all_sessions()
            st.success(f"✅ 已清空 {count} 个会话")
            st.session_state["messages"] = [
                {"role": "assistant", 
                 "content": f"您好，我是《{config.COURSE_NAME}》课程的AI助教，有什么我可以帮您的吗？"
                }
            ]
            st.rerun()
    else:
        st.info("暂无历史会话")
    
    st.divider()

    # ===== 学生画像统计 =====
    st.subheader("👤 学习画像")

    try:
        from core.memory_core import get_memory_core
        memory_core = get_memory_core()
        # 尝试聚合（幂等的，有则更新，无则跳过）
        memory_core.aggregate_profile(current_session)
        profile = memory_core.get_profile(current_session)

        if profile.recent_concepts:
            st.text("最近关注：")
            for cid, cf in list(profile.recent_concepts.items())[:3]:
                st.text(f"  • {cf.display_name} ({cf.mention_count}次)")
        else:
            st.info("暂无学习数据")

        if profile.weak_spot_candidates:
            weak_spots = [w for w in profile.weak_spot_candidates if w.confidence > 0.5]
            if weak_spots:
                st.text("需要巩固：")
                for w in weak_spots[:2]:
                    st.text(f"  • {w.display_name}")

        if profile.progress.current_chapter:
            st.text(f"当前进度：{profile.progress.current_chapter}")

        # 刷新画像按钮
        if st.button("🔄 刷新画像", help="更新学习统计"):
            try:
                memory_core.aggregate_profile(current_session)
                st.success("画像已更新")
                st.rerun()
            except Exception as e:
                st.error(f"更新失败: {e}")

    except Exception as e:
        st.error(f"加载画像失败: {e}")

    st.divider()

    with st.expander("ℹ️ 使用说明"):
        st.markdown(f"""
        ### 功能介绍
        本系统是《{config.COURSE_NAME}》课程助教，可以：
        - 📖 解答课程概念问题
        - 📚 基于课程资料回答问题
        - 💡 提供学习建议
        
        ### 使用方法
        1. 在输入框中输入您的问题
        2. 系统会自动检索课程资料并回答
        3. 回答会引用课程资料来源
        
        ### 注意事项
        - 请确保问题与课程内容相关
        - 可以追问以获得更详细的解释
        """)


if "messages" not in st.session_state:
    st.session_state["messages"] = [
        {"role": "assistant", 
         "content": f"您好，我是《{config.COURSE_NAME}》课程的AI助教，有什么我可以帮您的吗？"
        }
    ]

if "agent_service" not in st.session_state:
    st.session_state["agent_service"] = get_agent_service()


for message in st.session_state["messages"]:
    with st.chat_message(message["role"]):
        st.write(message["content"])

prompt = st.chat_input("请输入您的问题：")
if prompt:
    st.chat_message("user").write(prompt)
    st.session_state["messages"].append({"role": "user", "content": prompt})

    with st.spinner("正在思考..."):
        try:
            response = st.session_state["agent_service"].chat_with_history(
                prompt,
                session_id=current_session,
                student_id=current_session
            )

            st.chat_message("assistant").write(response)
            st.session_state["messages"].append({"role": "assistant", "content": response})

        except Exception as e:
            error_msg = f"抱歉，处理您的请求时出现错误：{str(e)}"
            st.chat_message("assistant").write(error_msg)
            st.session_state["messages"].append({"role": "assistant", "content": error_msg})
