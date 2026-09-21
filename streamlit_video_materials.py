import json
from pathlib import Path
import streamlit as st
import pandas as pd

from ads_collector import COUNTRIES, ROOT
from video_collector import collect_videos
from ui_zh import GENRES, country_name, STATUS_NAMES, STOP_NAMES


def show_video_materials():
    st.subheader("热门视频素材采集")
    st.caption("独立采集热门视频，不将普通视频标为广告。国家按榜单筛选条件记录，不代表作者国籍或广告投放地区。")
    with st.form("video_material_collection"):
        countries = st.multiselect("榜单国家 / 地区", list(COUNTRIES), default=["US", "JP", "GB"], format_func=country_name)
        genres = st.multiselect("视频内容分类", list(GENRES), default=list(GENRES), format_func=GENRES.get)
        pages = st.number_input("每国每分类页数（0 表示翻到接口末页）", 0, 100, 0)
        cookies = st.text_input("视频采集 Cookie 文件路径", "D:/Edge-Download/ads.tiktok.com_cookies.txt")
        st.caption("每页 10 条，自动翻页累计采集。只保存链接和指标，不自动下载 MP4。")
        submit = st.form_submit_button("采集视频素材并入库", type="primary")
    if submit:
        if not countries or not genres:
            st.error("请至少选择一个国家和一个分类。")
        elif not Path(cookies).is_file():
            st.error("Cookie 文件不存在。")
        else:
            try:
                with st.spinner("正在采集视频素材，逐页保存到历史库…"):
                    report = collect_videos(countries, cookies, int(pages), genres)
                st.success(f"已保存 {report['total_records']} 条国家记录、{report['unique_materials']} 个独立视频。")
                if any(not item["pagination_complete"] for item in report["countries"].values()):
                    st.warning("部分国家或分类未翻到接口末页，请查看结束原因。")
            except Exception as exc:
                st.error(f"采集未完成（{type(exc).__name__}）。已经入库的数据仍然保留。")
    root = ROOT / "output" / "videos"
    runs = sorted([file.parent for file in root.glob("*/report.json")], reverse=True)
    if not runs:
        st.info("暂无新的视频素材采集批次。原项目的示例数据仍可在“早期视频数据”查看。")
        return
    folder = st.selectbox("视频素材批次", runs, format_func=lambda path: path.name)
    report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    st.dataframe(pd.DataFrame([{"国家": country_name(code), "状态": STATUS_NAMES.get(item["status"], item["status"]), "页数": item["pages"], "独立视频": item["records"], "结束原因": STOP_NAMES.get(item["stop_reason"], item["stop_reason"])} for code, item in report["countries"].items()]), hide_index=True, width="stretch")
    path = folder / "videos.json"
    if not path.exists():
        st.info("本批次仍在采集，已完成页面可在历史数据库查看。")
        return
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not rows:
        st.info("本批次未返回视频素材。")
        return
    a, b = st.columns(2)
    a.download_button("导出视频素材表格", (folder / "videos.csv").read_bytes(), f"视频素材_{folder.name}.csv", "text/csv")
    b.download_button("导出视频素材原始数据", path.read_bytes(), f"视频素材_{folder.name}.json", "application/json")
    frame = pd.DataFrame([{"国家": country_name(row["query_country"]), "视频编号": row["material_id"], "作者": row["brand"], "文案": row["ad_text"], "播放量": row["plays"], "点赞量": row["likes"], "分类": "、".join(GENRES.get(value, value) for value in row["categories"]), "视频页面": row["detail_url"]} for row in rows])
    st.dataframe(frame, hide_index=True, width="stretch", column_config={"视频页面": st.column_config.LinkColumn("原视频页面", display_text="打开原视频")})
    index = st.selectbox("选择视频预览", range(len(rows)), format_func=lambda index: f"{country_name(rows[index]['query_country'])} · {rows[index]['brand']} · {rows[index]['material_id']}")
    row = rows[index]
    st.link_button("在 TikTok 打开原视频", row["detail_url"])
    with st.expander("复制原视频页面链接"):
        st.code(row["detail_url"], language=None)
        st.caption("应用内打不开时，可复制到能正常访问 TikTok 的 Edge / Chrome。")
    with st.expander("播放素材", expanded=False):
        preview = st.checkbox("尝试在线播放（链接可能失效或限制外部播放）", value=False, key="video_preview_enabled")
        if row["video_url"] and preview:
            st.video(row["video_url"])
        st.write(row["ad_text"])
        st.link_button("打开原视频", row["detail_url"])
        st.caption("媒体链接有有效期，过期后需重新采集；历史文案和指标不受影响。")
