from __future__ import annotations

from datetime import datetime

import streamlit as st

from services.reminder_service import (
    REMINDER_TASK_NAME,
    get_daily_reminder_config,
    get_today_review_log,
    get_windows_task_status,
    install_windows_daily_review_task,
    is_daily_review_due_now,
    mark_today_review_done,
    run_daily_review_reminder_now,
    save_daily_reminder_config,
    uninstall_windows_daily_review_task,
)


def render() -> None:
    st.title("每日复盘提醒")
    st.caption("本地提醒功能：到点后通过 Windows 计划任务弹窗并打开 INTP Study Manager。")

    config = get_daily_reminder_config()
    review_done = get_today_review_log()
    due_now = is_daily_review_due_now(config)

    cols = st.columns(3)
    cols[0].metric("提醒状态", "启用" if config["enabled"] else "关闭")
    cols[1].metric("提醒时间", config["time"])
    cols[2].metric("今日复盘", "已完成" if review_done else "未完成")

    if due_now:
        st.warning("已经到今天的复盘时间，建议现在完成每日复盘。")
    elif review_done:
        st.success(f"今日复盘已完成：{review_done['created_at']}")
    else:
        st.info(f"今天 {config['time']} 会提醒你进行每日复盘。")

    st.subheader("提醒设置")
    with st.form("daily_review_reminder_config"):
        enabled = st.checkbox("启用每日复盘提醒", value=config["enabled"])
        reminder_time = st.time_input(
            "每天提醒时间",
            value=datetime.strptime(config["time"], "%H:%M").time(),
            step=300,
        )
        saved = st.form_submit_button("保存设置")

    if saved:
        save_daily_reminder_config(enabled, reminder_time)
        st.success("提醒设置已保存。若已安装 Windows 计划任务，请点击下方“安装 / 更新计划任务”让时间生效。")
        st.rerun()

    st.subheader("Windows 计划任务")
    st.caption(f"任务名：{REMINDER_TASK_NAME}。电脑需要开机并登录 Windows；这不是邮件提醒。")
    task_ok, task_output = get_windows_task_status()
    if task_ok:
        st.success("计划任务已存在。")
        with st.expander("查看计划任务状态", expanded=False):
            st.text(task_output)
    elif "计划任务尚未安装" in task_output:
        st.info(task_output)
    else:
        st.warning("计划任务尚未安装，或当前环境无法读取。")
        with st.expander("查看系统返回", expanded=False):
            st.text(task_output)

    task_cols = st.columns(3)
    if task_cols[0].button("安装 / 更新计划任务", type="primary"):
        ok, output = install_windows_daily_review_task(config["time"])
        if ok:
            st.success("计划任务已安装 / 更新。")
        else:
            st.error("计划任务安装失败。")
        st.text(output)

    if task_cols[1].button("测试提醒"):
        ok, output = run_daily_review_reminder_now()
        if ok:
            st.success("测试提醒已触发。")
        else:
            st.error("测试提醒失败。")
        st.text(output)

    if task_cols[2].button("卸载计划任务"):
        ok, output = uninstall_windows_daily_review_task()
        if ok:
            st.success("计划任务已卸载。")
        else:
            st.error("计划任务卸载失败。")
        st.text(output)

    st.subheader("标记今日复盘")
    with st.form("mark_daily_review_done"):
        notes = st.text_area(
            "今日复盘备注",
            placeholder="例如：完成了信号与系统第 9 章复盘；Z 反变换 ROC 仍需追问。",
            height=120,
        )
        submitted = st.form_submit_button("标记今天已完成复盘")
    if submitted:
        mark_today_review_done(notes)
        st.success("今日复盘已标记完成。")
        st.rerun()
