# 今天吃得怎么样 · AI 饮食观察日记

> 网技部 10 天 AI 全栈项目 · 选题 08 · 当前版本 **v0.3**
> 一本“会看照片”的饮食日记：拍照识别菜品和饮食标签 → 人工确认 → 保存 → 时间线 / 图表 → 自然语言查询 → 阶段总结。
> 它不假装是医生，也不追求精确卡路里，只帮你看清最近到底吃了什么。

## 功能一览

| 模块 | 说明 | AI 参与 | 兜底 / 边界 |
|---|---|---|---|
| 记录一餐 | 拍照识别菜品 / 分类 / 份量 / 标签 / **估算热量**，可修改后保存；**扫条形码**一键添加包装食品 | 多模态模型输出结构化 JSON（含粗略 kcal） | Pydantic 校验 → 重试 → 手动填写；热量：模型 → 本地菜品表 → 手改；条形码走 Open Food Facts + 本地缓存 + 手动补录 |
| 饮食时间线 | 按日期浏览、筛选、编辑、删除；查看 AI 原始返回；单餐分享卡片 | — | — |
| 统计图表 | 周 / 月餐次、分类占比、关注标签趋势、环比、常吃菜品 | 无（程序计算） | — |
| 自然语言查询 | “这周喝过几次含糖饮料” | 模型只生成受限查询计划，程序执行 SQL，模型解释 | 白名单校验；不支持的问题拒答 |
| 阶段总结 | 周报 / 月报 + 分享卡片 | 程序先算事实，模型据事实写 | 正则核对数字来源 |
| 健康档案 | 人群预设（学生 / 上班族 / 宝妈 / 长辈 / 健身 / 控重）、身高体重年龄性别、疾病用药过敏、BMI 与能量粗估、中医体质自测 | 无（程序计算 + 关键词注意事项） | 明确“非医疗建议，遵医嘱” |
| 个性化餐单 | 结合档案、记忆与近期记录生成 1–7 天餐单；逐餐“换一换”；手动改菜与时间；购物清单；**到就餐时间播放提醒音效**（预设 / 自传音频，可提前提醒） | 模型生成，双视角说明（现代营养 + 中医体质） | 过敏原自动剔除、禁止卡路里/用药建议、注意事项由程序生成；结构完整性校验 + 同用户生成互斥 |
| AI 记忆 | 从记录 / 备注 / 档案中抽取偏好、习惯、健康、目标，注入到解释、周报、餐单提示词；可编辑关闭删除 | 模型抽取 | 去重、上限 100 条、不存敏感信息 |
| 通知推送 | 邮件 / 企业微信 / QQ 机器人 / Server酱 / PushPlus / 腾讯云短信 / **App 系统通知**；每日提醒、每日小结、周报定时、就餐提醒；消息中心可进详情，AI 内容按 Markdown 渲染 | 周报由模型撰写 | 发送日志 |
| 数据与集成 | JSON / CSV / ZIP（含图片）导入导出；个人访问令牌；**MCP 服务器**；App 收件箱与设备 | — | 导入去重、replace 需二次确认 |
| 用户与权限 | 开放注册（可关）+ **注册审核**（默认开启，管理员通过/拒绝，收件箱通知）；管理员创建 / 停用 / 重置用户；普通用户不能改模型 API；每人数据完全隔离 | — | — |
| 账户安全 | 密码登录、TOTP 两步验证、备用码、会话管理、登录限速 | — | — |
| 外观 | 浅色 / 深色 / 跟随系统、主题色、紧凑模式；移动端适配 | — | — |
| Android App | WebView 薄壳：加载服务器地址，系统栏通知（轮询收件箱，无需 FCM），ZXing 扫码，原生分享；**功能更新全部在服务器端** | — | GitHub Actions 自动出 APK |

模型供应商（统一 OpenAI 兼容协议）：OpenAI、阿里云通义千问、智谱 GLM、硅基流动、DeepSeek（文本）、Moonshot、Ollama、自定义 base_url；`mock` 离线模式无需密钥即可完整演示。

## 技术栈与目录

- 前端：React 18 + Vite + TypeScript + Ant Design 5 + ECharts + @zxing/browser
- 后端：FastAPI + SQLAlchemy 2 + Pydantic v2 + Pillow + openai SDK + pyotp（MCP 服务器为纯 JSON-RPC 实现，无额外依赖）
- 数据库：SQLite（`backend/data/diet.db`，旧版本自动迁移），图片存 `backend/uploads/`
- 部署：Caddy 反向代理 + Let's Encrypt IP 证书自动申请续期 + systemd
- 移动端：Kotlin WebView 壳（`android/`），GitHub Actions 构建

```
diet-diary/
├── backend/app/
│   ├── main.py  config.py  db.py(迁移)  models.py  schemas.py  deps.py(登录/令牌/管理员)
│   ├── routers/  auth users tokens meals misc(stats/query/reports) settings notify(含收件箱/设备)
│   │             health(档案/体质/餐单) memory data(导入导出) barcode share mcp_server
│   └── services/ auth llm_client mock_llm vision stats nl_query report tags timeutil
│                 notify notify_channels profile meal_plan memory exporter barcode share
├── backend/tests/            pytest（167 个用例）
├── frontend/src/             pages: Upload Timeline Stats Query Reports Health Memory Notify Integrations AdminUsers Settings Login
├── android/                  Android 壳应用（README.md / BRIDGE.md）
├── .github/workflows/android.yml   自动构建 APK
├── deploy/                   install.sh · Caddyfile 模板 · systemd
├── docs/AI_LOG.md            AI 协作与出错记录（答辩素材，11 个案例）
└── start.sh                  本地一键启动
```

## 一、本地运行（WSL）

```bash
sudo apt install -y python3 python3-venv python3-pip curl git
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - && sudo apt install -y nodejs
bash start.sh --seed      # 首次：venv、依赖、14 天演示数据、前后端
bash start.sh             # 之后
```
前端 http://localhost:5173 ，后端 http://localhost:8000 （接口文档 /docs）。
**首次启动自动创建管理员** `admin`，密码打印在终端并保存在 `backend/data/initial_password.txt`（或在 `.env` 预设 `ADMIN_USERNAME` / `ADMIN_PASSWORD`）。

## 二、配置（backend/.env）

| 项 | 说明 |
|---|---|
| `LLM_PROVIDER` / `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_TEXT_MODEL` / `LLM_FAST_MODEL` / `LLM_VISION_MODEL` | 也可在网页「模型设置」填写（仅管理员），设置页优先；密钥只存后端。**快速模型**用于查询规划、结果解释、记忆抽取、分享文案、餐单"换一换"等短任务；**文字模型**用于周报、餐单生成（质量优先）；每类任务设有输出长度上限以缩短等待 |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | 首次启动的管理员 |
| `ENABLE_SCHEDULER` | 通知定时任务开关 |
| `TIMEZONE` | 默认 Asia/Shanghai |

## 三、用户与权限

- **注册**：默认开放自主注册（登录页「注册新账号」，同一 IP 每小时最多 5 个）；管理员可在「用户管理」顶部关闭注册。**注册审核**默认开启：新账号需管理员在「用户管理」点「通过」后才能登录（「拒绝」即删除），有人注册时管理员收件箱会收到通知；不需要审核可关闭「新注册账号需管理员审核」。管理员也可以手动创建账号（用户名、初始密码、角色），并可停用、重置密码、重置两步验证、删除（级联删除其全部数据）。
- 角色：`admin` 可管理用户与模型 API；`user` 只能看到自己的数据，模型设置只读。
- 每个用户的餐食、报告、查询、通知配置、档案、餐单、记忆、令牌互相隔离；管理员也看不到他人数据。
- v0.2 升级：启动时自动补列，旧数据归到第一个管理员，旧的全局通知配置迁移为其个人配置。

## 四、安全（公网部署必读）

1. 所有 `/api/*`、`/uploads/*`、`/mcp` 需登录或令牌；会话为 HttpOnly Cookie（HTTPS 自动 Secure）。
2. 「模型设置 → 账户与安全」开启 TOTP 两步验证并保存备用码；改密码会让其他设备下线。
3. 同一 IP + 用户名 5 次失败锁定 60 秒。
4. 安全组只放行 80 / 443；不要暴露 8000 / 5173。
5. 个人访问令牌（`ddt_…`）明文只显示一次，可随时撤销。

## 四点五、带宽很小时的加载优化（已内置）

- 前端按路由与依赖库拆包（react / antd / echarts / zxing 分块），首屏只加载必要代码；图表、扫码库按需加载。
- 构建产物文件名带内容哈希，服务端返回 `Cache-Control: immutable`（一年），刷新时不再重复下载；`index.html` 走 `no-cache` 保证更新可见。
- 所有 API / JS / CSS 经 gzip 压缩（Caddy 前置时还会再压一层 zstd）。
- 上传图片自动生成 320px 缩略图，时间线列表只加载缩略图，详情才加载原图；图片缓存 7 天。
- 如果仍然慢，优先检查：服务器带宽（云主机按 1–5 Mbps 计费的上行是瓶颈，可考虑把 `frontend/dist/assets` 放到对象存储/CDN）、Caddy 是否启用了 `encode zstd gzip`。

## 四点八、Windows Server + 宝塔面板部署

见 `windows/安装说明-宝塔Windows.md`：宝塔「Python 项目管理器」运行后端（`python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`），Nginx 站点反向代理 + Let's Encrypt 证书；包内自带已构建前端，服务器无需 Node.js。`windows/` 目录另有 `install-windows.bat`、`start-windows.bat`、NSSM 服务脚本与 Nginx 配置片段。

## 五、部署到服务器（HTTPS · 公网 IP 自动证书）

```bash
git clone <你的仓库> diet-diary && cd diet-diary
sudo bash deploy/install.sh                 # 自动检测公网 IP，安装 Caddy，申请 Let's Encrypt IP 短期证书（6 天自动续期）
sudo bash deploy/install.sh --self-signed   # 无法放行 80 端口时
```
更新：`git pull && (cd frontend && npm run build) && sudo systemctl restart diet-diary`（App 无需更新）。
日志：`journalctl -u diet-diary -f`；证书：`journalctl -u caddy -n 50 | grep -iE 'cert|obtain|error'`。

## 六、Android App

- 源码在 `android/`，是加载服务器网址的 WebView 壳；**所有功能与更新都在服务器**，App 基本不需要重装。
- **获取 APK**：仓库推到 GitHub 后 Actions 自动构建（也可手动 Run workflow），在 Artifacts 里下载 `diet-diary-apks`；本地构建见 `android/README.md`（JDK 17 + Android SDK 34：`cd android && gradle assembleRelease`，已实际编译验证，release APK 约 2.4 MB，当前版本 1.3.1）。
- release 包默认使用 debug 签名（无需配置即可安装）；要用自己的密钥，在 GitHub Secrets 设置 `KEYSTORE_BASE64 / KEYSTORE_PASSWORD / KEY_ALIAS / KEY_PASSWORD`。
- 首次打开填写服务器地址 → 测试连接 → 登录。自签名证书会弹出确认。
- **服务器地址预填** `https://diet-diary.720172.xyz`，首次打开可直接进入，也可改成自己的地址。
- **拍照不丢**：App 内拍照/选图由原生完成并直接上传到服务器，网页草稿保存在本地；即使拍照期间 App 被系统回收，回来后照片与识别结果自动恢复；解锁/切回不再整页刷新。
- **后台通知**：首次登录后会引导「忽略电池优化」；菜单也有「后台运行设置」。未读消息在桌面图标显示角标（需启动器支持），应用内右上角铃铛与「我的」页显示未读数。
- **系统栏通知**：默认开启「实时通知」前台服务，对收件箱做长轮询，新消息数秒内弹出横幅（会有一条可静音的常驻提示“正在监听通知”）；另有 WorkManager 每 15 分钟兜底轮询；开机自动恢复。App 菜单可切换实时通知开关；国产 ROM 请允许自启动与后台运行、关闭电池优化。
- **AI 用量与余额**：「模型设置」页显示今日/本月调用次数、tokens、估算费用（管理员可设单价）、按任务/按用户分布；DeepSeek / 硅基流动 / Moonshot 支持一键查余额，其他供应商给出控制台链接。
- **就餐提醒音效（1.3.0）**：收到 `meal_alert` 类通知时，App 在后台也会播放用户在网页里选择的音效并震动；旧版 App 仅在网页处于前台时由页面播放。1.3.1 修复 App 内上传音效文件选择器只能选图片的问题。
- 扫码、分享由 App 提供原生能力（`window.DietDiaryNative`，见 `android/BRIDGE.md`）；网页版则用浏览器摄像头扫码（需 HTTPS）。

## 七、MCP 接入（让 Claude Desktop 等 Agent 直接操作日记）

1. 「数据与集成 → 访问令牌」创建令牌（scope `mcp`）。
2. 端点 `https://你的IP/mcp`（Streamable HTTP，`Authorization: Bearer ddt_…`）。
3. Claude Desktop 示例（`claude_desktop_config.json`，需 Node）：
   ```json
   {"mcpServers": {"diet-diary": {"command": "npx", "args": ["-y", "mcp-remote", "https://你的IP/mcp", "--header", "Authorization:${DIET_TOKEN}"], "env": {"DIET_TOKEN": "Bearer ddt_你的令牌"}}}}
   ```
4. 工具：`log_meal` 记一餐、`list_meals`、`get_stats`、`ask_diet_question`、`generate_report`、`get_today_summary`、`list_tags`。「数据与集成 → MCP 接入」页有可复制的配置。

## 八、通知渠道

| 渠道 | 需要什么 |
|---|---|
| App 通知 | 安装 App 并登录即可（默认启用） |
| 邮件 | SMTP 服务器 / 端口 / 账号 / 授权码 |
| 企业微信群机器人 | Webhook 地址 |
| QQ 机器人 | NapCat / go-cqhttp / LLOneBot 的 HTTP 地址、token、QQ 号或群号 |
| Server酱 / PushPlus | SendKey / Token |
| 腾讯云短信 | SecretId / SecretKey / SdkAppId / 签名 / 模板（变量 {1}=餐数、{2}=含糖饮料次数）/ 手机号 |
| 就餐提醒音效 | 「健康 → 个性化餐单」或「通知推送」页开启；选预设或上传音频（mp3/wav/ogg/m4a ≤3 MB，可重命名），可设提前分钟数、餐次、音量、震动；服务器按当前餐单时间写入收件箱并推送到 App。**管理员**可上传 / 重命名 / 删除系统预设音效，并可隐藏或重命名内置音效 |

## 九、测试

```bash
cd backend && source .venv/bin/activate && pytest -q      # 167 个用例
cd frontend && npm run build                               # 类型检查 + 打包
```
另有 Playwright 无头浏览器冒烟（登录 → 12 个路由 × 浅色/深色 × 桌面/手机，控制台零错误）。

## 十、演示链路（验收）

登录 → 记录一餐（拍照识别 / 扫码）→ 手动修正 → 保存 → 时间线看原始返回 → `sqlite3 backend/data/diet.db` 展示真实数据 → 统计图表 → 自然语言查询（展开查询计划与 SQL）→ 周报 + 分享卡片 → 健康档案 → 体质自测 → 生成餐单并“换一换” → AI 记忆 → 通知测试 → 用户管理 → MCP 用 curl 调一次 `tools/list` → `docs/AI_LOG.md` 讲 AI 出错案例。

## 十一、常见问题

| 问题 | 处理 |
|---|---|
| 忘记管理员密码 | `sqlite3 backend/data/diet.db "delete from auth_sessions; delete from users;"` 后重启，按 `.env` 重建 |
| 普通用户看不到模型设置表单 | 设计如此：模型 API 由管理员统一配置 |
| 记忆一直是 0 条 | 需要保存过几餐或在「AI 记忆」点“重建”；mock 模式按规则抽取（如某菜出现 ≥3 次） |
| 扫码摄像头打不开 | 浏览器要求 HTTPS（或 localhost）；App 内使用原生扫码不受限；也可手动输入条码 |
| 条形码查不到 | Open Food Facts 对国内商品覆盖有限，可手动补录，之后所有人都能复用缓存 |
| 餐单里有“卡路里”数字 | 程序会剔除此类行；如仍出现请反馈，并以“非医疗建议”看待 |
| App 收不到通知 | 检查手机通知权限、后台运行/自启动白名单；在「数据与集成 → App 与通知收件箱」点“发送测试到 App” |
| 证书申请失败 | 放行 80/443，`caddy version` ≥ 2.10.2，服务器时间准确；临时用 `--self-signed` |
| 识别与照片无关 | 当前 mock 模式，管理员到「模型设置」配置真实供应商 |

## 升级

见 `docs/升级指南.md`（Windows 宝塔 / Linux / WSL 三种环境的逐步操作、备份与回滚）。数据库结构在启动时自动迁移。

## 边界与声明

识别与估算可能出错；**热量为按菜品与份量的粗略估算**（模型或本地菜品表），仅用于观察趋势；健康档案、体质自测、餐单、记忆均为**一般性饮食参考**，不构成医疗诊断或用药建议，有疾病或用药请遵医嘱。
