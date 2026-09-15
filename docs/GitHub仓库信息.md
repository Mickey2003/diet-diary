# GitHub 仓库信息（可直接粘贴）

进 GitHub 仓库页 → 右上 **About** 齿轮 → 填 Description / Website / Topics。

## 一、Description（仓库简介）

> GitHub 的 Description 输入框上限 350 字符，但**列表页只显示约 120 字符**，
> 所以主推版本控制在 120 字符以内，把关键词放在最前面。

### 推荐（主用，中文 · 118 字符）

```
一本会看照片的饮食日记：拍照识别菜品 → 时间线 / 统计 → 自然语言查询 → 周报 → 健康档案与个性化餐单（含 AI 生图配图）。FastAPI + React + SQLite，多模型、MCP 接入、Android 壳。
```

### 备选 A（更短，突出 AI · 62 字符）

```
会看照片的 AI 饮食日记：拍照识别 → 统计 → 自然语言查询 → 周报 → 个性化餐单与 AI 配图。
```

### 备选 B（英文，便于检索）

```
AI diet diary: snap a meal, get charts, ask in plain language, get weekly reports & AI-illustrated meal plans.
```

### 备选 C（强调工程亮点 · 119 字符）

```
AI 饮食观察日记：多模态识别 + 自然语言查询 + 个性化餐单 + 菜品 AI 生图。服务端热更新，Android WebView 壳，内置 MCP 服务器与多模型接入。
```

## 二、Website（项目主页）

```
https://diet-diary.720172.xyz
```

（换成你自己的实际部署地址；没部署就先留空。）

## 三、Topics（仓库标签）

GitHub 最多填 20 个，全部小写、用连字符分隔。按重要性排序，直接粘贴：

```
ai  diet-diary  food-recognition  meal-plan  fastapi  react  typescript  sqlite
llm  multimodal  image-generation  mcp  nutrition  health  self-hosted  python
antd  vite  echarts  barcode-scanner
```

## 四、一句话介绍（发群 / 答辩开场备用）

**面向同学**：
> 拍照就能记一餐，AI 帮你识别菜品和标签；攒够记录后能问「这周喝过几次含糖饮料」，还能结合健康档案生成个性化餐单、自动配图。手机装个 2.4 MB 的壳就能用，所有更新都在服务器端。

**面向老师 / 答辩**：
> 一个 AI 全栈饮食观察日记：多模态识别、自然语言转查询（模型不写 SQL、只出受限查询计划）、事实约束的周报、中医体质自测 + 个性化餐单。前端 React，后端 FastAPI，内置 MCP 服务器供 Agent 调用，菜品配图用「AI 生图 + Emoji 兜底」保证永不空白。附 19 个真实 AI 出错与修复案例（`docs/AI_LOG.md`）。
