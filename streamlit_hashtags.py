from ui_zh import translate_genres
import os
from pathlib import Path
import streamlit as st
import pandas as pd
import sqlite3
import datetime

def show_hashtags():
    # Helper function to format numbers (K, M)
    def format_number(n):
        try:
            if pd.isna(n) or n == "":
                return ""
            if n >= 1_000_000:
                return f"{n/1_000_000:.1f}M"
            elif n >= 1_000:
                return f"{n/1_000:.1f}K"
            else:
                return str(int(n))
        except:
            return str(n)

    # App title
    st.markdown("### 热门话题数据", unsafe_allow_html=True)

    # === Connect to SQLite DB ===
    db_path = os.environ.get("TIKTOK_DB_PATH", str(Path(__file__).resolve().parent / "output" / "tiktok-local.db"))
    conn = sqlite3.connect(db_path)

    # Get min and max date from database
    minmax_query = "SELECT MIN(crawl_date) as min_date, MAX(crawl_date) as max_date FROM hashtags"
    minmax_df = pd.read_sql(minmax_query, conn)

    if minmax_df.empty or minmax_df["min_date"].iloc[0] is None:
        st.warning("暂无话题数据，请先完成话题采集。")
        conn.close()
        return

    min_date = datetime.datetime.strptime(minmax_df["min_date"].iloc[0], "%Y-%m-%d").date()
    max_date = datetime.datetime.strptime(minmax_df["max_date"].iloc[0], "%Y-%m-%d").date()

    # === Select one crawl_date ===
    query_dates = "SELECT DISTINCT crawl_date FROM hashtags ORDER BY crawl_date"
    dates_df = pd.read_sql(query_dates, conn)
    available_dates = [datetime.datetime.strptime(d, "%Y-%m-%d").date() for d in dates_df["crawl_date"].tolist()]

    selected_date = st.date_input(
        "选择采集日期",
        min_value=min(available_dates),
        max_value=max(available_dates),
        value=max(available_dates),
        key="hashtags_date"
    )

    # Query hashtags for selected date
    query = f"SELECT * FROM hashtags WHERE crawl_date = '{selected_date}'"
    df = pd.read_sql(query, conn)
    df = df.drop_duplicates(subset=["hashtag_id", "hashtag_name"])

    # Query hashtags for previous day
    prev_date = selected_date - datetime.timedelta(days=1)
    query_prev = f"SELECT * FROM hashtags WHERE crawl_date = '{prev_date}'"
    df_prev = pd.read_sql(query_prev, conn)
    df_prev = df_prev.drop_duplicates(subset=["hashtag_id", "hashtag_name"])
    conn.close()

    if df.empty:
        st.warning("所选日期暂无数据。")
        return

    if "industry_value" not in df.columns:
        df["industry_value"] = ""

    df = df.dropna(subset=["hashtag_name"])
    df['video_views_dis'] = df['video_views'].apply(format_number)
    df['publish_count_dis'] = df['publish_count'].apply(format_number)

    # === KPI Overview without Top Hashtag ===
    st.subheader("数据概览")

    # Current day metrics
    total_views = df['video_views'].sum()
    total_hashtags = df['hashtag_name'].nunique()
    total_posts = df['publish_count'].sum()

    # Previous day metrics
    if not df_prev.empty:
        prev_total_views = df_prev['video_views'].sum()
        prev_total_hashtags = df_prev['hashtag_name'].nunique()
        prev_total_posts = df_prev['publish_count'].sum()
    else:
        prev_total_views = prev_total_hashtags = prev_total_posts = 0

    # Display metrics (without Top Hashtag)
    col1, col2, col3 = st.columns(3)
    col1.metric("话题总播放量", format_number(total_views), delta=format_number(total_views - prev_total_views))
    col2.metric("独立话题数", total_hashtags, delta=total_hashtags - prev_total_hashtags)
    col3.metric("关联视频总数", format_number(total_posts), delta=format_number(total_posts - prev_total_posts))

    # === Top Hashtags by Views ===
    st.subheader("播放量前 20 个话题")
    industries_views = [i for i in df["industry_value"].dropna().unique() if i != ""]
    selected_industry_views = st.selectbox("选择行业（播放量榜）", ["全部"] + industries_views, key="hashtags_views_industry")

    df_views = df.copy()
    if selected_industry_views != "全部":
        df_views = df_views[df_views["industry_value"] == selected_industry_views]

    top20_views = (
        df_views.groupby(["hashtag_name", "industry_value"], dropna=False)["video_views"]
        .sum()
        .sort_values(ascending=False)
        .head(20)
        .reset_index()
    )
    top20_views['video_views_dis'] = top20_views['video_views'].apply(format_number)

    st.data_editor(
        top20_views[["hashtag_name", "industry_value", "video_views", "video_views_dis"]],
        column_config={
            "hashtag_name": st.column_config.TextColumn("话题"),
            "industry_value": st.column_config.TextColumn("行业"),
            "video_views": st.column_config.NumberColumn("播放量（排序值）", format="%d"),
            "video_views_dis": st.column_config.TextColumn("播放量")
        },
        hide_index=True,
        width="stretch"
    )

    # === Top Hashtags by Post Count ===
    st.subheader("视频数量前 20 个话题")
    industries_posts = [i for i in df["industry_value"].dropna().unique() if i != ""]
    selected_industry_posts = st.selectbox("选择行业（视频数量榜）", ["全部"] + industries_posts, key="hashtags_posts_industry")

    df_posts = df.copy()
    if selected_industry_posts != "全部":
        df_posts = df_posts[df_posts["industry_value"] == selected_industry_posts]

    top20_posts = (
        df_posts.groupby(["hashtag_name", "industry_value"], dropna=False)["publish_count"]
        .sum()
        .sort_values(ascending=False)
        .head(20)
        .reset_index()
    )
    top20_posts['publish_count_dis'] = top20_posts['publish_count'].apply(format_number)

    st.data_editor(
        top20_posts[["hashtag_name", "industry_value", "publish_count", "publish_count_dis"]],
        column_config={
            "hashtag_name": st.column_config.TextColumn("话题"),
            "industry_value": st.column_config.TextColumn("行业"),
            "publish_count": st.column_config.NumberColumn("视频数量（排序值）", format="%d"),
            "publish_count_dis": st.column_config.TextColumn("热门视频")
        },
        hide_index=True,
        width="stretch"
    )

    # === Full Dataset Display ===
    st.subheader("本地数据库明细")
    industries_all = [i for i in df["industry_value"].dropna().unique() if i != ""]
    selected_industry_all = st.selectbox("选择行业（全部数据）", ["全部"] + industries_all, key="hashtags_all_industry")

    df_all = df.copy()
    if selected_industry_all != "全部":
        df_all = df_all[df_all["industry_value"] == selected_industry_all]

    df_all.insert(0, "序号", range(1, len(df_all) + 1))
    df_all["hashtag_id"] = df_all["hashtag_id"].astype(str)

    st.data_editor(
        df_all,
        column_config={
            "序号": st.column_config.NumberColumn("序号", format="%d"),
            "hashtag_id": st.column_config.TextColumn("话题编号"),
            "hashtag_name": st.column_config.TextColumn("话题名称"),
            "country": st.column_config.TextColumn("国家"),
            "rank": st.column_config.NumberColumn("排名", format="%d"),
            "video_views": st.column_config.NumberColumn("视频播放量（原始值）", format="%d"),
            "video_views_dis": st.column_config.TextColumn("视频播放量"),
            "publish_count": st.column_config.NumberColumn("发布数量（原始值）", format="%d"),
            "publish_count_dis": st.column_config.TextColumn("发布数量"),
            "industry_value": st.column_config.TextColumn("行业"),
        },
        hide_index=True,
        width="stretch"
    )
