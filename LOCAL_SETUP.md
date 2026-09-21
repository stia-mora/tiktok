# 本地部署与测试

原仓库： https://github.com/jayden856/tiktok ，基于提交 fde08f3。

已在 .venv 中安装 requirements.txt；看板使用 output/tiktok-local.db，未混入仓库自带的历史数据。

## 启动看板

在本目录 PowerShell 执行 `./start-dashboard.ps1`，访问 http://127.0.0.1:8501 。

## 小规模采集

```powershell
.\.venv\Scripts\python.exe smoke_test.py --cookies D:/Edge-Download/ads.tiktok.com_cookies.txt
```

每次只请求一个分类的一页视频、一页创作者及一页话题。视频和创作者使用原项目 Entertainment / Region=All 配置（请求客户端地区为 MY）；话题使用 US / 7 天 / 最多 5 条。

Cookie 使用 Netscape 文件格式，仅运行时按域加载，不复制到仓库。原作者硬编码的 Cookie、身份请求头和签名已去除。

结果写入 output/时间戳/ 下的 JSON、CSV 和 report.json；有数据时追加写入独立 SQLite。仅接口失败时不会生成伪数据，report.json 会记录失败。

2026-09-19 实测：视频 10 条，创作者关联视频 74 条，话题返回业务码 40101 / no permission。不能仅凭该错误认定 Cookie 过期，也可能需要更新接口或请求认证信息。原项目的旧话题接口尚未修复。

看板通过 Streamlit AppTest 运行检查，无异常。此次测试数据不含 Top Ads 广告素材；该项目采集的是热门视频、创作者和话题。

默认请使用 smoke_test.py；原 script.py 的 main 会采集多个分类各 10 页。

## 多国家广告素材（新增）

看板第一个“广告素材”页支持 28 个国家 / 地区多选、品牌关键词、7/30/180 天、分页及排序。列表逐国请求；详情中的 country_code 用于核实广告投放地区。同一广告可能在多国出现，保留各国记录，详情和下载文件按素材 ID 复用。

```powershell
.\.venv\Scripts\python.exe ads_collector.py --cookies D:/Edge-Download/ads.tiktok.com_cookies.txt --countries US JP GB --pages 1 --limit 5 --download-per-country 1
```

关键词示例：追加 `--keyword Nike`。国家代码来自官网当前筛选接口（ads_countries.json）；英国为 GB。`--download-per-country 0` 仅保存素材链接；下载数量最多为每国 20 条。串行请求，每个素材的详情请求间隔至少 0.35 秒。每个视频最大 100 MB，不向媒体 CDN 发送登录 Cookie。

输出目录 output/ads/批次/：合并 ads.csv、ads.json、ads.sqlite3；各国家目录包含独立 CSV/JSON 及原始分页响应；details 保存详情；videos 保存 MP4；report.json 保存各国家成功、空结果和失败状态。CSV 对可能被表格软件作为公式执行的文本加单引号，JSON 保留原始文本。

已补齐官方网页请求使用的动态签名，并使用当前 top_ads/v2/list 与 detail 接口。该签名算法来自官网公开脚本，并不替代账号 Cookie；官网更新时可能需要同步调整。

2026-09-19 实测 US / JP / GB 各 5 条，共 15 条国家记录、10 个独立素材；全部通过详情核实投放地区，下载 3 个 MP4。此前话题接口的 40101 不能单独用来判断 Cookie 无效；旧话题协议本次未重新验证。

国家筛选代表投放市场，不表示创作者国籍或视频语言。这里是 Creative Center 公开展示的 Top Ads，不是平台全部广告。原热门视频 / 创作者脚本仍使用 Region=All，本次多国家功能针对新增广告采集入口。

视频 / 封面链接带有效期；失效时重新采集。品牌和落地页可能为空；CTR、花费字段保留原始值，不推断为绝对金额。单国家失败会记录错误并继续其他国家。

验证：`python -m unittest test_ads_collector.py` 检查多国隔离、分页去重、部分失败、下载域名限制和 CSV 文本处理；看板已用 Streamlit AppTest 验证初始加载与切换国家。

## 持续历史数据库与每日计划（2026-09-19 更新）

上述每批次文件继续保留，新增两个持续 SQLite 库：

- `output/ads_history.sqlite3`：广告素材历史。
- `output/video_history.sqlite3`：热门视频素材历史（包含作者、分类、播放量、点赞量、文案、视频地址和封面地址）。

各库的 `materials` 按素材编号去重，保留首次/最后发现时间；`observations` 按采集批次、国家、素材编号保存观测；`daily_snapshots` 视图按北京时间日期取同国同素材当天最后一次观测。重复导入同批次不增加记录，跨天不覆盖旧指标。已采数据每页入库，中断不丢失此前完成页面。首次发现是本库首次采到，不等于发布时间；指标是素材整体指标，不按国家相加。

界面标题、导航、筛选、国家名、业务状态和表头已汉化；视频原文、品牌、作者名称不做机器翻译。历史数据库支持按来源、日期、国家、文本检索，查看每日独立素材、国家分布、品牌/作者分布和单个素材点赞变化，支持导出全部筛选结果。分析页面不请求采集 API。

每国不是只采 10 条：视频每页 10 条，广告每页最多 20 条（当前本地配置）。`--pages 0` 自动分页直到末页、重复页或请求失败。广告保护上限 1000 页/国家，视频保护上限 100 页/国家/分类；到上限明确标为未完成。广告实测美国 6 页得到 103 个独立素材，部分详情失败，列表已到末页。为减少额外详情请求，日采默认只抓广告列表，已包含文案、品牌、指标、视频和封面链接；界面可选补充详情，连续三次详情失败即暂停详情抓取。

热门视频单独采集示例：

```powershell
.\.venv\Scripts\python.exe video_collector.py --cookies D:/Edge-Download/ads.tiktok.com_cookies.txt --countries US JP GB --pages 2 --genres Entertainment
```

实测美国 20、日本 19、英国 19 条国家记录，共 53 个独立视频。国家按 Creator Studio 请求筛选记录，不代表作者所在地，也不是广告投放认证；不同市场可能返回重复热门内容，未验证的市场不承诺筛选完整性。默认日采遍历 28 个国家及全部 11 个分类，空结果、失败、重复页和页数上限都会记录。

用户已指定全部 28 国、北京时间每天 09:00、只存链接。已在 Codex 创建任务自动化 `tiktok`，每日执行 `daily_collect.py`，同时采集广告和热门视频。配置位于 `daily_config.json`。需本机与 Codex 正常运行、Cookie 有效。计划从下一次 09:00 开始；当前仅执行了小规模功能测试和一次美国广告翻页测试，没有宣称已完成今天全部 28 国。

```powershell
.\.venv\Scripts\python.exe daily_collect.py
```

手动运行同一命令可提前执行。脚本使用文件锁避免同时重复日采；当日同配置重跑会跳过已经完整成功的来源/国家，失败项可以重试。它不会补造错过日期的数据。广告和视频各有独立任务，`output/daily/` 保存每天完成情况。Cookie 内容不会进入配置或日志。

本地历史保留不受官网页面历史窗口影响，但新采集仍受接口可见范围、权限和限流约束。这不是平台所有内容的完整备份。只保存链接不能保证视频永久播放，媒体链接过期时需刷新或另行保存文件。

运行 `python -m unittest test_ads_collector.py test_history.py` 验证分页去重、失败隔离、数据库幂等、北京时间跨日、历史指标保留、视频跨分类去重与日采两来源续跑。


## 项目专用代理

本机 `proxy.local.json` 的 `proxy_url` 设置为 `http://127.0.0.1:7897`，由 Clash Verge 提供。仅本项目采集请求使用，不修改系统代理。每日任务和前端采集自动读取；请保持 Clash 运行。可用 `TIKTOK_PROXY_URL` 覆盖。代理不可用时请求失败，不自动改为直连。国家通过接口国家参数选择，不代表代理出口切换到该国家，也不保证平台开放全部国家数据。
