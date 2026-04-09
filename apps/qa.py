"""
Streamlit QA 应用 - 现代化课程助教界面
基于 LangChain Agent 的课程助教系统
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import utils.config as config
from core.agent import get_agent_service
from utils.history import get_history, get_all_sessions, delete_session, clear_all_sessions


# ==================== 自定义CSS样式 ====================
def load_css():
    """加载自定义CSS样式"""
    st.markdown("""
    <style>
    /* 全局配色变量 */
    :root {
        --primary-blue: #1e3a5f;
        --accent-orange: #ff6b35;
        --success-green: #22c55e;
        --warning-yellow: #f59e0b;
        --danger-red: #ef4444;
        --bg-light: #f8fafc;
        --card-bg: #ffffff;
        --text-primary: #1e293b;
        --text-secondary: #64748b;
        --border-color: #e2e8f0;
    }

    /* 主标题样式 - 渐变背景 */
    .main-header {
        background: linear-gradient(135deg, #1e3a5f 0%, #2d5a87 100%);
        padding: 1.5rem 2rem;
        border-radius: 16px;
        margin-bottom: 1.5rem;
        box-shadow: 0 4px 20px rgba(30, 58, 95, 0.15);
    }

    .main-header h1 {
        color: white !important;
        margin: 0 !important;
        font-size: 1.6rem !important;
        font-weight: 700 !important;
    }

    .main-header p {
        color: rgba(255,255,255,0.85) !important;
        margin: 0.5rem 0 0 0 !important;
        font-size: 0.9rem !important;
    }

    /* 侧边栏样式 */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #f8fafc 0%, #f1f5f9 100%);
    }

    [data-testid="stSidebar"] .block-container {
        padding: 1.5rem 1rem;
    }

    /* 画像卡片 */
    .profile-card {
        background: white;
        border-radius: 12px;
        padding: 1rem;
        margin-bottom: 0.75rem;
        box-shadow: 0 2px 8px rgba(0,0,0,0.04);
        border-left: 4px solid #1e3a5f;
    }

    .profile-card.weakness {
        border-left-color: #ff6b35;
    }

    .profile-card.progress {
        border-left-color: #22c55e;
    }

    .card-title {
        font-size: 0.75rem;
        font-weight: 600;
        color: #64748b;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        margin-bottom: 0.5rem;
    }

    /* 概念标签云 */
    .concept-tag {
        display: inline-block;
        background: linear-gradient(135deg, #dbeafe 0%, #bfdbfe 100%);
        color: #1e40af;
        padding: 0.3rem 0.7rem;
        border-radius: 16px;
        font-size: 0.8rem;
        font-weight: 500;
        margin: 0.15rem;
        border: 1px solid #93c5fd;
    }

    .concept-tag.hot {
        background: linear-gradient(135deg, #ffedd5 0%, #fed7aa 100%);
        color: #c2410c;
        border-color: #fdba74;
        font-size: 0.85rem;
        padding: 0.35rem 0.8rem;
    }

    /* 薄弱点警示 */
    .weakness-item {
        background: #fff7ed;
        border: 1px solid #fed7aa;
        border-radius: 8px;
        padding: 0.5rem 0.75rem;
        margin: 0.3rem 0;
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }

    .weakness-item.high {
        background: #fef2f2;
        border-color: #fecaca;
    }

    /* 进度条 */
    .progress-container {
        margin-top: 0.5rem;
    }

    .progress-bar {
        height: 6px;
        background: #e2e8f0;
        border-radius: 3px;
        overflow: hidden;
    }

    .progress-fill {
        height: 100%;
        background: linear-gradient(90deg, #22c55e 0%, #4ade80 100%);
        border-radius: 3px;
        transition: width 0.5s ease;
    }

    /* 快速提问胶囊 */
    .quick-q-btn {
        background: white;
        border: 1px solid #cbd5e1;
        border-radius: 20px;
        padding: 0.4rem 1rem;
        font-size: 0.85rem;
        color: #334155;
        cursor: pointer;
        transition: all 0.2s;
    }

    .quick-q-btn:hover {
        background: #1e3a5f;
        color: white;
        border-color: #1e3a5f;
    }

    /* 消息气泡样式 */
    .stChatMessage {
        padding: 0.5rem 0;
    }

    /* 用户消息 - 右侧蓝色 */
    .stChatMessage[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) {
        flex-direction: row-reverse;
    }

    .stChatMessage [data-testid="chatAvatarIcon-user"] {
        background: #1e3a5f !important;
    }

    /* 助手消息 */
    .stChatMessage [data-testid="chatAvatarIcon-assistant"] {
        background: linear-gradient(135deg, #ff6b35 0%, #f97316 100%) !important;
    }

    /* 来源标注样式 */
    .source-citation {
        display: inline-flex;
        align-items: center;
        gap: 0.25rem;
        background: #f1f5f9;
        padding: 0.2rem 0.5rem;
        border-radius: 4px;
        font-size: 0.7rem;
        color: #64748b;
        margin-right: 0.3rem;
    }

    /* 统计数字 */
    .stat-number {
        font-size: 1.3rem;
        font-weight: 700;
        color: #1e3a5f;
    }

    .stat-label {
        font-size: 0.7rem;
        color: #64748b;
    }

    /* 隐藏默认元素 */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    </style>
    """, unsafe_allow_html=True)


# ==================== 组件渲染函数 ====================
def render_header():
    """渲染页面头部"""
    st.markdown(f"""
    <div class="main-header">
        <h1>📚 {config.COURSE_NAME}</h1>
        <p>🎓 智能课程助教 · {config.COURSE_DESCRIPTION}</p>
    </div>
    """, unsafe_allow_html=True)


def render_concept_tags(concepts: dict, max_display: int = 5):
    """渲染概念标签云"""
    if not concepts:
        return "<p style='color: #94a3b8; font-size: 0.8rem;'>💡 开始提问建立画像</p>"

    # 按提及次数排序（确保转为int比较）
    sorted_concepts = sorted(
        concepts.items(),
        key=lambda x: int(getattr(x[1], 'mention_count', 0) or 0),
        reverse=True
    )[:max_display]

    tags_html = ""
    for cid, cf in sorted_concepts:
        # 确保 mention_count 是整数
        mention_count = int(getattr(cf, 'mention_count', 0) or 0)
        is_hot = mention_count >= 3
        hot_class = "hot" if is_hot else ""
        tags_html += f'<span class="concept-tag {hot_class}">{cf.display_name}</span>'

    return tags_html


def render_weakness_list(weak_spots: list, max_display: int = 3):
    """渲染薄弱点列表"""
    if not weak_spots:
        return "<p style='color: #22c55e; font-size: 0.8rem;'>✨ 暂无薄弱点，继续保持！</p>"

    significant = [w for w in weak_spots if float(getattr(w, 'confidence', 0) or 0) > 0.3][:max_display]

    if not significant:
        return "<p style='color: #22c55e; font-size: 0.8rem;'>✨ 暂无显著薄弱点</p>"

    items_html = ""
    for w in significant:
        conf = float(getattr(w, 'confidence', 0) or 0)
        is_high = conf > 0.7
        high_class = "high" if is_high else ""
        icon = "🔴" if is_high else "🟡"
        conf_pct = int(conf * 100)

        items_html += f"""
        <div class="weakness-item {high_class}">
            <span>{icon}</span>
            <span style="flex:1; font-size: 0.8rem; color: {'#991b1b' if is_high else '#9a3412'};">
                {w.display_name}
            </span>
            <span style="font-size: 0.7rem; padding: 0.1rem 0.4rem; border-radius: 10px;
                        background: {'#fee2e2' if is_high else '#ffedd5'};
                        color: {'#991b1b' if is_high else '#c2410c'};">
                {conf_pct}%
            </span>
        </div>
        """
    return items_html


def render_profile_section(current_session: str):
    """渲染学习画像区域"""
    try:
        from core.memory_core import get_memory_core
        import traceback

        # 使用全局单例，确保和 Agent 使用同一个 MemoryCore
        memory_core = get_memory_core()
        memory_core.aggregate_profile(current_session)
        profile = memory_core.get_profile(current_session)

        # 最近关注概念
        st.markdown(f"""
        <div class="profile-card">
            <div class="card-title">🔥 最近关注</div>
            {render_concept_tags(profile.recent_concepts)}
        </div>
        """, unsafe_allow_html=True)

        # 薄弱点
        weakness_html = render_weakness_list(profile.weak_spot_candidates)
        st.markdown(f"""
        <div class="profile-card weakness">
            <div class="card-title">⚠️ 需要巩固</div>
            {weakness_html}
        </div>
        """, unsafe_allow_html=True)

        # 计算每章互动次数
        chapter_counts = {}
        for cf in profile.recent_concepts.values():
            ch = cf.chapter or "未分类"
            chapter_counts[ch] = chapter_counts.get(ch, 0) + int(getattr(cf, 'mention_count', 0) or 0)

        # 按互动次数排序
        sorted_chapters = sorted(chapter_counts.items(), key=lambda x: x[1], reverse=True)

        # 学习进度 - 显示每章互动次数
        current_chapter = profile.progress.current_chapter or "刚开始学习"
        total_mentions = sum(chapter_counts.values())

        # 学习进度 - 使用卡片样式
        chapter_lines = ""
        for ch, count in sorted_chapters[:3]:
            is_current = "📍" if ch == current_chapter else ""
            chapter_lines += f'<div style="display: flex; justify-content: space-between; padding: 0.2rem 0; font-size: 0.85rem;"><span>{is_current}&nbsp;&nbsp;{ch}</span><span style="color: #64748b; font-weight: 500;">{count} 次</span></div>'

        progress_html = f'<div class="profile-card progress"><div class="card-title">📊 学习进度</div>{chapter_lines}<div style="display: flex; justify-content: space-between; margin-top: 0.5rem; padding-top: 0.5rem; border-top: 1px solid #e2e8f0;"><span style="font-weight: 600; font-size: 0.85rem;">总计</span><span style="font-size: 0.85rem; color: #64748b; font-weight: 600;">{total_mentions} 次互动</span></div></div>'
        st.markdown(progress_html, unsafe_allow_html=True)

        # 刷新按钮
        if st.button("🔄 刷新画像", key="refresh_profile", use_container_width=True):
            memory_core.aggregate_profile(current_session)
            st.success("✅ 已更新")
            st.rerun()

    except Exception as e:
        import traceback
        st.error(f"加载画像失败: {e}")
        with st.expander("🔍 调试信息"):
            st.code(traceback.format_exc())


def render_sidebar(current_session: str):
    """渲染侧边栏"""
    with st.sidebar:
        # Logo区域
        st.markdown("""
        <div style="text-align: center; margin-bottom: 1.5rem; padding: 1rem;
                    background: white; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.04);">
            <div style="font-size: 2.5rem; margin-bottom: 0.3rem;">🎓</div>
            <div style="font-weight: 700; color: #1e3a5f; font-size: 1rem;">
                个人学习中心
            </div>
            <div style="font-size: 0.75rem; color: #64748b; margin-top: 0.2rem;">
                AI驱动的学习追踪
            </div>
        </div>
        """, unsafe_allow_html=True)

        # 学习画像
        render_profile_section(current_session)

        st.divider()

        # 会话管理（折叠）
        with st.expander("📋 历史会话", expanded=False):
            sessions = get_all_sessions()
            if sessions:
                st.caption(f"共 {len(sessions)} 个会话")

                for session_id in sessions[:5]:
                    col1, col2 = st.columns([4, 1])
                    display_id = session_id[:12] + "..." if len(session_id) > 12 else session_id
                    with col1:
                        st.text(display_id)
                    with col2:
                        if st.button("🗑️", key=f"del_{session_id}"):
                            delete_session(session_id)
                            st.rerun()

                if len(sessions) > 5:
                    st.caption(f"...还有 {len(sessions) - 5} 个")

                if st.button("⚠️ 清空所有", type="secondary", use_container_width=True):
                    clear_all_sessions()
                    st.session_state["messages"] = []
                    st.success("已清空")
                    st.rerun()
            else:
                st.info("暂无历史会话")

        # 使用帮助
        with st.expander("❓ 使用帮助"):
            st.markdown(f"""
            **功能介绍**
            - 📖 解答课程概念问题
            - 📚 基于教材资料回答
            - 💡 追踪学习进度和薄弱点

            **使用提示**
            1. 输入问题或点击快速提问
            2. 系统会自动检索课程资料
            3. 多次询问同一概念会被记录
            """)


def render_quick_questions():
    """渲染快速提问按钮"""
    questions = [
        "什么是SVM？",
        "解释一下过拟合",
        "梯度下降原理",
        "逻辑回归与线性回归区别",
    ]

    st.markdown("<p style='color: #64748b; font-size: 0.85rem; margin-bottom: 0.5rem;'>💡 快速提问</p>", unsafe_allow_html=True)

    # 使用两列布局
    for i in range(0, len(questions), 2):
        cols = st.columns(2)
        for j, col in enumerate(cols):
            idx = i + j
            if idx < len(questions):
                with col:
                    if st.button(questions[idx], key=f"quick_{idx}", use_container_width=True, type="secondary"):
                        # 设置待处理问题并触发
                        st.session_state["pending_input"] = questions[idx]
                        st.rerun()


# ==================== 主程序 ====================
def main():
    """主应用入口"""
    # 页面配置
    st.set_page_config(
        page_title=f"{config.COURSE_NAME} - 智能助教",
        page_icon="🎓",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # 加载CSS
    load_css()

    # 获取当前会话ID
    current_session = config.session_config.get("configurable", {}).get("session_id", "user_001")

    # 初始化状态
    if "messages" not in st.session_state:
        st.session_state["messages"] = [
            {
                "role": "assistant",
                "content": f"""您好！我是《{config.COURSE_NAME}》的智能课程助教 🤖

我可以帮您：
• 📖 理解课程概念和知识点
• 🔍 检索教材内容并标注来源
• 📊 追踪您的学习进度和薄弱点

请直接输入问题，或点击下方快速提问按钮开始！"""
            }
        ]

    if "agent_service" not in st.session_state:
        with st.spinner("正在初始化..."):
            st.session_state["agent_service"] = get_agent_service()

    # 处理待处理的输入（来自快速提问）
    pending_input = st.session_state.pop("pending_input", None)

    # 渲染侧边栏
    render_sidebar(current_session)

    # 渲染主区域
    render_header()

    # 快速提问区域
    render_quick_questions()

    st.divider()

    # 聊天区域
    # 显示历史消息
    for msg in st.session_state["messages"]:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])

    # 处理待处理的输入
    if pending_input:
        # 添加用户消息
        st.session_state["messages"].append({"role": "user", "content": pending_input})

        # 显示用户消息
        with st.chat_message("user"):
            st.write(pending_input)

        # 显示思考中
        with st.chat_message("assistant"):
            with st.spinner("🤔 正在思考..."):
                try:
                    response = st.session_state["agent_service"].chat_with_history(
                        pending_input,
                        session_id=current_session,
                        student_id=current_session
                    )
                    st.write(response)
                    st.session_state["messages"].append({"role": "assistant", "content": response})
                except Exception as e:
                    error_msg = str(e)
                    st.session_state["last_error"] = error_msg
                    st.session_state["last_error_time"] = __import__('time').time()

                    # 显示友好的错误提示
                    st.error("⚠️ **生成回复失败**")
                    st.markdown(f"""
                    错误信息：{error_msg[:100]}

                    可能原因：
                    - AI 服务暂时不可用
                    - 网络连接超时
                    - 课程资料检索失败
                    """)

                    # 重试按钮
                    if st.button("🔄 重试", key="retry_error", type="primary"):
                        st.session_state["pending_input"] = pending_input
                        st.rerun()

                    st.session_state["messages"].append({
                        "role": "assistant",
                        "content": f"⚠️ 生成回复失败，请重试。"
                    })

        st.rerun()

    # 输入框
    prompt = st.chat_input("💭 请输入您的问题...")

    if prompt:
        # 添加用户消息
        st.session_state["messages"].append({"role": "user", "content": prompt})

        # 显示用户消息
        with st.chat_message("user"):
            st.write(prompt)

        # 获取回复
        with st.chat_message("assistant"):
            with st.spinner("🤔 正在思考..."):
                try:
                    response = st.session_state["agent_service"].chat_with_history(
                        prompt,
                        session_id=current_session,
                        student_id=current_session
                    )
                    st.write(response)
                    st.session_state["messages"].append({"role": "assistant", "content": response})
                except Exception as e:
                    error_msg = str(e)
                    st.session_state["last_error"] = error_msg
                    st.session_state["last_error_time"] = __import__('time').time()

                    # 显示友好的错误提示
                    st.error("⚠️ **生成回复失败**")
                    st.markdown(f"""
                    错误信息：{error_msg[:100]}

                    可能原因：
                    - AI 服务暂时不可用
                    - 网络连接超时
                    - 课程资料检索失败
                    """)

                    # 重试按钮
                    if st.button("🔄 重试", key=f"retry_{len(st.session_state['messages'])}", type="primary"):
                        st.session_state["pending_input"] = prompt
                        st.rerun()

                    st.session_state["messages"].append({
                        "role": "assistant",
                        "content": f"⚠️ 生成回复失败，请重试。"
                    })

        st.rerun()

    # 清空按钮
    col1, col2 = st.columns([8, 1])
    with col2:
        if st.button("🗑️ 清空对话", key="clear_chat", help="清空当前对话"):
            st.session_state["messages"] = [
                {
                    "role": "assistant",
                    "content": f"对话已清空。我是《{config.COURSE_NAME}》的课程助教，有什么可以帮您的吗？"
                }
            ]
            st.rerun()


if __name__ == "__main__":
    main()
