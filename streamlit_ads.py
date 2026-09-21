import json
from pathlib import Path

import pandas as pd
import streamlit as st

from ads_collector import COUNTRIES, ROOT, SORTS, collect_ads
from ui_zh import country_name, STATUS_NAMES, STOP_NAMES


def show_ads():
    st.subheader("多国家广告素材")
    st.caption("来源：TikTok Creative Center · Top Ads。国家表示广告投放市场，同一素材可能覆盖多个国家。")
    with st.expander("采集设置", expanded=True):
        with st.form("ads_collection"):
            countries = st.multiselect("投放国家 / 地区", list(COUNTRIES), default=["US", "JP", "GB"], format_func=lambda code: f"{country_name(code)} ({code})")
            keyword = st.text_input("品牌或产品关键词", placeholder="留空采集热门广告")
            a, b, c = st.columns(3)
            period = a.selectbox("时间范围", [7, 30, 180], index=1, format_func=lambda value: f"最近 {value} 天")
            pages = b.number_input("每国页数（0 表示翻到接口末页）", 0, 1000, 0)
            limit = c.number_input("每页数量", 1, 20, 20)
            st.caption("每页数量不是总条数。自动分页会在末页、重复页或接口报错时停止，并记录覆盖情况。")
            a, b = st.columns(2)
            sort = a.selectbox("排序", list(SORTS), format_func=SORTS.get)
            download_count = b.number_input("每个国家下载前 N 条 MP4（0 为仅导出链接）", 0, 20, 0)
            cookie_file = st.text_input("本机 Cookie 文件路径", value="D:/Edge-Download/ads.tiktok.com_cookies.txt")
            fetch_details = st.checkbox("补充广告详情并核实投放地区（额外请求，连续失败时暂停）", value=False)
            submitted = st.form_submit_button("开始采集", type="primary")
        if submitted:
            if not countries:
                st.error("请至少选择一个国家。")
            elif not Path(cookie_file).is_file():
                st.error("Cookie 文件不存在，请填写本机文件路径。")
            else:
                try:
                    with st.spinner("正在按国家采集广告、核对投放地区并保存素材…"):
                        report = collect_ads(countries, cookie_file, int(pages), int(limit), period, keyword, sort, int(download_count), details=fetch_details)
                    st.session_state["ads_run"] = report["run_id"]
                    if any(value["status"] == "partial" or value["errors"] for value in report["countries"].values()):
                        st.warning("采集完成，部分请求失败。请查看下方各国状态。")
                    else:
                        st.success(f"完成：{report['total_records']} 条国家记录，{report['unique_materials']} 个独立素材。")
                except Exception as exc:
                    # Cookie parse errors may include secret lines: show only the class.
                    st.error(f"采集未完成（{type(exc).__name__}），请检查 Cookie 格式、网络和目录权限。")
    ads_root = ROOT / "output" / "ads"
    runs = sorted([path.parent.name for path in ads_root.glob("*/report.json")], reverse=True)
    if not runs:
        st.info("尚无广告数据，请先运行采集。")
        return
    preferred = st.session_state.get("ads_run", runs[0])
    selected = st.selectbox("采集批次", runs, index=runs.index(preferred) if preferred in runs else 0)
    folder = ads_root / selected
    report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    if not (folder / "ads.json").exists():
        st.info("该批次仍在采集，请稍后刷新。")
        return
    rows = json.loads((folder / "ads.json").read_text(encoding="utf-8"))
    a, b, c = st.columns(3)
    a.metric("国家记录", report.get("total_records", 0))
    b.metric("独立广告素材", report.get("unique_materials", 0))
    c.metric("已下载 MP4", report.get("unique_videos_downloaded", 0))
    st.dataframe(pd.DataFrame([{"国家": country_name(code), "状态": STATUS_NAMES.get(value["status"], value["status"]), "采集条数": value["records"], "已采页数": value["pages"], "接口返回总数": value.get("total_available"), "结束原因": STOP_NAMES.get(value.get("stop_reason"), "旧批次未记录"), "详情确认投放": value["verified_records"], "下载数": value["downloaded"]} for code, value in report["countries"].items()]), hide_index=True, width="stretch")
    errors = {code: value["errors"] for code, value in report["countries"].items() if value["errors"]}
    if errors:
        with st.expander("失败请求"):
            st.dataframe(pd.DataFrame([{"国家": country_name(code), "阶段": {"detail": "广告详情", "list": "广告列表", "download": "视频下载"}.get(item.get("stage"), "请求"), "素材编号": item.get("material_id", ""), "页码": item.get("page"), "错误类型": item.get("error", "")} for code, items in errors.items() for item in items]), hide_index=True, width="stretch")
    if not rows:
        st.info("本批次没有可展示的广告数据。")
        return
    a, b = st.columns(2)
    a.download_button("导出全部 CSV", (folder / "ads.csv").read_bytes(), file_name=f"ads_{selected}.csv", mime="text/csv")
    b.download_button("导出全部 JSON", (folder / "ads.json").read_bytes(), file_name=f"ads_{selected}.json", mime="application/json")
    country = st.selectbox("查看国家", ["全部"] + list(report["countries"]), format_func=country_name)
    filtered = [row for row in rows if country == "全部" or row["query_country"] == country]
    frame = pd.DataFrame(filtered)
    if frame.empty:
        st.info("该国家在本批次没有数据。")
        return
    columns = ["query_country", "material_id", "brand", "ad_text", "likes", "duration_seconds", "country_verified", "detail_url"]
    frame["query_country"] = frame["query_country"].map(country_name)
    st.dataframe(frame[columns], hide_index=True, width="stretch", column_config={"query_country": "国家", "material_id": "素材编号", "brand": "品牌", "ad_text": "广告文案", "likes": "点赞数", "duration_seconds": "时长（秒）", "country_verified": "详情确认投放", "detail_url": st.column_config.LinkColumn("广告详情")})
    if filtered:
        selected_ad = st.selectbox("素材预览", range(len(filtered)), format_func=lambda index: f"{country_name(filtered[index]['query_country'])} · {filtered[index]['brand'] or '未提供品牌'} · {filtered[index]['material_id']}")
        ad = filtered[selected_ad]
        left, right = st.columns([1, 2])
        with left:
            local = Path(ad["video_file"]) if ad["video_file"] else None
            if local and local.is_file() and local.resolve().is_relative_to(ads_root.resolve()):
                st.video(str(local))
                st.download_button("下载 MP4", local.read_bytes(), file_name=local.name, mime="video/mp4")
            elif ad["video_url"] and st.checkbox("尝试播放远程素材", value=False, key="ads_remote_preview"):
                st.video(ad["video_url"])
        with right:
            st.write(ad["ad_text"] or "此广告未提供文案")
            st.write("投放地区：" + ("、".join(country_name(code) for code in ad["delivery_countries"]) or "详情未提供"))
            st.link_button("打开官方广告详情", ad["detail_url"])
            if ad["cover_url"]:
                st.link_button("打开封面原图", ad["cover_url"])
            st.caption("视频和封面链接可能过期，可重新采集更新。CTR 与花费字段保留接口原始值，不解释为实际花费金额。")
    st.caption(f"本地输出：{folder}")
