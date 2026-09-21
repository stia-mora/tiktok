from ui_zh import translate_genres
import os
from pathlib import Path
import streamlit as st
import pandas as pd
import plotly.express as px
import sqlite3
import datetime

def show_posts():
    # Helper function to format numbers (K, M)
    def format_number(n):
        try:
            if pd.isna(n):
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
    st.markdown("### 热门视频数据", unsafe_allow_html=True)

    # === Connect to SQLite DB and get available date range ===
    db_path = os.environ.get("TIKTOK_DB_PATH", str(Path(__file__).resolve().parent / "output" / "tiktok-local.db"))
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT MIN(crawl_date), MAX(crawl_date) FROM posts")
    min_date, max_date = cursor.fetchone()
    conn.close()

    if not min_date or not max_date:
        st.warning("暂无热门视频数据。")
        return

    # === Date selection based on DB values ===
    selected_date = st.date_input(
        "选择采集日期",
        min_value=pd.to_datetime(min_date).date(),
        max_value=pd.to_datetime(max_date).date(),
        value=pd.to_datetime(max_date).date(),
        key="posts_date"
    )

    # === Query posts table for selected date and previous day ===
    conn = sqlite3.connect(db_path)
    df = pd.read_sql(f"SELECT * FROM posts WHERE crawl_date = '{selected_date}'", conn)
    prev_date = pd.to_datetime(selected_date) - pd.Timedelta(days=1)
    df_prev = pd.read_sql(f"SELECT * FROM posts WHERE crawl_date = '{prev_date.date()}'", conn)
    conn.close()

    df = df.drop_duplicates(subset=["item_id", "user_id"], keep="first")
    df_prev = df_prev.drop_duplicates(subset=["item_id", "user_id"], keep="first")

    if df.empty:
        st.warning("所选日期暂无数据。")
        return

    df = translate_genres(df)
    df_prev = translate_genres(df_prev)

    # Format numbers for display
    df['play_count_dis'] = df['play_count'].apply(format_number)
    df['like_count_dis'] = df['like_count'].apply(format_number)

    # === KPI Overview with delta compared to previous day ===
    st.subheader("数据概览")

    # Current metrics
    total_plays = df['play_count'].sum()
    total_likes = df['like_count'].sum()
    total_videos = len(df)
    avg_engagement = (df['like_count'] / df['play_count']).mean()

    # Previous day metrics
    if not df_prev.empty:
        prev_total_plays = df_prev['play_count'].sum()
        prev_total_likes = df_prev['like_count'].sum()
        prev_total_videos = len(df_prev)
        prev_avg_engagement = (df_prev['like_count'] / df_prev['play_count']).mean()
    else:
        prev_total_plays = prev_total_likes = prev_total_videos = prev_avg_engagement = 0

    # === Top Creator ===
    top_creator_row = df.groupby("nickname")["play_count"].sum().sort_values(ascending=False)
    top_creator_name = top_creator_row.index[0]
    top_creator_plays = top_creator_row.iloc[0]

    # Previous day Top Creator plays
    if not df_prev.empty and top_creator_name in df_prev["nickname"].values:
        prev_top_creator_plays = df_prev.groupby("nickname")["play_count"].sum().get(top_creator_name, 0)
    else:
        prev_top_creator_plays = 0

    # === Top Genre ===
    top_genre_row = df.groupby("genre")["play_count"].sum().sort_values(ascending=False)
    top_genre_name = top_genre_row.index[0]
    top_genre_plays = top_genre_row.iloc[0]

    # Previous day Top Genre plays
    if not df_prev.empty and top_genre_name in df_prev["genre"].values:
        prev_top_genre_plays = df_prev.groupby("genre")["play_count"].sum().get(top_genre_name, 0)
    else:
        prev_top_genre_plays = 0

    # Display KPIs
    # First row: Top Creator & Top Genre
    row1_col1, row1_col2, row1_col3 = st.columns(3)
    row1_col1.metric("播放最多的创作者", top_creator_name, delta=format_number(top_creator_plays - prev_top_creator_plays))
    row1_col2.metric("该创作者播放量", format_number(top_creator_plays), delta=format_number(top_creator_plays - prev_top_creator_plays))
    row1_col3.metric("播放最多的分类", top_genre_name, delta=format_number(top_genre_plays - prev_top_genre_plays))

    # Second row: Top Genre Plays & Total Plays & Total Likes
    row2_col1, row2_col2, row2_col3 = st.columns(3)
    row2_col1.metric("该分类播放量", format_number(top_genre_plays), delta=format_number(top_genre_plays - prev_top_genre_plays))
    row2_col2.metric("总播放量", format_number(total_plays), delta=format_number(total_plays - prev_total_plays))
    row2_col3.metric("总点赞量", format_number(total_likes), delta=format_number(total_likes - prev_total_likes))
    # Optional: add more KPIs as needed

    # === Required Columns Check ===
    required_cols = {'genre', 'play_count', 'like_count'}
    if not required_cols.issubset(df.columns):
        st.error("数据库缺少内容分类、播放量或点赞量字段。")
        return

    # === Genre average statistics ===
    genre_avg = df.groupby('genre')[['play_count', 'like_count']].mean().round(0).reset_index()
    genre_avg['play_count_dis'] = genre_avg['play_count'].apply(format_number)
    genre_avg['like_count_dis'] = genre_avg['like_count'].apply(format_number)

    st.subheader("分类平均指标")
    st.data_editor(
        genre_avg[['genre','play_count','play_count_dis','like_count','like_count_dis']],
        column_config={
            "genre": st.column_config.TextColumn("内容分类"),
            "play_count": st.column_config.NumberColumn("平均播放量（排序值）", format="%d"),
            "play_count_dis": st.column_config.TextColumn("平均播放量"),
            "like_count": st.column_config.NumberColumn("平均点赞量（排序值）", format="%d"),
            "like_count_dis": st.column_config.TextColumn("平均点赞量"),
        },
        hide_index=True,
        width="stretch"
    )

    # === Charts & Remaining Sections ===
    # Play count by genre
    st.subheader("各分类平均播放量")
    fig_play = px.bar(
        genre_avg,
        x="genre",
        y="play_count",
        color="genre",
        labels={"genre": "内容分类", "play_count": "平均播放量"},
        color_discrete_sequence=px.colors.qualitative.Set3
    )
    st.plotly_chart(fig_play, width="stretch")

    # Like count by genre
    st.subheader("各分类平均点赞量")
    fig_like = px.bar(
        genre_avg,
        x="genre",
        y="like_count",
        color="genre",
        labels={"genre": "内容分类", "like_count": "平均点赞量"},
        color_discrete_sequence=px.colors.qualitative.Pastel
    )
    st.plotly_chart(fig_like, width="stretch")

    # Engagement Rate
    st.subheader("各分类点赞播放比")
    df["engagement_rate"] = df["like_count"] / df["play_count"]
    genre_engagement = df.groupby("genre")["engagement_rate"].mean().sort_values(ascending=False)
    fig_engagement = px.bar(
        genre_engagement,
        x=genre_engagement.index,
        y=genre_engagement.values,
        color=genre_engagement.index,
        labels={"x": "内容分类", "y": "平均点赞播放比"},
        color_discrete_sequence=px.colors.qualitative.Safe
    )
    fig_engagement.update_yaxes(tickformat=".0%")
    st.plotly_chart(fig_engagement, width="stretch")

    # === Filter Top Videos / Creators ===
    st.subheader("筛选热门视频和创作者")
    col1, col2 = st.columns(2)
    creators = df["nickname"].unique().tolist()
    genres = df["genre"].unique().tolist()
    selected_creator = col1.selectbox("选择创作者", ["全部"] + creators)
    selected_genre = col2.selectbox("选择内容分类", ["全部"] + genres)
    df_filtered = df.copy()
    if selected_creator != "全部":
        df_filtered = df_filtered[df_filtered["nickname"] == selected_creator]
    if selected_genre != "全部":
        df_filtered = df_filtered[df_filtered["genre"] == selected_genre]

    # === Top 20 Videos / Creators Combined Ranking ===
    top20_play = df_filtered.sort_values(by='play_count', ascending=False).head(20)
    top20_like = df_filtered.sort_values(by='like_count', ascending=False).head(20)
    top_videos = pd.concat([top20_play, top20_like]).drop_duplicates().reset_index(drop=True)
    creator_stats = df_filtered.groupby("nickname")[["play_count","like_count"]].sum().reset_index()
    top_videos = top_videos.merge(creator_stats, on="nickname", suffixes=("", "_creator"))

    top_videos["play_count_dis"] = top_videos["play_count"].apply(format_number)
    top_videos["like_count_dis"] = top_videos["like_count"].apply(format_number)
    top_videos["play_count_creator_dis"] = top_videos["play_count_creator"].apply(format_number)
    top_videos["like_count_creator_dis"] = top_videos["like_count_creator"].apply(format_number)

    st.subheader("热门视频与创作者综合榜")
    st.data_editor(
        top_videos[[
            "url","nickname","genre",
            "play_count","play_count_dis","like_count","like_count_dis",
            "play_count_creator","play_count_creator_dis",
            "like_count_creator","like_count_creator_dis"
        ]],
        column_config={
            "url": st.column_config.LinkColumn("视频链接"),
            "nickname": st.column_config.TextColumn("创作者"),
            "genre": st.column_config.TextColumn("内容分类"),
            "play_count": st.column_config.NumberColumn("视频播放量（排序值）", format="%d"),
            "play_count_dis": st.column_config.TextColumn("视频播放量"),
            "like_count": st.column_config.NumberColumn("视频点赞量（排序值）", format="%d"),
            "like_count_dis": st.column_config.TextColumn("视频点赞量"),
            "play_count_creator": st.column_config.NumberColumn("创作者总播放量", format="%d"),
            "play_count_creator_dis": st.column_config.TextColumn("总播放量"),
            "like_count_creator": st.column_config.NumberColumn("创作者总点赞量", format="%d"),
            "like_count_creator_dis": st.column_config.TextColumn("总点赞量"),
        },
        hide_index=True,
        width="stretch"
    )

    # Correlation scatter plot
    st.subheader("视频播放量与点赞量的关系")
    fig_scatter = px.scatter(
        df_filtered,
        x="play_count",
        y="like_count",
        color="genre",
        hover_data=["nickname", "url"],
        labels={"play_count": "视频播放量", "like_count": "视频点赞量"}
    )
    st.plotly_chart(fig_scatter, width="stretch")

    # All Data Table
    st.subheader("本地数据库明细")
    df_display = df.copy()
    df_display.insert(0, "序号", range(1, len(df_display) + 1))
    df_display["user_id_str"] = df_display["user_id"].astype(str)
    df_display["item_id_str"] = df_display["item_id"].astype(str)

    col1, col2 = st.columns(2)
    creators = df_display["nickname"].dropna().unique().tolist()
    selected_creator = col1.selectbox("按创作者筛选", ["全部"] + creators)
    genres = df_display["genre"].dropna().unique().tolist()
    selected_genre = col2.selectbox("按内容分类筛选", ["全部"] + genres)

    df_filtered = df_display.copy()
    if selected_creator != "全部":
        df_filtered = df_filtered[df_filtered["nickname"] == selected_creator]
    if selected_genre != "全部":
        df_filtered = df_filtered[df_filtered["genre"] == selected_genre]

    columns_to_show = ["序号","url","nickname","user_id_str","item_id_str","item_name","genre","like_count","play_count"]
    st.data_editor(
        df_filtered[columns_to_show],
        column_config={
            "序号": st.column_config.NumberColumn("序号", format="%d"),
            "url": st.column_config.LinkColumn("视频链接"),
            "nickname": st.column_config.TextColumn("创作者"),
            "user_id_str": st.column_config.TextColumn("用户编号"),
            "item_id_str": st.column_config.TextColumn("视频编号"),
            "item_name": st.column_config.TextColumn("视频文案"),
            "genre": st.column_config.TextColumn("内容分类"),
            "like_count": st.column_config.NumberColumn("点赞量", format="%d"),
            "play_count": st.column_config.NumberColumn("播放量", format="%d"),
        },
        hide_index=True,
        width="stretch"
    )
