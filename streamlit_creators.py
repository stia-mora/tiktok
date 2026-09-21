from ui_zh import translate_genres
import os
from pathlib import Path
import streamlit as st
import pandas as pd
import sqlite3
import datetime

def show_creators():
    # Helper function to format numbers (K, M)
    def format_number(n):
        try:
            if pd.isna(n):
                return "0"
            if n >= 1_000_000:
                return f"{n/1_000_000:.1f}M"
            elif n >= 1_000:
                return f"{n/1_000:.1f}K"
            else:
                return str(int(n))
        except:
            return str(n)

    # App title
    st.markdown("### 创作者数据", unsafe_allow_html=True)

    # === Connect to SQLite DB and get available date range ===
    db_path = os.environ.get("TIKTOK_DB_PATH", str(Path(__file__).resolve().parent / "output" / "tiktok-local.db"))
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT MIN(crawl_date), MAX(crawl_date) FROM creators")
    min_date, max_date = cursor.fetchone()
    conn.close()

    if not min_date or not max_date:
        st.warning("暂无创作者数据。")
        return

    # === Date selection based on DB values ===
    selected_date = st.date_input(
        "选择采集日期",
        min_value=pd.to_datetime(min_date).date(),
        max_value=pd.to_datetime(max_date).date(),
        value=pd.to_datetime(max_date).date(),
        key="creators_date"
    )

    # === Query creators table for selected date ===
    conn = sqlite3.connect(db_path)
    query = f"""
    SELECT * FROM creators
    WHERE crawl_date = '{selected_date}'
    """
    df = pd.read_sql(query, conn)

    df = df.drop_duplicates(subset=["user_id", "video_item_id"], keep="first")

    # === Query creators table for previous day ===
    prev_date = pd.to_datetime(selected_date) - pd.Timedelta(days=1)
    query_prev = f"""
    SELECT * FROM creators
    WHERE crawl_date = '{prev_date.date()}'
    """
    df_prev = pd.read_sql(query_prev, conn)
    conn.close()

    df_prev = df_prev.drop_duplicates(subset=["user_id", "video_item_id"], keep="first")

    if df.empty:
        st.warning("所选日期暂无数据。")
        return

    # Verify required columns exist
    required_cols = {
        "nickname", "user_id", "follower_count",
        "creator_rank", "video_item_id",
        "video_play_count", "video_like_count"
    }
    if not required_cols.issubset(df.columns):
        st.error(f"数据库缺少必要字段： {', '.join(required_cols)}")
        return

    df = translate_genres(df)
    df_prev = translate_genres(df_prev)

    # Preprocess columns for display
    df["play_display"] = df["video_play_count"].apply(format_number)
    df["like_display"] = df["video_like_count"].apply(format_number)
    df["follower_display"] = df["follower_count"].apply(format_number)

    # ============ KPI Overview ============
    st.subheader("数据概览")

    # Current metrics
    total_creators = df["user_id"].nunique()
    total_followers = df.groupby("user_id")["follower_count"].max().sum()
    total_videos = df["video_item_id"].nunique()
    total_views = df["video_play_count"].sum()
    total_likes = df["video_like_count"].sum()
    avg_engagement = (df["video_like_count"] / df["video_play_count"]).mean()

    # Previous day metrics (if available)
    if not df_prev.empty:
        prev_total_creators = df_prev["user_id"].nunique()
        prev_total_followers = df_prev.groupby("user_id")["follower_count"].max().sum()
        prev_total_videos = df_prev["video_item_id"].nunique()
        prev_total_views = df_prev["video_play_count"].sum()
        prev_total_likes = df_prev["video_like_count"].sum()
        prev_avg_engagement = (df_prev["video_like_count"] / df_prev["video_play_count"]).mean()
    else:
        prev_total_creators = prev_total_followers = prev_total_videos = prev_total_views = prev_total_likes = prev_avg_engagement = 0

    # Top creator and video (display name only, delta only compares values)
    top_creator = (
        df.groupby(["user_id","nickname"])["follower_count"]
        .max().sort_values(ascending=False)
        .reset_index().iloc[0]
    )
    top_creator_name = top_creator["nickname"]
    top_creator_followers = top_creator["follower_count"]
    top_creator_followers_display = format_number(top_creator_followers)

    # Previous day's top creator followers value
    if not df_prev.empty:
        prev_top_creator_followers = df_prev.groupby(["user_id"])["follower_count"].max().max()
    else:
        prev_top_creator_followers = 0

    top_video = (
        df.groupby(["video_item_id","nickname"])["video_play_count"]
        .max().sort_values(ascending=False)
        .reset_index().iloc[0]
    )
    top_video_creator = top_video["nickname"]
    top_video_views = top_video["video_play_count"]
    top_video_views_display = format_number(top_video_views)

    # Previous day's top video views value
    if not df_prev.empty:
        prev_top_video_views = df_prev.groupby(["video_item_id"])["video_play_count"].max().max()
    else:
        prev_top_video_views = 0

    # Display KPI metrics (delta only for numeric values)
    kpi1, kpi2, kpi3 = st.columns(3)
    kpi1.metric("粉丝最多的创作者", top_creator_name, delta=format_number(top_creator_followers - prev_top_creator_followers))
    kpi2.metric("播放最多的视频作者", top_video_creator, delta=format_number(top_video_views - prev_top_video_views))
    kpi3.metric("独立创作者数", total_creators, delta=total_creators - prev_total_creators)

    kpi4, kpi5, kpi6, kpi7 = st.columns(4)
    kpi4.metric("视频总数", total_videos, delta=total_videos - prev_total_videos)
    kpi5.metric("总播放量", format_number(total_views), delta=format_number(total_views - prev_total_views))
    kpi6.metric("总点赞量", format_number(total_likes), delta=format_number(total_likes - prev_total_likes))
    kpi7.metric("平均点赞播放比", f"{avg_engagement:.2%}", delta=f"{(avg_engagement - prev_avg_engagement):.2%}")

    # ============ Top Creators ============
    st.subheader("粉丝数前 20 位创作者")
    top_creators = (
        df.groupby(["user_id","nickname","profile_url"])["follower_count"]
        .max().sort_values(ascending=False).head(20).reset_index()
    )
    top_creators["follower_display"] = top_creators["follower_count"].apply(format_number)

    st.data_editor(
        top_creators[["nickname","profile_url","follower_count","follower_display"]],
        column_config={
            "nickname": st.column_config.TextColumn("创作者名称"),
            "profile_url": st.column_config.LinkColumn("创作者主页"),
            "follower_count": st.column_config.NumberColumn("粉丝数（排序值）", format="%d"),
            "follower_display": st.column_config.TextColumn("粉丝数"),
        },
        hide_index=True
    )

    # ============ Top Videos ============
    st.subheader("播放量前 20 条视频")
    if "video_url" in df.columns:
        top_videos = (
            df.groupby(["video_item_id","video_url","nickname"])[["video_play_count","video_like_count"]]
            .max().sort_values("video_play_count",ascending=False).head(20).reset_index()
        )
        top_videos["play_display"] = top_videos["video_play_count"].apply(format_number)
        top_videos["like_display"] = top_videos["video_like_count"].apply(format_number)

        st.data_editor(
            top_videos[["video_url","nickname","video_play_count","play_display","video_like_count","like_display"]],
            column_config={
                "video_url": st.column_config.LinkColumn("视频链接"),
                "nickname": st.column_config.TextColumn("创作者"),
                "video_play_count": st.column_config.NumberColumn("播放量（排序值）", format="%d"),
                "play_display": st.column_config.TextColumn("播放量"),
                "video_like_count": st.column_config.NumberColumn("点赞量（排序值）", format="%d"),
                "like_display": st.column_config.TextColumn("点赞量"),
            },
            hide_index=True
        )
    else:
        st.warning("数据库缺少视频链接字段。")

    # ============ Filter by Category ============
    if "video_type" in df.columns:
        st.subheader("分类热门视频（前 20 条）")
        categories = ["全部"] + df["video_type"].dropna().unique().tolist()
        selected_cat = st.selectbox("选择视频分类", categories)
        filtered_df = df if selected_cat=="全部" else df[df["video_type"]==selected_cat]

        top_cat_videos = filtered_df.sort_values("video_play_count",ascending=False).head(20).reset_index(drop=True)
        top_cat_videos["play_display"] = top_cat_videos["video_play_count"].apply(format_number)
        top_cat_videos["like_display"] = top_cat_videos["video_like_count"].apply(format_number)

        show_cols = ["video_type","nickname","video_play_count","play_display","video_like_count","like_display"]
        if "video_url" in top_cat_videos.columns:
            show_cols.insert(1,"video_url")

        st.data_editor(
            top_cat_videos[show_cols],
            column_config={
                "video_url": st.column_config.LinkColumn("视频链接") if "video_url" in show_cols else None,
                "video_type": st.column_config.TextColumn("分类"),
                "nickname": st.column_config.TextColumn("创作者"),
                "video_play_count": st.column_config.NumberColumn("播放量（排序值）", format="%d"),
                "play_display": st.column_config.TextColumn("播放量"),
                "video_like_count": st.column_config.NumberColumn("点赞量（排序值）", format="%d"),
                "like_display": st.column_config.TextColumn("点赞量"),
            },
            hide_index=True
        )

    # ============ Display All Data ============
    st.subheader("本地数据库明细")
    df_all = df.copy()
    df_all.insert(0,"序号",range(1,len(df_all)+1))
    df_all["user_id_str"] = df_all["user_id"].astype(str)
    df_all["video_item_id_str"] = df_all["video_item_id"].astype(str)

    # Filters
    col1,col2,col3,col4 = st.columns(4)
    creators = df_all["nickname"].dropna().unique().tolist()
    selected_creator = col1.selectbox("创作者名称", ["全部"]+creators)
    video_types = df_all["video_type"].dropna().unique().tolist() if "video_type" in df_all.columns else []
    selected_video_type = col2.selectbox("视频类别", ["全部"]+video_types)
    creator_ranks = df_all["creator_rank"].dropna().unique().tolist() if "creator_rank" in df_all.columns else []
    selected_creator_rank = col3.selectbox("创作者排名", ["全部"]+sorted(creator_ranks))
    video_ranks = df_all["video_rank"].dropna().unique().tolist() if "video_rank" in df_all.columns else []
    selected_video_rank = col4.selectbox("视频排名", ["全部"]+sorted(video_ranks))

    if selected_creator!="全部":
        df_all = df_all[df_all["nickname"]==selected_creator]
    if selected_video_type!="全部":
        df_all = df_all[df_all["video_type"]==selected_video_type]
    if selected_creator_rank!="全部":
        df_all = df_all[df_all["creator_rank"]==selected_creator_rank]
    if selected_video_rank!="全部":
        df_all = df_all[df_all["video_rank"]==selected_video_rank]

    columns_to_show = [
        "序号","nickname","uniqueId","user_id_str","follower_count","bio",
        "creator_rank","video_type","video_item_id_str","video_name",
        "video_url","profile_url","video_play_count","video_like_count","video_rank"
    ]

    st.data_editor(
        df_all[columns_to_show],
        column_config={
            "序号": st.column_config.NumberColumn("序号", format="%d"),
            "nickname": st.column_config.TextColumn("创作者名称"),
            "uniqueId": st.column_config.TextColumn("账号名称"),
            "user_id_str": st.column_config.TextColumn("用户编号"),
            "follower_count": st.column_config.NumberColumn("粉丝数", format="%d"),
            "bio": st.column_config.TextColumn("简介"),
            "creator_rank": st.column_config.NumberColumn("创作者排名", format="%d"),
            "video_type": st.column_config.TextColumn("视频类别"),
            "video_item_id_str": st.column_config.TextColumn("视频编号"),
            "video_name": st.column_config.TextColumn("视频名称"),
            "video_url": st.column_config.LinkColumn("视频链接"),
            "profile_url": st.column_config.LinkColumn("主页链接"),
            "video_play_count": st.column_config.NumberColumn("视频播放量", format="%d"),
            "video_like_count": st.column_config.NumberColumn("视频点赞量", format="%d"),
            "video_rank": st.column_config.NumberColumn("视频排名", format="%d"),
        },
        hide_index=True,
        width="stretch",
        key="all_creators_data"
    )
