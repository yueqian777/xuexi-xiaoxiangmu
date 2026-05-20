from __future__ import annotations

import pandas as pd
import streamlit as st

from db import fetch_all, insert_and_get_id
from services.prompt_service import render_template


def render() -> None:
    st.title("主线与插问")
    st.caption("插问必须绑定主线锚点，处理完后明确回到原主线。")

    sessions = fetch_all("SELECT * FROM study_sessions ORDER BY date DESC, id DESC")
    if not sessions:
        st.info("请先在“学习登记”创建学习记录，再添加主线锚点。")
        return

    session_by_id = {session["id"]: session for session in sessions}
    session_id = st.selectbox(
        "选择学习会话",
        list(session_by_id),
        format_func=lambda item_id: _session_label(session_by_id, item_id),
    )
    session = session_by_id.get(session_id)
    if not session:
        return
    anchors = fetch_all(
        "SELECT * FROM mainline_anchors WHERE session_id = ? ORDER BY order_index ASC, id ASC",
        (session_id,),
    )
    anchor_by_id = {anchor["id"]: anchor for anchor in anchors}

    tab_anchor, tab_branch, tab_context = st.tabs(["主线锚点", "插问分支", "完整脉络"])

    with tab_anchor:
        next_index = len(anchors) + 1
        with st.form("add_anchor"):
            st.subheader("添加主线锚点")
            cols = st.columns([1, 2, 1])
            anchor_code = cols[0].text_input("锚点编号", value=f"M{next_index}")
            title = cols[1].text_input("锚点标题", placeholder="例如：Z 反变换")
            order_index = cols[2].number_input("顺序", min_value=1, value=next_index, step=1)
            content = st.text_area("主线内容")
            submitted = st.form_submit_button("保存锚点")
        if submitted:
            if not anchor_code.strip() or not title.strip():
                st.error("锚点编号和标题不能为空。")
            else:
                insert_and_get_id(
                    """
                    INSERT INTO mainline_anchors (session_id, anchor_code, title, content, order_index)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (session_id, anchor_code.strip(), title.strip(), content.strip(), int(order_index)),
                )
                st.success("主线锚点已保存。")
                st.rerun()

        if anchors:
            st.dataframe(
                pd.DataFrame(anchors)[["anchor_code", "title", "content", "order_index"]],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.caption("当前学习会话暂无主线锚点。")

    with tab_branch:
        if not anchors:
            st.warning("请先添加至少一个主线锚点。")
        else:
            with st.form("add_branch"):
                st.subheader("添加绑定锚点的插问")
                anchor_id = st.selectbox(
                    "绑定主线锚点",
                    list(anchor_by_id),
                    format_func=lambda item_id: _anchor_label(anchor_by_id, item_id),
                )
                question = st.text_area("插问内容")
                answer_summary = st.text_area("ChatGPT 回答摘要")
                cols = st.columns(2)
                understood = cols[0].checkbox("我已理解", value=False)
                need_review = cols[1].checkbox("后续需要复习", value=True)
                submitted = st.form_submit_button("保存插问")
            if submitted:
                if not question.strip():
                    st.error("插问内容不能为空。")
                else:
                    insert_and_get_id(
                        """
                        INSERT INTO branch_questions (
                            session_id, anchor_id, question, answer_summary, understood, need_review
                        )
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            session_id,
                            anchor_id,
                            question.strip(),
                            answer_summary.strip(),
                            int(understood),
                            int(need_review),
                        ),
                    )
                    anchor = anchor_by_id[anchor_id]
                    st.success(f"插问已保存。现在回到主线 {anchor['anchor_code']}。")

            selected_anchor_id = st.selectbox(
                "为当前插问生成 ChatGPT Prompt",
                list(anchor_by_id),
                format_func=lambda item_id: _anchor_label(anchor_by_id, item_id),
                key="branch_prompt_anchor",
            )
            prompt_question = st.text_area("要发送给 ChatGPT 的插问", key="branch_prompt_question")
            if prompt_question.strip():
                anchor = anchor_by_id[selected_anchor_id]
                mainline = f"{session['subject']} · {session['title']}：{session['main_question']}"
                prompt = render_template(
                    "branch_question.md",
                    {
                        "mainline": mainline,
                        "anchor": f"{anchor['anchor_code']} {anchor['title']}：{anchor['content']}",
                        "question": prompt_question.strip(),
                        "anchor_code": anchor["anchor_code"],
                    },
                )
                st.code(prompt, language="markdown")

    with tab_context:
        st.subheader("完整脉络")
        branches = fetch_all(
            "SELECT * FROM branch_questions WHERE session_id = ? ORDER BY anchor_id ASC, created_at ASC, id ASC",
            (session_id,),
        )
        branches_by_anchor: dict[int, list[dict]] = {}
        for branch in branches:
            branches_by_anchor.setdefault(int(branch["anchor_id"]), []).append(branch)
        for anchor in anchors:
            st.markdown(f"### {anchor['anchor_code']}：{anchor['title']}")
            st.write(anchor["content"] or "未填写主线内容。")
            for branch in branches_by_anchor.get(int(anchor["id"]), []):
                with st.container(border=True):
                    st.markdown(f"**插问：** {branch['question']}")
                    st.markdown(f"**回答摘要：** {branch['answer_summary'] or '未填写'}")
                    st.caption(f"理解：{'是' if branch['understood'] else '否'} · 需要复习：{'是' if branch['need_review'] else '否'}")
                    st.success(f"现在回到主线 {anchor['anchor_code']}")


def _session_label(sessions: dict[int, dict], session_id: int) -> str:
    session = sessions[session_id]
    return f"{session['date']} · {session['subject']} · {session['title']}"


def _anchor_label(anchors: dict[int, dict], anchor_id: int) -> str:
    anchor = anchors[anchor_id]
    return f"{anchor['anchor_code']} · {anchor['title']}"
