# AI 协作日志（答辩素材）

> 验收要求：说明 AI 帮自己完成了哪些工作、哪些地方 AI 写错或判断错了、自己如何定位和修复。
> 每次让 AI 生成代码 / 识别图片 / 回答查询后，随手在这里记一条。格式随意，重点是“错在哪、怎么发现、怎么修”。

## 一、AI 帮我完成的工作

| 日期 | 事项 | AI 产出 | 我做了什么 |
|---|---|---|---|
| 09-03 | 项目规划 | 需求拆解、技术选型、数据模型、API 设计 | 决定接入国内外多家模型 + 自定义 API；确认用 React + FastAPI + SQLite |
| 09-03 | 后端初版 | FastAPI 路由、SQLAlchemy 模型、视觉识别 / 统计 / 自然语言查询 / 报告服务、pytest | 运行测试、阅读代码、对照题目要求检查 |
| 09-03 | 前端初版 | React + AntD + ECharts 六个页面 | 联调、修改文案与样式 |
| 09-03 | v0.2 安全 | 密码登录、会话、TOTP 两步验证、备用码、限速、受保护静态资源 | 部署到公网服务器后提出需求；核对安全组 |
| 09-03 | v0.2 通知 | 邮件 / 企业微信 / QQ 机器人 / Server酱 / PushPlus / 腾讯云短信 + 定时任务 | 提供各渠道凭据并逐个测试发送 |
| 09-03 | v0.2 部署 | Caddy + Let's Encrypt IP 证书自动申请、systemd、install.sh | 在腾讯云服务器执行并观察证书日志 |
| 09-03 | v0.2 外观 | 深色/浅色/跟随系统、主题色、紧凑模式、移动端适配 | 手机上实际体验并反馈 |

## 二、AI 出错记录（真实案例）

### 案例 1：SQLite 外键级联没有生效 → 测试 5 个失败
- **现象**：`pytest` 报 `IntegrityError: UNIQUE constraint failed: meal_item_tags.item_id, meal_item_tags.tag_code`，以及一个新建记录的标签里莫名多出 `refined_staple`。
- **AI 的错误**：模型表定义里写了 `ondelete="CASCADE"`，就默认级联删除会生效；但 SQLite 默认 **不启用外键约束**，批量 `delete()` 删掉 `meal_items` 后，关联表 `meal_item_tags` 留下孤儿行，新记录复用了旧 id 就撞上了。
- **定位**：单独跑失败用例是通过的，全量跑才失败 → 判断是测试间的数据残留；看报错里的 SQL 参数 `(1, 'refined_staple')`，id=1 是被复用的旧 id。
- **修复**：在 `db.py` 用 `event.listens_for(engine, "connect")` 执行 `PRAGMA foreign_keys=ON`；`seed --reset` 与测试夹具额外显式清空关联表。
- **学到**：ORM 声明的约束 ≠ 数据库真的在执行；SQLite 的外键要手动打开。

### 案例 2：SQLAlchemy `cast` 写法错误
- **现象**：AI 写了 `func.cast(func.strftime("%H", Meal.eaten_at), "INTEGER")`，这不是合法用法。
- **修复**：改为 `cast(func.strftime("%H", Meal.eaten_at), Integer)`，并补了跨夜时间段（22~5 点）的测试 `test_hour_filter_wraps_midnight`。

### 案例 3：FastAPI `on_event("startup")` 已弃用
- **现象**：测试输出 DeprecationWarning。
- **修复**：改用 `lifespan` 上下文管理器。

### 案例 4：前端用 `toISOString()` 提交用餐时间 → 存进数据库差 8 小时
- **现象**：代码审查时发现前端 `eaten_at: eatenAt.toISOString()`。`toISOString()` 会把本地 12:30 转成 UTC `04:30:00Z`，后端按朴素本地时间存储，午餐就变成了凌晨。
- **AI 的错误**：写前端的 AI 默认“ISO 字符串就是标准做法”，没有考虑后端的时区约定；这是典型的前后端约定不一致。
- **定位**：审查 API 调用参数时对照后端 `timeutil.py` 的“统一存本地朴素时间”约定发现的；补了一个用例 `test_eaten_at_timezone_normalized` 复现。
- **修复**：前端改为 `format('YYYY-MM-DDTHH:mm:ss')` 发送本地时间；后端 `MealCreate/MealUpdate` 增加校验器，若收到带时区的时间就换算到 `Asia/Shanghai` 再去掉 tzinfo（双保险）。
- **学到**：时间字段一定要在 API 文档里写清“带不带时区、哪个时区”，并用测试固定下来。

### 案例 5：/stats 与 /reports 整页白屏 —— `l.isoWeek is not a function`
- **现象**：部署到服务器后，统计图表页和阶段总结页打开是空白，其他页面正常。
- **定位**：在无头 Chromium（Playwright）里打开页面抓控制台，报 `TypeError: l.isoWeek is not a function`，堆栈指向 dayjs 的 `format`。原因是 AI 写前端时给周选择器用了 `YYYY-[W]WW` 格式，`WW` 依赖 dayjs 的 `advancedFormat`/`isoWeek` 插件，但没有 `dayjs.extend()` 注册；AntD 自己只注册了它需要的插件。任何一个组件抛错，React 会卸载整棵树，于是整页白屏。
- **AI 的错误**：只在“能编译”层面自检（TypeScript 不会检查 dayjs 格式串），没有在浏览器里真跑一次。
- **修复**：`main.tsx` 注册 `isoWeek / weekOfYear / advancedFormat`；格式改为 `YYYY 年第 w 周`；新增 `ErrorBoundary`，以后单页出错只显示错误提示不再白屏；把 Playwright 页面冒烟纳入验证流程。
- **学到**：类型检查通过 ≠ 运行正确；前端一定要在真实浏览器里跑一遍每个路由并看控制台。

### 案例 6：静态托管 catch-all 存在 `../` 路径穿越风险
- **现象**：写 `test_path_traversal_blocked` 时发现 `/{full_path:path}` 用 `dist / full_path` 直接拼路径，理论上 `GET /../../backend/.env`（客户端不做规范化时）可读到密钥文件。
- **修复**：`resolve()` 后校验目标路径必须位于 dist 目录内；`/uploads/{name}` 只接受单段文件名并需要登录。
- **学到**：凡是“用户输入拼文件路径”的地方都要做 resolve + 前缀校验，并写一个恶意路径的测试。

### 案例 7：`parse_json` 只认对象不认数组 → 记忆抽取“静默失败”
- **现象**：v0.3 联调时「从最近记录重建记忆」扫描了 37 餐却新增 0 条；mock 模型明明返回了 5 条候选。
- **定位**：直接在 Python 里调用 `extract_memories`，返回空列表；再单步看 `parse_json`：早期为视觉识别写的 `strip_json_fence` 假定输出是 `{...}`，遇到 `[...]` 数组会把它截成从第一个 `{` 到最后一个 `}`，变成非法 JSON，异常被“兜底”吞掉了。
- **AI 的错误**：第一版是我（AI）写的，只考虑了当时唯一的用例；后续新功能复用时没有人重新审视这个假设。兜底 `except` 过于宽泛，把真正的 bug 也吞了。
- **修复**：`strip_json_fence` 同时支持对象与数组；新增 `test_parse_json_arrays_and_wrapped_text`；重建接口改为一次汇总调用而不是逐餐重复调用。
- **学到**：公共工具函数要为“别人怎么用”写测试；捕获异常时至少要留日志，否则错误会被兜底掩盖。

### 案例 8：条形码把可口可乐标成“酒精”
- **现象**：扫 6928804011142（可口可乐）返回标签 `['sugary_drink', 'alcohol']`。
- **定位**：Open Food Facts 的分类标签里有 `en:non-alcoholic-beverages`，子串包含 "alcohol"，关键词匹配误命中；另外 AI 把“能量饮料”也错映射成了 alcohol（把需求里“energy-drink/alcohol 分类”理解成了同一类）。
- **修复**：匹配前先剔除 non-alcoholic / alcohol-free；能量饮料改为含糖饮料；测试全部通过。
- **学到**：关键词匹配要先处理否定词；对外部数据源的字段要用真实样本验证一次。

### 案例 9：子代理因 API 过载中断
- **现象**：负责 Android 壳应用的子代理写到一半（Kotlin 源码尚未生成）因 HTTP 529 Overloaded 终止。
- **处理**：检查磁盘上已生成的文件清单，用新的子代理“接着写”，并要求它先通读已有文件保持一致（类名、布局 id、字符串资源双语同步），最后做 R.id / strings / manifest 交叉核对。
- **学到**：长任务要能从中间状态恢复；给接手者明确“已有什么、还缺什么”比重来一遍更省。

### 案例 10：Android 项目首次 CI 构建失败（AI 漏写 gradle.properties）
- **现象**：GitHub Actions 报 `android.useAndroidX property is not enabled`，`:app:dataBindingMergeDependencyArtifactsDebug FAILED`。
- **原因**：AI 生成的 Gradle 工程漏了 `gradle.properties`（`android.useAndroidX=true` 是 AndroidX 工程的必需项）。沙箱没有 JDK/Android SDK，无法本地编译，只能靠人工审查。
- **借机复查全部 Kotlin 源码，又发现 4 个只有编译/运行时才会暴露的问题**：
  1. `InboxWorker` 把服务端返回当作 JSON 数组解析，但接口实际返回 `{"messages": [...]}` 对象 → 收件箱永远为空；
  2. `build.gradle.kts` 里局部变量 `keyAlias` 与 signingConfig 属性同名，`keyAlias = keyAlias` 在 Kotlin 里会解析成给只读局部变量赋值 → 编译错误；
  3. 扫码页没有申请相机运行时权限 → 首次打开黑屏；
  4. `zxing:core 3.5.x` 在 API < 24 上不兼容，按官方文档 minSdk 21 应搭配 3.3.0。
- **修复**：补 `gradle.properties`；修正 JSON 解析；重命名 env 变量；扫码页加权限申请；核心库版本；工作流 actions 升级到不再弃用的版本。
- **第二次 CI 仍失败**：aapt2 资源链接报错。原因是布局里写了 `?attr/colorBackground`（不存在的应用级属性，应为 `?android:attr/colorBackground`），且 `TextInputLayout` 需要 Material 主题而当时用的是 AppCompat 主题。
- **最终解法**：不再盲改，而是在沙箱里真正搭起 JDK 17 + Gradle 8.7 + Android SDK 34 编译（期间还解决了 Java 独立证书库不信任沙箱出口代理 CA 的问题——把两张 CA 证书导入 `cacerts`）。`assembleDebug` 与 `assembleRelease`（R8 混淆）均 BUILD SUCCESSFUL，release APK 2.3 MB。
- **学到**：AI 在没有编译器反馈的情况下写多文件工程，出错率明显高于有测试的 Python 后端；凡是能本地编译的产出，一定要先编译再交付，靖读代码不能替代编译器。

### 案例 12：真机实测暴露的 4 个问题（v0.4 修复）
- **扫码点了没反应**：JS 桥的 `isServerHost()` 在 WebView 的 JS 线程里读 `webView.url`。Android 规定 WebView 方法只能在 UI 线程调用，于是抛异常、调用被吞，前端拿不到任何回调。修复：由 Activity 在 `onPageStarted/onPageFinished`（UI 线程）维护 `currentUrl`，桥只读这个 volatile 字段。**学到**：`@JavascriptInterface` 方法不在主线程，任何 UI/WebView 访问都要 `Handler.post`。
- **「测试连接」按钮看不见**：主题换成 Material Components 后，普通 `<Button>` 会被自动膨胀为 `MaterialButton`，再套 AppCompat 的 `Borderless.Colored` 样式，结果背景取 colorPrimary、文字取 colorAccent——绿字绿底。修复：改用 `Widget.MaterialComponents.Button(.OutlinedButton)`。
- **后台收不到通知**：App 只靠 WorkManager 每 15 分钟拉一次，用户发完测试立刻看，当然没有。修复：新增前台服务 `InboxService` 对 `/api/notify/inbox?wait=25` 长轮询（服务端新增 `wait` 参数），秒级到达；通知渠道提到 HIGH 以弹横幅；WorkManager 保留兜底；开机自启恢复。
- **移动端抽屉盖满整屏**：`Drawer width="100%"`。彻底改为底部 Tab 栏 + 「我的」页面的原生 App 式布局（前端子代理实现）。
- **另一个小坑**：英文字符串里的 `You'll` 未转义单引号，aapt 直接报 "Invalid unicode escape sequence"。

### 案例 13：用量统计永远是 0 —— contextvar 在线程池里“设了但没传回来”
- **现象**：用户拍照识别后，「AI 用量」显示调用 0、tokens 0。
- **定位**：我在 `get_current_user` 依赖里 `current_user_id.set(user.id)`，模型调用时读它来归属用户。但 FastAPI 的同步依赖运行在线程池，anyio 是把上下文**拷贝**进线程执行的，线程里的 set 不会写回请求上下文；随后端点函数在另一个线程里拿到的是 None。记录写成了“系统”用户，普通用户看自己的用量自然是 0。
- **修复**：改为纯 ASGI 中间件在事件循环里解析用户并 set（后续所有线程池调用都能继承），并加 60 秒内存缓存避免每个请求查库；补测试 `test_vision_usage_recorded_for_user`。
- **学到**：contextvar + 线程池的传播方向是单向的（进不出）；凡是“在依赖里设置全局上下文”的做法都要验证是否真的可见。

### 案例 14：拍照回来照片没了 / 一解锁就刷新
- **原因**：相机 App 占内存，系统回收了我们的 Activity 甚至进程；重建时 `onCreate` 无脑 `loadUrl` 重新加载网页，`<input type=file>` 的回调也随之丢失。
- **修复**：`onSaveInstanceState/restoreState` 保存恢复 WebView；改为**原生拍照 → 原生直接上传 → 结果写入本地“待处理”并通知网页**，网页把草稿存 localStorage，重载后自动恢复；识别改走 `recognize-path`。
- **学到**：WebView 壳应用里任何“跳出去再回来”的流程（相机、分享、支付）都要假设自己会被杀掉。

### 案例 15：requirements.txt 缺了两个包却"一直能跑"
- **现象**：做 Windows 宝塔包时逐行核对依赖，发现 `pyotp`、`qrcode` 不在 `requirements.txt` 里。
- **原因**：v0.2 时的追加命令写成 `pip install ... && python3 -c "...pyotp.__version__" && cat >> requirements.txt`，中间那步因 pyotp 没有 `__version__` 属性报错，`&&` 链直接中断，追加没执行；而沙箱和用户服务器的环境里早已装过这两个包，所以一直没暴露。
- **修复**：补上两包并增加 `tzdata`（Windows 必需）。
- **学到**：把"副作用步骤"放在 `&&` 链末尾很危险；依赖清单要用一次干净环境（`pip install -r` 到新 venv 再 `python -c "import app.main"`）验证。

### 设计取舍记录：热量估算（v0.6）
- 课题要求"不追求精确到个位数的卡路里"，用户又明确需要每道菜的热量。折中：三级来源（模型估算 → 本地 ~150 条常见菜品表按份量缩放 → 用户手改），所有界面统一写"估算 / ≈"，统计里附一句说明，周报只能引用程序汇总的估算值且必须写成"估算约"。这样既满足需求，又不把猜测当事实。

### 案例 17：生成一次餐单却出现两份，其中一份残缺（v0.7 修复）
- **现象**：用户点一次「生成餐单」，列表里出现两份：一份正常，另一份只有“9/6 早餐”一餐，或打开直接白屏 `Cannot read properties of undefined (reading 'map')`。
- **排查**：
  1. 前端 axios 全局超时 90 秒，而 7 天餐单用质量模型常常要 1.5–3 分钟。前端超时报错 → 用户再点一次 → 后端其实两次都在跑，于是落库两份。
  2. 后端把模型返回的**原始 dict** 直接存进 `plan_json`，只要模型某天漏写 `meals`、或输出被 4000 tokens 上限截断后 `parse_json` 只救回了一部分，残缺结构就原样进了数据库；前端 `day.meals.map` 遇到 `undefined` 就崩。
  3. 校验函数只检查了“有 days”，没检查“每天有餐、每餐有菜”。
- **修复**：`_validate_plan_json` 逐层校验并抛错触发重试；入库存 `model_dump()` 后的**补全结构**（缺省字段全部有默认值）；每用户生成互斥锁（重复请求返回 409）；`meal_plan` 输出上限提到 8000；前端生成请求超时 240 秒、生成期间禁用按钮、收到 409 自动轮询；渲染全部 `?? []` 防御，残缺餐单显示“数据不完整可删除”。
- **学到**：模型输出**必须经过校验后的模型再落库**，而不是校验“通过了”就存原始 JSON；长任务的前端超时要和后端实际耗时匹配，并且服务端要做幂等/互斥，否则“用户重试”就是重复写入。

### 案例 18：中餐菜品配图——图库搜不到，AI 生图又太慢（v0.8.6 修复）
- **现象**：餐单里的菜品卡片经常是统一的占位图。维基百科 / 维基共享 / 百度百科能搜到「西兰花」，但搜不到「小米山药粥」「清蒸鲈鱼」这类中餐，命中率很低；一屏十几张卡片，首屏还发卡。
- **排查**：
  1. 免费图库的覆盖面和**中餐命名词表**天然不匹配——百科条目标题和我们写菜名的方式不一样，`清蒸鲈鱼` 能搜到 `鲈鱼` 却拿不到"清蒸"的图，风格更是五花八门。
  2. 早期 `/uploads` 路由只支持单层文件名，`/uploads/dish_images/xxx.jpg` 全部 404，图片存了却显示不出来（v0.8.5 已修）。
  3. 图片没做统一尺寸，原图直接进列表，单张几百 KB × 十几张，移动端流量和渲染都吃不消。
- **修复**：
  1. 取图优先级重排为 **本地缓存 → AI 生图 → 网络图库 → Emoji 兜底**。AI 生图用固定提示词模板（`{菜名}，3D 卡通渲染风格，柔和奶油色渐变背景，居中构图，柔光，可爱简约`）保证全站风格统一，中餐识别也更准。
  2. 接入 **SenseAudio（商汤）生图 API** 作为独立配置：`image_provider` / `image_base_url` / `image_api_key` / `image_model_id` / `image_size`，与文本、识图模型完全解耦，可单独换提供方、单独限额。同步 `/v1/image/sync` 与异步 `/v1/image/async` + `/v1/image/pending` 两条路径都适配了，并把 `429000`/`429002`/`400001`/`authentication_error` 等错误码映射成中文，配额与鉴权类错误标记 `fatal` 让批量任务立即停止重试。
  3. **Emoji 兜底**：`dish_emoji.py` 做「精确菜名 → 关键词（长词优先）→ 类别 → 🍽」四级映射，前端用 Twemoji SVG 渲染，各端风格一致、零成本、秒加载、绝不空白。关键词必须按长度降序排，否则「粥」会抢走「小米山药粥」。
  4. 落盘时统一转 **WebP**（限最长边 1280），并生成 **200×150 居中裁切缩略图** 到 `uploads/thumb/`，列表用缩略图、预览用原图；前端全部 `loading="lazy"` + `onError` 回退 emoji。
  5. 图上加「**用 AI 生图替换掉 emoji 图**」按钮：仅当 AI 生图已开启且 `image_stats.emoji > 0` 时亮起。服务端把任务登记为 `busy("plan")`，重复触发返回 409，前端收到 409 转入轮询——刷新页面也不会重复点。
- **踩到的一个隐蔽坑**：生图模型最初沿用入参名 `image_model`，而这个名字**早被"OpenAI 兼容配图模型"占用了**，结果两者共写同一个 DB key、互相覆盖。改成独立的 `image_model_id` → DB key `dish_image_model`，并加了一条回归测试锁死这个隔离性。
- **学到**：
  - 图库 API 适合通用物体，**长尾的领域名词（中餐）命中率极低**，要么自建映射、要么生成。
  - 给"不确定能否成功的外部依赖"设计功能时，**兜底方案不是可选项而是首要设计**——emoji 兜底让生图失败这件事从"功能挂了"降级成"图片朴素一点"。
  - Pydantic 里旧字段命名一旦被复用，**悄悄覆盖不会报错**，加新语义时宁可另起字段名并写测试锁住。

### 案例 16：（待补充）真实模型图片识别的错误
- 记录：哪张照片、模型识别成什么、实际是什么、置信度多少、我在确认页改了什么。
- 建议截图保存到 `docs/cases/`。

### 案例 11：（待补充）自然语言查询计划错误
- 记录：问题原文、模型生成的 plan JSON、程序校验丢弃了什么、最后结果是否正确。

## 三、设计上防止 AI 出错的措施

1. 视觉识别输出用 Pydantic 严格校验；非法分类 / 份量 / 餐次自动回退到默认值；未知标签直接丢弃并提示。
2. 解析失败自动带着错误信息重试一次，仍失败则切换手动填写，界面明确告知。
3. 自然语言查询：模型 **不写 SQL**，只输出白名单字段的“查询计划”；程序生成 SQL、执行、统计；“今天”的日期由后端注入，避免模型算错日期。
4. 周报 / 月报：程序先算事实，模型只据事实写作；程序再用正则核对总结里的数字是否都能在事实里找到，找不到的标“待核对”。
5. 所有 AI 相关输出附免责声明；原始返回 `ai_raw_json`、模型名、耗时都落库，随时可回查。
6. 密钥只在后端 `.env` / SQLite settings 表；接口返回掩码；`.gitignore` 排除 `.env`。

## 四、十天学到的东西（答辩总结提纲）

- 前端：
- 后端：
- 数据库：
- 部署（WSL）：
- 调试：
- 专项（多模态 / 自然语言转查询）：
