"""Read-only Streamlit presentation for automatic viral-video analysis."""
from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path

import pandas as pd
import streamlit as st

from ads_collector import ROOT
from ads_store import connect
from analysis_pipeline import ANALYSIS_VERSION, RULE_VERSION, VIDEO_DB
from ui_zh import country_name, GENRES


def _tables_exist(conn) -> bool:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('analysis_evaluations', 'analysis_jobs', 'analysis_results')").fetchall()
    return len(rows) == 3


def _rows() -> pd.DataFrame:
    with closing(connect(VIDEO_DB, readonly=True)) as conn:
        if not _tables_exist(conn):
            return pd.DataFrame()
        return pd.read_sql_query("""
            SELECT e.material_id, e.country, e.category, e.published_at, e.age_bucket, e.score,
                   e.jev_decision, e.jev_confidence, e.creative_score, e.conversion_score,
                   e.duplicate_risk, e.jev_model, e.status AS evaluation_status, e.last_error,
                   j.status AS job_status, j.attempt_count, j.last_error_class, j.completed_at,
                   r.created_at AS analysis_created_at
            FROM analysis_evaluations AS e
            LEFT JOIN analysis_jobs AS j ON j.material_id=e.material_id AND j.analysis_version=?
            LEFT JOIN analysis_results AS r ON r.material_id=e.material_id AND r.analysis_version=?
            WHERE e.evaluation_version=?
            ORDER BY e.score DESC, e.evaluated_at DESC
        """, conn, params=(ANALYSIS_VERSION, ANALYSIS_VERSION, RULE_VERSION))


def _read_result(material_id: str):
    with closing(connect(VIDEO_DB, readonly=True)) as conn:
        row = conn.execute("SELECT * FROM analysis_results WHERE material_id=? AND analysis_version=?",
                           (material_id, ANALYSIS_VERSION)).fetchone()
    return row


def show_analysis():
    st.subheader("爆款分析")
    st.caption("系统按真实发布时间、增长速度、互动率与持续性自动筛选。Jev 判定通过后直接进入 VLM，不设人工抽检。")
    try:
        frame = _rows()
    except Exception:
        st.info("分析数据库暂不可读，采集数据不受影响。")
        return
    if frame.empty:
        st.info("分析流水线尚未完成首次评估。每日采集后的分析 worker 会自动回填最近 30 天可评估素材。")
        return
    a, b, c, d = st.columns(4)
    a.metric("已评分素材", len(frame))
    b.metric("Jev 深度通过", int((frame["jev_decision"] == "deep").sum()))
    c.metric("等待/处理中", int(frame["job_status"].isin(["pending", "retry_wait", "running"]).sum()))
    d.metric("分析完成", int(frame["analysis_created_at"].notna().sum()))
    countries = ["全部"] + sorted(frame["country"].dropna().unique().tolist())
    categories = ["全部"] + sorted(frame["category"].dropna().unique().tolist())
    statuses = ["全部"] + sorted(frame["job_status"].fillna("未入队").unique().tolist())
    first, second, third = st.columns(3)
    country = first.selectbox("国家 / 地区", countries, format_func=lambda code: "全部" if code == "全部" else country_name(code), key="analysis_country")
    category = second.selectbox("分类", categories, format_func=lambda value: "全部" if value == "全部" else GENRES.get(value, value), key="analysis_category")
    status = third.selectbox("分析状态", statuses, key="analysis_status")
    filtered = frame.copy()
    if country != "全部":
        filtered = filtered[filtered["country"] == country]
    if category != "全部":
        filtered = filtered[filtered["category"] == category]
    if status != "全部":
        filtered = filtered[filtered["job_status"].fillna("未入队") == status]
    display = filtered.rename(columns={
        "material_id": "素材编号", "country": "国家", "category": "分类", "published_at": "实际发布时间", "age_bucket": "年龄段",
        "score": "定量评分", "jev_decision": "Jev 判定", "jev_confidence": "Jev 置信度", "creative_score": "创意复用", "conversion_score": "转化价值",
        "duplicate_risk": "重复风险", "job_status": "任务状态", "attempt_count": "尝试次数", "analysis_created_at": "分析完成时间",
    })
    display["国家"] = display["国家"].map(country_name)
    display["分类"] = display["分类"].map(lambda value: GENRES.get(value, value))
    st.dataframe(display[["素材编号", "国家", "分类", "实际发布时间", "年龄段", "定量评分", "Jev 判定", "Jev 置信度", "创意复用", "转化价值", "重复风险", "任务状态", "尝试次数", "分析完成时间"]],
                 hide_index=True, width="stretch")
    if filtered.empty:
        return
    material_id = st.selectbox("查看素材分析", filtered["material_id"].tolist(), key="analysis_material")
    result = _read_result(material_id)
    if result is None:
        selected = filtered[filtered["material_id"] == material_id].iloc[0]
        if selected["job_status"] == "failed":
            st.warning(f"分析未完成：{selected['last_error_class'] or '未知错误'}。系统会对可重试故障自动延迟重试。")
        else:
            st.info("该素材尚未生成 VLM 报告。")
        return
    report = json.loads(result["report_json"])
    st.markdown(f"### {report.get('summary_zh', '分析报告')}")
    evidence = report.get("evidence", {})
    frame_paths = evidence.get("frames", [])
    images = [ROOT / "output" / path for path in frame_paths if (ROOT / "output" / path).is_file()]
    if images:
        st.image(images, caption=[path.name for path in images], width=220)
    labels = {
        "viral_mechanisms": "爆发机制", "hook": "前 3 秒钩子", "creative_structure": "创意结构", "visual_language": "视觉语言", "on_screen_text": "屏幕文字", "subtitle_summary": "字幕摘要",
        "audience": "受众", "comment_insights": "评论洞察", "conversion_analysis": "转化分析",
        "reusable_playbook": "可复用打法", "risks": "风险与不确定性", "missing_inputs": "缺失输入",
    }
    for key, label in labels.items():
        with st.expander(label, expanded=key in {"hook", "conversion_analysis", "reusable_playbook"}):
            value = report.get(key)
            if isinstance(value, (dict, list)):
                st.json(value, expanded=False)
            else:
                st.write(value or "未提供")
    left, right = st.columns(2)
    left.download_button("下载 JSON 报告", result["report_json"].encode("utf-8"), f"爆款分析_{material_id}.json", "application/json")
    right.download_button("下载 Markdown 报告", result["report_markdown"].encode("utf-8"), f"爆款分析_{material_id}.md", "text/markdown")
