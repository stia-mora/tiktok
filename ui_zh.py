COUNTRY_NAMES = {
    "AR": "阿根廷", "AU": "澳大利亚", "BR": "巴西", "CA": "加拿大", "CO": "哥伦比亚",
    "FR": "法国", "DE": "德国", "ID": "印度尼西亚", "IT": "意大利", "JP": "日本",
    "MY": "马来西亚", "MX": "墨西哥", "NL": "荷兰", "PK": "巴基斯坦", "PH": "菲律宾",
    "RO": "罗马尼亚", "SA": "沙特阿拉伯", "SG": "新加坡", "ZA": "南非", "KR": "韩国",
    "ES": "西班牙", "SE": "瑞典", "TH": "泰国", "TR": "土耳其", "AE": "阿联酋",
    "GB": "英国", "US": "美国", "VN": "越南",
}
STATUS_NAMES = {"ok": "成功", "partial": "部分完成", "failed": "失败", "empty": "无数据", "running": "采集中"}
STOP_NAMES = {"end_of_results": "已到接口末页", "page_limit": "达到设置页数", "safety_limit": "达到安全页数上限", "repeated_page": "接口重复返回同一页", "request_failed": "接口请求失败", "running": "进行中", "interrupted": "采集中断"}
GENRES = {"Entertainment": "娱乐", "Beauty_Style": "美妆穿搭", "Performance": "表演", "Sport & Outdoor": "运动户外", "Society": "社会", "Lifestyle": "生活方式", "Auto_Vehicle": "汽车", "Talents": "才艺", "Nature": "自然", "Culture_Education_Technology": "文化教育科技", "Supernatural_Horror": "悬疑惊悚"}


def country_name(code):
    return COUNTRY_NAMES.get(code, code)


def translate_genres(frame):
    for column in ("genre", "video_type"):
        if column in frame:
            frame[column] = frame[column].replace(GENRES)
    return frame
