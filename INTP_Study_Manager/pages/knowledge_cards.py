from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from db import execute, fetch_all, fetch_one, insert_and_get_id
from services.auth_service import require_login
from services.knowledge_card_service import (
    compact_card_index_rows,
    knowledge_card_preview_markdown,
    mastery_level,
)
from services.review_service import ensure_initial_review_tasks
from services.ui_helpers import render_workbench_header

RELATION_TYPES = [
    "前置知识",
    "相似概念",
    "对比概念",
    "容易混淆",
    "公式迁移",
    "应用迁移",
    "同一主线",
    "反例关系",
    "补充说明",
]


def render() -> None:
    user = require_login()
    _install_knowledge_card_styles()
    render_workbench_header("知识沉淀工作台", "先浏览和定位已有知识，再按需要新建、编辑、复习或建立知识双链。")

    sessions = fetch_all(
        "SELECT id, date, subject, title FROM study_sessions WHERE user_id = ? ORDER BY date DESC, id DESC",
        (user.id,),
    )
    session_options = [None] + [s["id"] for s in sessions]
    cards = fetch_all("SELECT * FROM knowledge_cards WHERE user_id = ? ORDER BY created_at DESC, id DESC", (user.id,))
    mode = st.radio(
        "知识沉淀模式",
        ["浏览知识点", "新建知识点"],
        horizontal=True,
        key="knowledge_cards_mode",
        help="默认先浏览已有卡片，避免新建表单占据第一屏。",
    )

    if mode == "新建知识点":
        _render_create_form(user.id, sessions, session_options)
        st.divider()

    st.subheader("浏览知识点")
    if not cards:
        st.info("暂无知识点卡片。")
        return

    filtered = _filter_cards(cards)
    if not filtered:
        st.warning("当前筛选条件下没有知识卡片。")
        return

    _render_card_index(filtered)

    default_selected_id = int(filtered[0]["id"])
    selected_id = st.selectbox(
        "查看 / 编辑知识点",
        [int(c["id"]) for c in filtered],
        index=0,
        format_func=lambda item_id: f"#{item_id} - {next(c['topic'] for c in filtered if int(c['id']) == item_id)}",
    )

    card = fetch_one(
        "SELECT * FROM knowledge_cards WHERE id = ? AND user_id = ?",
        (selected_id or default_selected_id, user.id),
    )
    if not card:
        return

    preview_col, side_col = st.columns([1.35, 1])
    with preview_col:
        _render_card_preview(card)
    with side_col:
        _render_related_review_context(user.id, int(card["id"]), card)

    edit_left, edit_right = st.columns([1.15, 1])
    with edit_left:
        _render_edit_form(user.id, card)
    with edit_right:
        _render_recall_panel(card)

    _render_knowledge_links(user.id, card, cards)


def _render_create_form(user_id: int, sessions: list[dict], session_options: list[int | None]) -> None:
    with st.form("add_knowledge_card"):
        st.subheader("新建知识点")
        cols = st.columns(3)
        subject = cols[0].text_input("科目")
        topic = cols[1].text_input("知识点")
        mastery = cols[2].slider("掌握度", 0, 100, 60)
        core_question = st.text_area("核心问题", placeholder="这个知识点想解决什么问题？")
        one_sentence = st.text_area("一句话解释")
        logic_or_formula = st.text_area("公式 / 逻辑推导")
        application = st.text_area("典型题 / 应用场景")
        need_review = st.checkbox("创建 1-3-7-14 复习任务", value=True)
        source_session_id = st.selectbox(
            "关联学习记录（可选）",
            session_options,
            format_func=lambda item: "不关联" if item is None else _session_label(sessions, item),
        )
        submitted = st.form_submit_button("保存知识点卡片")

    if submitted:
        if not subject.strip() or not topic.strip() or not one_sentence.strip():
            st.error("科目、知识点、一句话解释不能为空。")
        else:
            knowledge_id = insert_and_get_id(
                """
                INSERT INTO knowledge_cards (
                    user_id, subject, topic, core_question, one_sentence, logic_or_formula,
                    application, mastery, need_review, source_session_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    subject.strip(),
                    topic.strip(),
                    core_question.strip(),
                    one_sentence.strip(),
                    logic_or_formula.strip(),
                    application.strip(),
                    mastery,
                    int(need_review),
                    source_session_id,
                ),
            )
            if need_review:
                ensure_initial_review_tasks(knowledge_id, date.today(), user_id=user_id)
            st.success("知识点卡片已保存，复习任务已按 1-3-7-14 生成。")


def _filter_cards(cards: list[dict]) -> list[dict]:
    subjects = sorted({item["subject"] for item in cards})
    cols = st.columns([1, 1, 1.4])
    selected_subject = cols[0].selectbox("按科目筛选", ["全部"] + subjects)
    status_options = ["全部", "薄弱", "巩固中", "基本掌握", "迁移熟练"]
    selected_status = cols[1].selectbox("按掌握状态筛选", status_options)
    keyword = cols[2].text_input("搜索知识点 / 问题 / 公式 / 应用").strip().lower()

    filtered = cards
    if selected_subject != "全部":
        filtered = [card for card in filtered if card["subject"] == selected_subject]
    if selected_status != "全部":
        filtered = [card for card in filtered if mastery_level(card.get("mastery"))["label"] == selected_status]
    if keyword:
        filtered = [
            card
            for card in filtered
            if keyword
            in "\n".join(
                [
                    str(card.get("subject") or ""),
                    str(card.get("topic") or ""),
                    str(card.get("core_question") or ""),
                    str(card.get("one_sentence") or ""),
                    str(card.get("logic_or_formula") or ""),
                    str(card.get("application") or ""),
                ]
            ).lower()
        ]
    return filtered


def _render_card_index(cards: list[dict]) -> None:
    st.markdown("**快速索引**")
    frame = pd.DataFrame(compact_card_index_rows(cards))
    st.dataframe(
        frame,
        use_container_width=True,
        hide_index=True,
        column_config={
            "id": st.column_config.NumberColumn("ID", width="small"),
            "核心问题": st.column_config.TextColumn("核心问题", width="large"),
            "掌握度": st.column_config.ProgressColumn("掌握度", min_value=0, max_value=100),
            "创建时间": st.column_config.TextColumn("创建时间", width="medium"),
        },
    )


def _render_card_preview(card: dict) -> None:
    level = mastery_level(card.get("mastery"))
    st.subheader("学习预览")
    st.caption(f"{card['subject']} · {card['created_at']} · {level['hint']}")
    with st.container(border=True):
        st.markdown(knowledge_card_preview_markdown(card))


def _render_edit_form(user_id: int, card: dict) -> None:
    selected_id = int(card["id"])
    with st.form(f"edit_knowledge_card_{selected_id}"):
        st.subheader("编辑知识点")
        edit_subject = st.text_input("科目", value=card["subject"])
        edit_topic = st.text_input("知识点", value=card["topic"])
        edit_question = st.text_area("核心问题", value=card["core_question"] or "")
        edit_one = st.text_area("一句话解释", value=card["one_sentence"] or "")
        edit_logic = st.text_area("公式 / 逻辑推导", value=card["logic_or_formula"] or "")
        edit_app = st.text_area("典型题 / 应用场景", value=card["application"] or "")
        edit_mastery = st.slider("掌握度", 0, 100, int(card["mastery"]), key=f"card_mastery_{selected_id}")
        edit_need_review = st.checkbox("需要复习", value=bool(card["need_review"]))
        update_submitted = st.form_submit_button("更新知识点")
    if update_submitted:
        execute(
            """
            UPDATE knowledge_cards
            SET subject = ?, topic = ?, core_question = ?, one_sentence = ?,
                logic_or_formula = ?, application = ?, mastery = ?, need_review = ?
            WHERE id = ? AND user_id = ?
            """,
            (
                edit_subject.strip(),
                edit_topic.strip(),
                edit_question.strip(),
                edit_one.strip(),
                edit_logic.strip(),
                edit_app.strip(),
                edit_mastery,
                int(edit_need_review),
                selected_id,
                user_id,
            ),
        )
        if edit_need_review:
            ensure_initial_review_tasks(selected_id, card["created_at"], user_id=user_id)
        st.success("知识点已更新。")
        st.rerun()


def _render_recall_panel(card: dict) -> None:
    st.subheader("闭卷回忆")
    st.markdown(f"**先不看答案，回答：**\n\n{card.get('core_question') or '这个知识点想解决什么问题？'}")
    with st.expander("展开答案与定位线索", expanded=False):
        st.markdown(f"**一句话：**\n\n{card.get('one_sentence') or '待补充'}")
        st.markdown(f"**公式 / 推导：**\n\n{card.get('logic_or_formula') or '待补充'}")
        st.markdown(f"**应用：**\n\n{card.get('application') or '待补充'}")


def _render_related_review_context(user_id: int, selected_id: int, card: dict) -> None:
    st.subheader("复习与证据")
    tasks = fetch_all(
        """
        SELECT review_date, review_stage, status, result
        FROM review_tasks
        WHERE knowledge_id = ? AND user_id = ?
        ORDER BY review_date ASC, id ASC
        """,
        (selected_id, user_id),
    )
    if tasks:
        st.dataframe(pd.DataFrame(tasks), use_container_width=True, hide_index=True)
    else:
        st.caption("暂无复习任务。勾选需要复习并保存后会自动生成。")

    st.markdown("**关联错题**")
    mistakes = fetch_all(
        """
        SELECT cause_category, original_question, summary, created_at
        FROM mistakes
        WHERE user_id = ? AND (knowledge_id = ? OR (subject = ? AND topic = ?))
        ORDER BY created_at DESC
        """,
        (user_id, selected_id, card["subject"], card["topic"]),
    )
    if mistakes:
        st.dataframe(pd.DataFrame(mistakes), use_container_width=True, hide_index=True)
    else:
        st.caption("暂无关联错题。")

    st.markdown("**关联插问**")
    branches = fetch_all(
        """
        SELECT ma.anchor_code, bq.question, bq.answer_summary, bq.understood
        FROM branch_questions bq
        JOIN mainline_anchors ma ON ma.id = bq.anchor_id
        WHERE bq.user_id = ? AND (bq.question LIKE ? OR bq.answer_summary LIKE ?)
        ORDER BY bq.created_at DESC
        """,
        (user_id, f"%{card['topic']}%", f"%{card['topic']}%"),
    )
    if branches:
        st.dataframe(pd.DataFrame(branches), use_container_width=True, hide_index=True)
    else:
        st.caption("暂无关联插问。")


def _install_knowledge_card_styles() -> None:
    st.markdown(
        """
        <style>
        .stMarkdown h3 {
            margin-top: 0.2rem;
        }
        div[data-testid="stExpander"] details {
            border-radius: 8px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _session_label(sessions: list[dict], session_id: int) -> str:
    session = next(item for item in sessions if item["id"] == session_id)
    return f"{session['date']} · {session['subject']} · {session['title']}"


def _render_knowledge_links(user_id: int, card: dict, cards: list[dict]) -> None:
    selected_id = int(card["id"])
    candidates = [item for item in cards if int(item["id"]) != selected_id]

    st.divider()
    st.subheader("知识双链 / 联系与对比")
    st.caption("把当前知识点连接到前置知识、相似概念、易混淆概念或公式迁移关系。这里不是资料收藏，而是帮助你建立 Obsidian 式的知识网络。")

    if candidates:
        candidate_by_id = {int(item["id"]): item for item in candidates}
        with st.form(f"add_knowledge_link_{selected_id}"):
            cols = st.columns([1.4, 1])
            target_id = cols[0].selectbox(
                "连接到哪个已学知识点",
                list(candidate_by_id),
                format_func=lambda item_id: _knowledge_card_label(candidate_by_id[item_id]),
                key=f"link_target_{selected_id}",
            )
            relation_type = cols[1].selectbox(
                "关系类型",
                RELATION_TYPES,
                key=f"link_type_{selected_id}",
            )
            relation_note = st.text_area(
                "为什么要连接它们",
                placeholder="例如：Z 变换 ROC 和系统稳定性都在回答“极点位置如何决定系统行为”，但一个强调序列唯一性，一个强调系统响应收敛。",
                key=f"link_note_{selected_id}",
            )
            compare_points = st.text_area(
                "联系 / 对比要点",
                placeholder="写成 2-4 条：相同点、不同点、适用条件、容易混淆的位置。",
                key=f"link_compare_{selected_id}",
            )
            submitted = st.form_submit_button("建立知识链接")

        if submitted:
            existing = fetch_one(
                """
                SELECT id
                FROM knowledge_links
                WHERE user_id = ? AND source_knowledge_id = ? AND target_knowledge_id = ? AND relation_type = ?
                """,
                (user_id, selected_id, target_id, relation_type),
            )
            if existing:
                execute(
                    """
                    UPDATE knowledge_links
                    SET relation_note = ?, compare_points = ?, created_at = datetime('now', 'localtime')
                    WHERE id = ? AND user_id = ?
                    """,
                    (relation_note.strip(), compare_points.strip(), existing["id"], user_id),
                )
                st.success("已有同类型链接，已更新说明和对比要点。")
            else:
                insert_and_get_id(
                    """
                    INSERT INTO knowledge_links (
                        user_id, source_knowledge_id, target_knowledge_id, relation_type,
                        relation_note, compare_points
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        selected_id,
                        target_id,
                        relation_type,
                        relation_note.strip(),
                        compare_points.strip(),
                    ),
                )
                st.success("知识链接已建立。")
            st.rerun()
    else:
        st.info("至少需要两张知识卡片，才能建立知识双链。")

    outgoing = _knowledge_links_for_card(user_id, selected_id, direction="outgoing")
    incoming = _knowledge_links_for_card(user_id, selected_id, direction="incoming")

    left, right = st.columns(2)
    with left:
        st.markdown("**出链：当前知识点连接到什么**")
        _render_link_list(user_id, outgoing, direction="outgoing")
    with right:
        st.markdown("**入链：哪些知识点连接到当前卡片**")
        _render_link_list(user_id, incoming, direction="incoming")


def _knowledge_links_for_card(user_id: int, card_id: int, *, direction: str) -> list[dict]:
    if direction == "outgoing":
        return fetch_all(
            """
            SELECT
                kl.id,
                kl.relation_type,
                kl.relation_note,
                kl.compare_points,
                kl.created_at,
                kc.id AS linked_id,
                kc.subject AS linked_subject,
                kc.topic AS linked_topic,
                kc.core_question AS linked_question,
                kc.mastery AS linked_mastery
            FROM knowledge_links kl
            JOIN knowledge_cards kc ON kc.id = kl.target_knowledge_id AND kc.user_id = kl.user_id
            WHERE kl.user_id = ? AND kl.source_knowledge_id = ?
            ORDER BY kl.created_at DESC, kl.id DESC
            """,
            (user_id, card_id),
        )

    return fetch_all(
        """
        SELECT
            kl.id,
            kl.relation_type,
            kl.relation_note,
            kl.compare_points,
            kl.created_at,
            kc.id AS linked_id,
            kc.subject AS linked_subject,
            kc.topic AS linked_topic,
            kc.core_question AS linked_question,
            kc.mastery AS linked_mastery
        FROM knowledge_links kl
        JOIN knowledge_cards kc ON kc.id = kl.source_knowledge_id AND kc.user_id = kl.user_id
        WHERE kl.user_id = ? AND kl.target_knowledge_id = ?
        ORDER BY kl.created_at DESC, kl.id DESC
        """,
        (user_id, card_id),
    )


def _render_link_list(user_id: int, links: list[dict], *, direction: str) -> None:
    if not links:
        st.caption("暂无知识链接。")
        return

    for link in links:
        label = _knowledge_link_display_label(link)
        with st.container(border=True):
            st.markdown(f"**{label}**")
            st.caption(f"关系类型：{link['relation_type']} · 创建时间：{link['created_at']}")
            if link.get("linked_question"):
                st.markdown(f"核心问题：{link['linked_question']}")
            if link.get("relation_note"):
                st.markdown(f"连接理由：{link['relation_note']}")
            if link.get("compare_points"):
                st.markdown(f"联系 / 对比：\n\n{link['compare_points']}")
            if st.button("删除这条链接", key=f"delete_knowledge_link_{direction}_{link['id']}"):
                execute("DELETE FROM knowledge_links WHERE id = ? AND user_id = ?", (link["id"], user_id))
                st.success("知识链接已删除。")
                st.rerun()


def _knowledge_link_display_label(link: dict) -> str:
    return (
        f"#{link['linked_id']} · {link['linked_subject']} · "
        f"{link['linked_topic']}（掌握度 {link['linked_mastery']}%）"
    )


def _knowledge_card_label(card: dict) -> str:
    return f"#{card['id']} · {card['subject']} · {card['topic']}（{card['mastery']}%）"
