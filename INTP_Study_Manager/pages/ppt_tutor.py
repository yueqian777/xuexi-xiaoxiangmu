from __future__ import annotations

import os

import pandas as pd
import streamlit as st

from db import fetch_all, fetch_one, insert_and_get_id
from services.openai_service import DEFAULT_MODEL, OpenAIServiceError, generate_text
from services.ppt_service import import_pptx
from services.prompt_service import render_template


def render() -> None:
    st.title("PPT 逐页讲解")
    st.caption("边看 PPT 边让 GPT 按页讲解；插问单独进入浮窗，不覆盖当前页主线讲解。")

    _render_api_settings()
    _render_upload_form()

    decks = fetch_all("SELECT * FROM ppt_decks ORDER BY created_at DESC, id DESC")
    if not decks:
        st.info("请先上传一个 PPTX 文件。当前版本会解析每页文字内容，后续可继续增强真实幻灯片画面渲染。")
        return

    deck_id = st.selectbox(
        "选择 PPT",
        [deck["id"] for deck in decks],
        format_func=lambda item_id: _deck_label(decks, item_id),
    )
    deck = fetch_one("SELECT * FROM ppt_decks WHERE id = ?", (deck_id,))
    slides = fetch_all(
        "SELECT * FROM ppt_slides WHERE deck_id = ? ORDER BY slide_number ASC",
        (deck_id,),
    )
    if not deck or not slides:
        st.warning("这个 PPT 暂无可用页面，请重新上传。")
        return

    slide_id = st.selectbox(
        "当前页",
        [slide["id"] for slide in slides],
        format_func=lambda item_id: _slide_label(slides, item_id),
    )
    slide = fetch_one("SELECT * FROM ppt_slides WHERE id = ?", (slide_id,))
    if not slide:
        return

    st.divider()
    left, right = st.columns([1.05, 1], gap="large")
    with left:
        _render_slide_view(deck, slide)
    with right:
        _render_main_explanation(deck, slide)

    st.divider()
    _render_branch_popover(deck, slide)
    _render_question_history(slide["id"])


def _render_api_settings() -> None:
    with st.expander("ChatGPT API 设置", expanded=False):
        st.caption("API Key 只保存在当前 Streamlit 会话里，不写入 SQLite。也可以使用系统环境变量 OPENAI_API_KEY。")
        api_key = st.text_input(
            "OPENAI_API_KEY",
            value=st.session_state.get("openai_api_key", ""),
            type="password",
            placeholder="sk-...",
        )
        if api_key:
            st.session_state["openai_api_key"] = api_key

        model = st.text_input(
            "模型",
            value=st.session_state.get("openai_model", DEFAULT_MODEL),
            help="默认使用 OpenAI 当前 Quickstart 示例中的 Responses API 模型，可按你的账号权限修改。",
        )
        st.session_state["openai_model"] = model.strip() or DEFAULT_MODEL
        if api_key or os.getenv("OPENAI_API_KEY"):
            st.success("API Key 已可用。")
        else:
            st.warning("未检测到 API Key。你仍可查看自动生成的 Prompt，但不能直接调用 GPT。")


def _render_upload_form() -> None:
    with st.form("upload_pptx"):
        st.subheader("上传 PPT")
        cols = st.columns(2)
        subject = cols[0].text_input("科目", placeholder="例如：信号与系统")
        title = cols[1].text_input("PPT 标题", placeholder="例如：第 3 章 Z 变换")
        uploaded = st.file_uploader("选择 PPTX 文件", type=["pptx"])
        submitted = st.form_submit_button("导入 PPT")

    if submitted:
        if uploaded is None:
            st.error("请先选择 PPTX 文件。")
            return
        try:
            deck_id = import_pptx(uploaded, subject=subject, title=title)
        except Exception as exc:
            st.error(f"PPT 导入失败：{exc}")
            return
        st.success(f"PPT 已导入，编号 #{deck_id}。")
        st.rerun()


def _render_slide_view(deck: dict, slide: dict) -> None:
    st.subheader("PPT 阅读区")
    with st.container(border=True):
        st.markdown(f"**{deck['title']}**")
        st.caption(f"{deck.get('subject') or '未分类'} · 第 {slide['slide_number']} / {deck['slide_count']} 页")
        st.markdown(f"### {slide['title'] or '未命名页面'}")
        slide_text = (slide["slide_text"] or "").strip()
        if slide_text:
            st.markdown(_format_slide_text(slide_text))
        else:
            st.warning("这一页没有解析到文字。建议把关键文字复制到 PPT 文本框，或后续上传导出的 PDF 版本。")


def _render_main_explanation(deck: dict, slide: dict) -> None:
    st.subheader("当前页主线讲解")
    latest = _latest_explanation(slide["id"])
    prompt = _build_slide_prompt(deck, slide)

    cols = st.columns(2)
    generate = cols[0].button("生成 / 更新本页讲解", type="primary")
    show_prompt = cols[1].toggle("显示本页讲解 Prompt", value=False)

    if show_prompt:
        st.code(prompt, language="markdown")

    if generate:
        try:
            with st.spinner("GPT 正在按当前页生成主线讲解..."):
                explanation = generate_text(
                    prompt,
                    api_key=st.session_state.get("openai_api_key"),
                    model=st.session_state.get("openai_model", DEFAULT_MODEL),
                )
            insert_and_get_id(
                """
                INSERT INTO slide_explanations (slide_id, model, explanation)
                VALUES (?, ?, ?)
                """,
                (slide["id"], st.session_state.get("openai_model", DEFAULT_MODEL), explanation),
            )
            st.success("本页主线讲解已保存。")
            st.rerun()
        except OpenAIServiceError as exc:
            st.error(str(exc))
            st.caption("可以先复制下面的 Prompt 到 ChatGPT 手动使用。")
            st.code(prompt, language="markdown")

    latest = _latest_explanation(slide["id"])
    if latest:
        st.markdown(latest["explanation"])
        st.caption(f"模型：{latest['model']} · 生成时间：{latest['created_at']}")
    else:
        st.info("还没有生成本页主线讲解。点击上方按钮，或先复制 Prompt 到 ChatGPT。")


def _render_branch_popover(deck: dict, slide: dict) -> None:
    latest = _latest_explanation(slide["id"])
    with st.popover("打开插问浮窗：问问题但不覆盖主线讲解", use_container_width=True):
        st.markdown(f"**当前锚点：第 {slide['slide_number']} 页 · {slide['title']}**")
        st.caption("这里的回答会保存到插问记录，不会覆盖右侧的主线讲解。")
        with st.form(f"branch_question_{slide['id']}", clear_on_submit=True):
            question = st.text_area("我的插问", placeholder="例如：这一页里的 ROC 为什么会影响反变换？")
            submitted = st.form_submit_button("问 GPT")

        if submitted:
            if not question.strip():
                st.error("插问不能为空。")
                return
            prompt = _build_branch_prompt(deck, slide, latest, question.strip())
            try:
                with st.spinner("GPT 正在回答插问..."):
                    answer = generate_text(
                        prompt,
                        api_key=st.session_state.get("openai_api_key"),
                        model=st.session_state.get("openai_model", DEFAULT_MODEL),
                    )
                insert_and_get_id(
                    """
                    INSERT INTO slide_questions (slide_id, question, answer, model)
                    VALUES (?, ?, ?, ?)
                    """,
                    (slide["id"], question.strip(), answer, st.session_state.get("openai_model", DEFAULT_MODEL)),
                )
                st.success(f"插问已保存。现在回到第 {slide['slide_number']} 页主线。")
                st.rerun()
            except OpenAIServiceError as exc:
                st.error(str(exc))
                st.caption("可以先复制下面的插问 Prompt 到 ChatGPT 手动使用。")
                st.code(prompt, language="markdown")


def _render_question_history(slide_id: int) -> None:
    questions = fetch_all(
        """
        SELECT question, answer, model, created_at
        FROM slide_questions
        WHERE slide_id = ?
        ORDER BY created_at DESC, id DESC
        """,
        (slide_id,),
    )
    st.subheader("本页插问记录")
    if not questions:
        st.caption("当前页还没有插问。")
        return
    for item in questions:
        with st.container(border=True):
            st.markdown(f"**问：** {item['question']}")
            st.markdown(item["answer"])
            st.caption(f"模型：{item['model']} · {item['created_at']}")

    with st.expander("表格视图"):
        st.dataframe(pd.DataFrame(questions), use_container_width=True, hide_index=True)


def _latest_explanation(slide_id: int) -> dict | None:
    return fetch_one(
        """
        SELECT *
        FROM slide_explanations
        WHERE slide_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (slide_id,),
    )


def _build_slide_prompt(deck: dict, slide: dict) -> str:
    return render_template(
        "ppt_slide_explain.md",
        {
            "subject": deck.get("subject") or "未分类",
            "deck_title": deck["title"],
            "slide_number": str(slide["slide_number"]),
            "slide_title": slide["title"] or "未命名页面",
            "slide_text": slide["slide_text"] or "这一页没有解析到文字。",
        },
    )


def _build_branch_prompt(deck: dict, slide: dict, latest: dict | None, question: str) -> str:
    return render_template(
        "ppt_branch_question.md",
        {
            "subject": deck.get("subject") or "未分类",
            "deck_title": deck["title"],
            "slide_number": str(slide["slide_number"]),
            "slide_title": slide["title"] or "未命名页面",
            "slide_text": slide["slide_text"] or "这一页没有解析到文字。",
            "main_explanation": latest["explanation"] if latest else "尚未生成主线讲解。",
            "question": question,
        },
    )


def _deck_label(decks: list[dict], deck_id: int) -> str:
    deck = next(item for item in decks if item["id"] == deck_id)
    return f"#{deck_id} · {deck['subject'] or '未分类'} · {deck['title']} · {deck['slide_count']} 页"


def _slide_label(slides: list[dict], slide_id: int) -> str:
    slide = next(item for item in slides if item["id"] == slide_id)
    return f"第 {slide['slide_number']} 页 · {slide['title'] or '未命名页面'}"


def _format_slide_text(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(f"- {line}" for line in lines)

