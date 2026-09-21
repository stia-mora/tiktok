from contextlib import closing
from datetime import date
import io
import csv
import json

import pandas as pd
import streamlit as st

from ads_collector import csv_text
from ads_store import connect, DB_PATH
from ui_zh import country_name, STATUS_NAMES, STOP_NAMES
from video_collector import VIDEO_DB


def show_history():
    st.subheader("本地历史数据库")
    source = st.radio("数据来源", ["广告素材", "热门视频素材"], horizontal=True, key="history_source")
    is_video = source == "热门视频素材"
    db_path = VIDEO_DB if is_video else DB_PATH
    st.caption("分析仅查询本地历史数据，不请求官方接口。首次发现指本库第一次采到的日期，不是广告上线日期。热门视频的实际发布时间来自视频详情页。")
    with closing(connect(db_path, readonly=True)) as conn:
        counts = conn.execute("SELECT COUNT(DISTINCT material_id), COUNT(*), MIN(observed_date), MAX(observed_date) FROM observations").fetchone()
        countries = [row[0] for row in conn.execute("SELECT DISTINCT country FROM observations ORDER BY country")]
        days = conn.execute("SELECT COUNT(DISTINCT observed_date) FROM observations").fetchone()[0]
        recent_runs = [json.loads(row[0]) for row in conn.execute("SELECT report_json FROM collection_runs ORDER BY started_at DESC LIMIT 50")]
    a, b, c = st.columns(3)
    a.metric("累计独立素材", counts[0])
    b.metric("累计采集记录", counts[1])
    c.metric("已有数据天数", days)
    if not counts[1]:
        st.info("还没有历史数据。请在“广告采集”中运行一次采集，结果会自动入库。")
        return
    a, b, c = st.columns(3)
    start = a.date_input("起始日期", date.fromisoformat(counts[2]), key="history_start")
    end = b.date_input("结束日期", date.fromisoformat(counts[3]), key="history_end")
    selected_country = c.selectbox("榜单国家" if is_video else "投放市场", ["全部"] + countries, format_func=country_name, key=f"history_country_{is_video}")
    if start > end:
        st.warning("起始日期不能晚于结束日期。")
        return
    params = [start.isoformat(), end.isoformat()]
    clause = "s.observed_date BETWEEN ? AND ?"
    if selected_country != "全部":
        clause += " AND s.country=?"
        params.append(selected_country)
    material_fields = "s.*, m.first_seen, m.published_at" if is_video else "s.*, m.first_seen"
    with closing(connect(db_path, readonly=True)) as conn:
        data = pd.read_sql_query(f"""SELECT {material_fields} FROM daily_snapshots s
            JOIN materials m USING(material_id) WHERE {clause} ORDER BY s.observed_at DESC""", conn, params=params)
    if data.empty:
        st.info("所选日期和国家没有采集记录。缺少记录不代表当天没有广告。")
        return
    query = st.text_input("搜索历史品牌、文案或素材编号", key="history_search")
    rows = []
    for record in data.to_dict("records"):
        payload = json.loads(record["payload_json"])
        row = {"日期": record["observed_date"], "国家": country_name(record["country"]), "素材编号": record["material_id"],
                     "品牌": payload.get("brand") or "未提供名称", "广告文案": payload.get("ad_text", ""), "播放量": payload.get("plays"),
                     "点赞数": record["likes"], "点击率原始值": record["ctr_raw"], "首次发现": record["first_seen"],
                     "视频地址": payload.get("video_url", ""), "广告详情": payload.get("detail_url", ""), "采集时间": record["observed_at"]}
        if is_video:
            row["实际发布时间"] = record["published_at"] or "未获取"
        rows.append(row)
    frame = pd.DataFrame(rows)
    if query:
        mask = frame[["品牌", "广告文案", "素材编号"]].astype(str).apply(lambda column: column.str.contains(query, case=False, regex=False)).any(axis=1)
        frame = frame[mask]
    st.caption("同一素材在同一国家同一天只展示最后一次快照；原始采集记录全部保留。")
    if frame.empty:
        st.info("没有匹配的历史记录。")
        return
    brand_label = "作者" if is_video else "品牌"
    st.subheader("每日采到的独立素材")
    trend = frame.groupby("日期")["素材编号"].nunique().rename("独立素材数").reset_index()
    if len(trend) == 1:
        st.dataframe(trend, hide_index=True, width="stretch")
        st.caption("目前只有一天的记录；积累多天后显示趋势曲线。")
    else:
        st.line_chart(trend, x="日期", y="独立素材数", x_label="日期", y_label="独立素材数")
    a, b = st.columns(2)
    with a:
        st.markdown("**榜单国家分布**" if is_video else "**投放市场分布**")
        st.bar_chart(frame.groupby("国家")["素材编号"].nunique().rename("独立素材数"), horizontal=True)
    with b:
        st.markdown(f"**{brand_label}素材数量（前 15 名）**")
        st.bar_chart(frame.groupby("品牌")["素材编号"].nunique().nlargest(15).rename("独立素材数"), horizontal=True)
    st.subheader("历史快照明细")
    page_count = max(1, (len(frame) + 99) // 100)
    page = st.number_input("明细页码（每页 100 条）", 1, page_count, 1, key="history_page")
    shown = frame.iloc[(int(page) - 1) * 100:int(page) * 100].copy()
    shown["首次发现"] = pd.to_datetime(shown["首次发现"], utc=True).dt.tz_convert("Asia/Shanghai").dt.strftime("%Y-%m-%d %H:%M")
    if is_video:
        actual = pd.to_datetime(shown["实际发布时间"], errors="coerce", utc=True)
        shown["实际发布时间"] = actual.dt.tz_convert("Asia/Shanghai").dt.strftime("%Y-%m-%d %H:%M").fillna("未获取")
    columns = ["日期", "国家", "素材编号", "品牌", "广告详情", "广告文案", "播放量", "点赞数", "点击率原始值"]
    if is_video:
        columns.append("实际发布时间")
    columns.extend(["首次发现", "视频地址", "采集时间"])
    st.dataframe(shown, hide_index=True, width="stretch", column_order=columns, column_config={"品牌": brand_label, "广告文案": "视频文案" if is_video else "广告文案", "点击率原始值": None if is_video else "点击率原始值", "播放量": "播放量" if is_video else None, "实际发布时间": "实际发布时间（北京时间）" if is_video else None, "广告详情": st.column_config.LinkColumn("原视频页面" if is_video else "官方广告页面", display_text="打开原视频" if is_video else "打开广告详情"), "视频地址": st.column_config.LinkColumn("临时媒体直链", display_text="临时链接", help="媒体 CDN 地址，可能过期或拒绝外部访问。观看请优先打开原视频或官方广告页面。")})
    st.caption("观看请点击“打开原视频 / 打开广告详情”。临时媒体直链不是网页地址，可能过期或受网络、播放权限限制。")
    output = io.StringIO()
    export_frame = frame.rename(columns={"品牌": brand_label, "广告文案": "视频文案" if is_video else "广告文案", "广告详情": "视频页面" if is_video else "广告详情"})
    writer = csv.DictWriter(output, fieldnames=list(export_frame.columns))
    writer.writeheader()
    writer.writerows({key: csv_text(value) for key, value in row.items()} for row in export_frame.to_dict("records"))
    st.download_button("导出筛选后的全部历史记录", output.getvalue().encode("utf-8-sig"), "广告历史数据.csv", "text/csv")
    st.subheader("单个素材的指标变化")
    ids = frame["素材编号"].drop_duplicates().tolist()
    material_id = st.selectbox("选择素材编号", ids, key="history_material")
    selected_row = frame[frame["素材编号"] == material_id].sort_values("采集时间").iloc[-1]
    page_url = selected_row["广告详情"]
    if page_url:
        st.link_button("在 TikTok 打开原视频" if is_video else "打开官方广告详情", page_url)
        with st.expander("应用内打不开？复制链接到 Edge / Chrome"):
            st.code(page_url, language=None)
            st.caption("用可正常访问 TikTok 的浏览器打开；平台可能要求登录。网页返回正常不代表视频一定能播放，删除或地区限制也可能影响访问。")
    # Likes are material-wide, not country-specific: remove cross-country duplicates.
    series = frame[frame["素材编号"] == material_id].sort_values("采集时间").drop_duplicates("日期", keep="last")
    if len(series) > 1:
        st.line_chart(series.set_index("日期")[["点赞数"]], x_label="日期", y_label="累计点赞数")
    else:
        st.info("该素材目前只有一天的数据，累积两天以上后可查看趋势。")
    st.caption("点赞等指标属于素材整体，不能把同一广告多个国家的数值相加。缺采日期不补零、不视为下线。")
    with st.expander("最近采集记录与覆盖情况"):
        logs = [{"批次": run["run_id"], "国家": country_name(code), "状态": STATUS_NAMES.get(item["status"], item["status"]), "页数": item["pages"], "条数": item["records"], "结束原因": STOP_NAMES.get(item.get("stop_reason"), "旧批次未记录")} for run in recent_runs for code, item in run["countries"].items()]
        st.dataframe(pd.DataFrame(logs), hide_index=True, width="stretch")
    st.caption(f"数据库：{db_path}")
