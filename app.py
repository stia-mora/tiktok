import json
from pathlib import Path
import streamlit as st
from streamlit_creators import show_creators
from streamlit_posts import show_posts
from streamlit_hashtags import show_hashtags
from streamlit_ads import show_ads
from streamlit_history import show_history
from streamlit_video_materials import show_video_materials
from streamlit_analysis import show_analysis

# === Page configuration ===
st.set_page_config(
    page_title="TikTok 素材数据中心",
    page_icon="image/tiktok.png",
    layout="wide"
)

# === Custom CSS ===
st.markdown(
    """
    <style>
    /* Adjust max width */
    .block-container {
        max-width: 1200px;
        margin: auto;
    }

    /* Metric cards styling */
    [data-testid="stMetric"] {
        border: 2px solid #FFD1DC;  /* 淡粉色边框 */
        border-radius: 10px;
        padding: 15px;
        background-color: #FFF0F5;  /* 淡粉色背景 */
    }

    /* Data editor / tables styling */
    div[data-testid="stDataEditor"] {
        border: 2px solid #FFD1DC;  /* 淡粉色边框 */
        border-radius: 10px;
        padding: 10px;
        background-color: #FFF0F5;  /* 淡粉色背景 */
    }

    /* Optional: make column headers bold */
    div[data-testid="stDataEditor"] th {
        font-weight: bold;
    }
    </style>
    """,
    unsafe_allow_html=True
)

# === Logo and title ===
st.image("image/tiktok.png", width=80)
st.title("TikTok 素材数据中心")
st.caption("广告与热门视频持续归档，在自己的历史数据库中检索和分析。")
with st.expander("每日采集计划"):
    st.write("北京时间每天 09:00 · 全部 28 个国家 / 地区 · 广告 + 11 类热门视频素材")
    st.write("仅保存链接、文案、作者与指标，不自动下载视频文件。广告使用最近 30 天窗口，视频使用接口当前热门榜单。")
    st.caption("服务器每天按北京时间 09:00 执行；登录失效、上游限流或地区权限限制的任务会在状态记录中保留。")
    daily_states = []
    for path in (Path(__file__).resolve().parent / "output" / "daily").glob("*.json"):
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(state, dict) and isinstance(state.get("date"), str) and isinstance(state.get("countries"), dict):
            daily_states.append((path, state))
    if daily_states:
        _, daily_state = max(daily_states, key=lambda item: (item[1]["date"], item[0].stat().st_mtime))
        jobs = daily_state["countries"]
        completed = sum(bool(item.get("complete")) for item in jobs.values())
        st.write(f"最近执行日期：{daily_state['date']}；已完成 {completed} / {len(jobs)} 个来源与国家任务。")
    else:
        st.caption("每日全量计划尚未执行；当前数据库已有手动实测数据。")

# === Tabs ===
tab_ads, tab_videos, tab_history, tab_analysis, tab1, tab2, tab3 = st.tabs(["广告采集", "视频素材", "历史数据库", "爆款分析", "创作者", "早期视频数据", "热门话题"])

with tab_videos:
    show_video_materials()

with tab_ads:
    show_ads()

with tab_history:
    show_history()

with tab_analysis:
    show_analysis()

with tab1:
    show_creators()
with tab2:
    show_posts()
with tab3:
    show_hashtags()
