from __future__ import annotations

import pandas as pd
import streamlit as st

from db import execute, execute_many, fetch_all
from services.auth_service import require_login

DECK_STATUSES = ["使用中", "归档", "暂停", "待整理"]
QUESTION_STATUSES = ["未整理", "待追问", "已解决", "待复习", "归档"]
QUESTION_CATEGORIES = ["概念卡点", "公式推导", "应用题", "反例", "错因分析", "扩展问题", "其他"]


def render() -> None:
    user = require_login()
    st.title("PPT 与插问管理")
    st.caption("用于管理 PPT/PDF 资料和侧边插问：分类、排序、状态标记、删除。")

    tab_decks, tab_questions = st.tabs(["PPT / PDF 资料", "插问记录"])
    with tab_decks:
        _render_deck_management(user.id)
    with tab_questions:
        _render_question_management(user.id)


def _render_deck_management(user_id: int) -> None:
    st.subheader("PPT / PDF 资料管理")
    decks = _fetch_decks(user_id)
    if not decks:
        st.info("暂无 PPT/PDF 资料。")
        return

    categories = sorted({deck.get("category") for deck in decks if deck.get("category")})
    cols = st.columns([1, 1, 1.5])
    status_filter = cols[0].multiselect(
        "状态筛选",
        DECK_STATUSES,
        default=DECK_STATUSES,
        key="deck_manage_status_filter",
    )
    category_filter = cols[1].multiselect(
        "分类筛选",
        categories,
        default=categories,
        key="deck_manage_category_filter",
    )
    keyword = cols[2].text_input("搜索标题 / 科目 / 文件名", key="deck_manage_keyword")

    visible = [
        deck
        for deck in decks
        if deck["status"] in status_filter
        and (not categories or deck.get("category", "") in category_filter or not deck.get("category"))
        and _matches_deck_keyword(deck, keyword)
    ]
    if not visible:
        st.warning("没有符合筛选条件的资料。")
        return

    frame = pd.DataFrame(visible)[
        [
            "id",
            "sort_order",
            "status",
            "category",
            "subject",
            "title",
            "filename",
            "slide_count",
            "question_count",
            "created_at",
        ]
    ]
    edited = st.data_editor(
        frame,
        use_container_width=True,
        hide_index=True,
        column_config={
            "id": st.column_config.NumberColumn("ID", disabled=True),
            "sort_order": st.column_config.NumberColumn("排序", step=1),
            "status": st.column_config.SelectboxColumn("状态", options=DECK_STATUSES),
            "category": st.column_config.TextColumn("分类"),
            "subject": st.column_config.TextColumn("科目"),
            "title": st.column_config.TextColumn("标题"),
            "filename": st.column_config.TextColumn("文件名", disabled=True),
            "slide_count": st.column_config.NumberColumn("页数", disabled=True),
            "question_count": st.column_config.NumberColumn("插问数", disabled=True),
            "created_at": st.column_config.TextColumn("创建时间", disabled=True),
        },
        key="ppt_deck_management_editor",
    )
    if st.button("保存 PPT 资料管理修改", type="primary", key="save_deck_management"):
        execute_many(
            """
            UPDATE ppt_decks
            SET sort_order = ?, status = ?, category = ?, subject = ?, title = ?
            WHERE id = ? AND user_id = ?
            """,
            [
                (
                    _int_or_zero(row["sort_order"]),
                    str(row["status"] or "使用中"),
                    str(row["category"] or "").strip(),
                    str(row["subject"] or "").strip(),
                    str(row["title"] or "").strip(),
                    int(row["id"]),
                    user_id,
                )
                for _, row in edited.iterrows()
            ],
        )
        st.success("PPT 资料管理修改已保存。")
        st.rerun()

    st.divider()
    _render_delete_deck(user_id, visible)


def _render_question_management(user_id: int) -> None:
    st.subheader("插问记录管理")
    decks = _fetch_decks(user_id)
    if not decks:
        st.info("暂无 PPT/PDF 资料。")
        return

    deck_options = {deck["id"]: deck for deck in decks}
    deck_id = st.selectbox(
        "选择资料",
        list(deck_options),
        format_func=lambda item_id: _deck_label(deck_options[item_id]),
        key="question_manage_deck",
    )
    slides = _fetch_slides(user_id, deck_id)
    questions = _fetch_questions(user_id, deck_id)
    if not questions:
        st.info("这份资料还没有插问记录。")
        return

    slide_numbers = sorted({int(item["slide_number"]) for item in questions})
    categories = sorted({item.get("category") for item in questions if item.get("category")})
    cols = st.columns([1, 1, 1, 1.5])
    selected_slides = cols[0].multiselect(
        "页码筛选",
        slide_numbers,
        default=slide_numbers,
        key=f"question_manage_slide_filter_{deck_id}",
    )
    status_filter = cols[1].multiselect(
        "状态筛选",
        QUESTION_STATUSES,
        default=QUESTION_STATUSES,
        key=f"question_manage_status_filter_{deck_id}",
    )
    category_filter = cols[2].multiselect(
        "分类筛选",
        categories,
        default=categories,
        key=f"question_manage_category_filter_{deck_id}",
    )
    keyword = cols[3].text_input("搜索问题 / 回答", key="question_keyword")

    visible = [
        item
        for item in questions
        if int(item["slide_number"]) in selected_slides
        and item["status"] in status_filter
        and (not categories or item.get("category", "") in category_filter or not item.get("category"))
        and _matches_question_keyword(item, keyword)
    ]
    if not visible:
        st.warning("没有符合筛选条件的插问。")
        return

    frame = pd.DataFrame(visible)[
        [
            "id",
            "sort_order",
            "status",
            "category",
            "slide_number",
            "slide_title",
            "question_preview",
            "answer_preview",
            "model",
            "created_at",
        ]
    ]
    edited = st.data_editor(
        frame,
        use_container_width=True,
        hide_index=True,
        column_config={
            "id": st.column_config.NumberColumn("ID", disabled=True),
            "sort_order": st.column_config.NumberColumn("排序", step=1),
            "status": st.column_config.SelectboxColumn("状态", options=QUESTION_STATUSES),
            "category": st.column_config.TextColumn("分类", help=f"常用分类：{'、'.join(QUESTION_CATEGORIES)}"),
            "slide_number": st.column_config.NumberColumn("页码", disabled=True),
            "slide_title": st.column_config.TextColumn("页标题", disabled=True),
            "question_preview": st.column_config.TextColumn("问题预览", disabled=True),
            "answer_preview": st.column_config.TextColumn("回答预览", disabled=True),
            "model": st.column_config.TextColumn("模型", disabled=True),
            "created_at": st.column_config.TextColumn("创建时间", disabled=True),
        },
        key="ppt_question_management_editor",
    )
    if st.button("保存插问管理修改", type="primary", key=f"save_question_management_{deck_id}"):
        execute_many(
            """
            UPDATE slide_questions
            SET sort_order = ?, status = ?, category = ?
            WHERE id = ? AND user_id = ?
            """,
            [
                (
                    _int_or_zero(row["sort_order"]),
                    str(row["status"] or "未整理"),
                    str(row["category"] or "").strip(),
                    int(row["id"]),
                    user_id,
                )
                for _, row in edited.iterrows()
            ],
        )
        st.success("插问管理修改已保存。")
        st.rerun()

    st.divider()
    _render_question_detail_and_delete(user_id, visible, slides)


def _render_delete_deck(user_id: int, decks: list[dict]) -> None:
    st.subheader("删除 PPT / PDF 资料")
    st.warning("删除资料会同时删除该资料下的页面、逐页讲解和插问记录。上传文件和页面图片默认保留在本地 data 目录。")
    deck_options = {deck["id"]: deck for deck in decks}
    deck_id = st.selectbox(
        "选择要删除的资料",
        list(deck_options),
        format_func=lambda item_id: _deck_label(deck_options[item_id]),
        key="delete_deck_id",
    )
    confirm = st.text_input("输入 DELETE 确认删除", key="delete_deck_confirm")
    if st.button("删除这份资料", disabled=confirm != "DELETE", key="delete_deck_button"):
        execute("DELETE FROM ppt_decks WHERE id = ? AND user_id = ?", (int(deck_id), user_id))
        st.success("资料已删除。")
        st.rerun()


def _render_question_detail_and_delete(user_id: int, questions: list[dict], slides: list[dict]) -> None:
    st.subheader("查看 / 删除单条插问")
    question_options = {item["id"]: item for item in questions}
    question_id = st.selectbox(
        "选择插问",
        list(question_options),
        format_func=lambda item_id: _question_label(question_options[item_id]),
        key="delete_question_id",
    )
    question = question_options[question_id]
    with st.expander("查看完整问题和回答", expanded=True):
        st.markdown("**问题**")
        st.markdown(question["question"])
        st.markdown("**回答**")
        st.markdown(question["answer"])
    confirm = st.text_input("输入 DELETE 确认删除这条插问", key="delete_question_confirm")
    if st.button("删除这条插问", disabled=confirm != "DELETE", key="delete_question_button"):
        execute("DELETE FROM slide_questions WHERE id = ? AND user_id = ?", (int(question_id), user_id))
        st.success("插问已删除。")
        st.rerun()


def _fetch_decks(user_id: int) -> list[dict]:
    return fetch_all(
        """
        SELECT
            d.*,
            COALESCE(q.question_count, 0) AS question_count
        FROM ppt_decks d
        LEFT JOIN (
            SELECT ps.deck_id, COUNT(sq.id) AS question_count
            FROM ppt_slides ps
            LEFT JOIN slide_questions sq ON sq.slide_id = ps.id AND sq.user_id = ps.user_id
            WHERE ps.user_id = ?
            GROUP BY ps.deck_id
        ) q ON q.deck_id = d.id
        WHERE d.user_id = ?
        ORDER BY
            CASE d.status
                WHEN '使用中' THEN 0
                WHEN '待整理' THEN 1
                WHEN '暂停' THEN 2
                WHEN '归档' THEN 3
                ELSE 9
            END,
            d.category ASC,
            d.sort_order ASC,
            d.created_at DESC,
            d.id DESC
        """,
        (user_id, user_id),
    )


def _fetch_slides(user_id: int, deck_id: int) -> list[dict]:
    return fetch_all(
        """
        SELECT id, slide_number, title
        FROM ppt_slides
        WHERE user_id = ? AND deck_id = ?
        ORDER BY slide_number ASC
        """,
        (user_id, deck_id),
    )


def _fetch_questions(user_id: int, deck_id: int) -> list[dict]:
    rows = fetch_all(
        """
        SELECT
            sq.*,
            ps.slide_number,
            ps.title AS slide_title
        FROM slide_questions sq
        JOIN ppt_slides ps ON ps.id = sq.slide_id AND ps.user_id = sq.user_id
        WHERE sq.user_id = ? AND ps.deck_id = ?
        ORDER BY sq.status ASC, sq.category ASC, sq.sort_order ASC, ps.slide_number ASC, sq.created_at ASC, sq.id ASC
        """,
        (user_id, deck_id),
    )
    for row in rows:
        row["question_preview"] = _preview(row["question"], 80)
        row["answer_preview"] = _preview(row["answer"], 90)
    return rows


def _matches_deck_keyword(deck: dict, keyword: str) -> bool:
    text = " ".join(str(deck.get(key) or "") for key in ["title", "subject", "filename", "category"])
    return not keyword.strip() or keyword.strip().lower() in text.lower()


def _matches_question_keyword(question: dict, keyword: str) -> bool:
    text = " ".join(str(question.get(key) or "") for key in ["question", "answer", "category", "slide_title"])
    return not keyword.strip() or keyword.strip().lower() in text.lower()


def _preview(text: str, limit: int) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip() + "..."


def _int_or_zero(value: object) -> int:
    try:
        if pd.isna(value):
            return 0
        return int(value)
    except (TypeError, ValueError):
        return 0


def _deck_label(deck: dict) -> str:
    category = deck.get("category") or "未分类"
    return f"#{deck['id']} · {category} · {deck.get('subject') or '未分类科目'} · {deck['title']}"


def _question_label(question: dict) -> str:
    return f"#{question['id']} · 第 {question['slide_number']} 页 · {_preview(question['question'], 48)}"
