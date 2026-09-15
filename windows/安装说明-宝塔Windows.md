# 在 Windows Server + 宝塔面板 上部署《今天吃得怎么样》

> 适用：Windows Server 2016/2019/2022 + 宝塔 Windows 面板（8.x）。
> 本压缩包已包含**编译好的前端**（`frontend/dist`），服务器上**不需要安装 Node.js**。
> 架构：宝塔 Nginx（80/443，HTTPS 证书）→ 反向代理 → 本机 `127.0.0.1:8000` 的 FastAPI（同时托管前端页面）。

---

## 一、准备

1. 宝塔面板 →「软件商店」安装：
   - **Nginx**（任意 1.2x 版本）
   - **Python 项目管理器**（宝塔官方插件）
2. 打开「Python 项目管理器」→「版本管理」→ 安装 **Python 3.11**（3.10 / 3.12 也可，不要低于 3.9）。
3. 域名 `diet-diary.720172.xyz` 的 A 记录指向本服务器公网 IP；云安全组 / Windows 防火墙放行 **80、443**。8000 端口不要对公网开放。

## 二、上传解压

1. 宝塔「文件」→ 进入 `D:\wwwroot`（或你喜欢的目录），上传本压缩包并解压，得到 `D:\wwwroot\diet-diary\`。
2. 目录结构：
   ```
   diet-diary\
   ├── backend\            后端（FastAPI），运行目录
   │   ├── app\
   │   ├── requirements.txt
   │   └── .env.example     → 复制为 .env
   ├── frontend\dist\      已构建的前端（后端自动托管，无需处理）
   ├── windows\            本目录：脚本与说明
   │   ├── install-windows.bat      创建虚拟环境、安装依赖、生成 .env
   │   ├── start-windows.bat        手动启动（测试用）
   │   ├── nginx-reverse-proxy.conf 宝塔 Nginx 反向代理配置片段
   │   └── nssm-install-service.bat 不用宝塔守护时，注册为 Windows 服务
   ├── docs\AI_LOG.md
   └── README.md           完整功能说明
   ```

## 三、配置 .env

复制 `backend\.env.example` 为 `backend\.env`（可用 `install-windows.bat` 自动完成），按需修改：

```env
LLM_PROVIDER=mock          # 先用离线模式跑通，之后在网页「模型设置」里配置真实模型（管理员）
ADMIN_USERNAME=admin
ADMIN_PASSWORD=             # 留空则首次启动随机生成，写入 backend\data\initial_password.txt
TIMEZONE=Asia/Shanghai
ENABLE_SCHEDULER=1
CORS_ORIGINS=https://diet-diary.720172.xyz
```

## 四、用宝塔「Python 项目管理器」运行后端（推荐）

1. 「Python 项目管理器」→「添加项目」：
   | 项 | 填写 |
   |---|---|
   | 项目名称 | diet-diary |
   | 项目路径 | `D:\wwwroot\diet-diary\backend` |
   | Python 版本 | 3.11 |
   | 框架 | 其他 / 通用 |
   | 启动方式 | 命令行启动 |
   | 启动命令 | `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips=127.0.0.1` |
   | 端口 | 8000 |
   | 是否安装依赖 | 勾选（读取 requirements.txt）；若插件没有该选项，见下一步手动安装 |
2. 手动安装依赖（如需要）：在项目的「终端」或「模块管理」中执行  
   `pip install -r requirements.txt`  
   国内建议先设置镜像：`pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple`
3. 启动项目，查看「日志」应看到 `Uvicorn running on http://127.0.0.1:8000` 以及 `[auth] 已创建初始管理员 admin，密码见 ...initial_password.txt`。
4. 在服务器本机浏览器打开 http://127.0.0.1:8000/api/health 应返回 `{"status":"ok"}`。

> 也可以不用插件：双击 `windows\install-windows.bat`（一次）再运行 `windows\start-windows.bat` 测试；长期运行用 `nssm-install-service.bat` 注册为 Windows 服务（开机自启、崩溃自动重启）。

## 五、宝塔 Nginx 站点与 HTTPS

1. 「网站」→「添加站点」：域名 `diet-diary.720172.xyz`，纯静态，不创建数据库/FTP。
2. 站点「设置」→「反向代理」→ 添加：
   - 代理名称：backend
   - 目标 URL：`http://127.0.0.1:8000`
   - 发送域名：`$host`
3. 站点「设置」→「配置文件」，在 `server { ... }` 内（反向代理 include 之前或 location 内）加入 `windows\nginx-reverse-proxy.conf` 中的内容；关键几行：
   ```nginx
   client_max_body_size 30m;          # 照片上传
   proxy_read_timeout 300s;            # App 通知长轮询最多等 25 秒
   proxy_set_header X-Forwarded-Proto $scheme;   # 让后端知道是 HTTPS（Cookie Secure）
   proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
   gzip on; gzip_types text/plain application/json application/javascript text/css;
   ```
   宝塔生成的反向代理配置一般已含 `proxy_set_header Host $host` 与 `X-Real-IP`，保留即可。
4. 「设置」→「SSL」→「Let's Encrypt」申请证书（域名验证方式选文件验证），勾选**强制 HTTPS**。
5. 浏览器访问 https://diet-diary.720172.xyz → 登录页；初始密码在 `backend\data\initial_password.txt`。登录后立即修改密码并开启两步验证。

## 六、App 连接

Android App 默认服务器就是 `https://diet-diary.720172.xyz`，安装后直接登录即可。

## 七、更新版本

1. 停止 Python 项目（或 Windows 服务）。
2. 用新压缩包覆盖 `backend\app`、`frontend\dist`、`docs`、`README.md`；**不要覆盖** `backend\.env`、`backend\data`、`backend\uploads`。
3. 若 requirements.txt 有变化，重新 `pip install -r requirements.txt`。
4. 启动项目。数据库表结构会在启动时自动迁移。

## 八、常见问题（Windows 特有）

| 问题 | 处理 |
|---|---|
| 报错 `ZoneInfoNotFoundError: Asia/Shanghai` | Windows 没有系统时区库，需 `pip install tzdata`（requirements.txt 已包含，重新安装依赖即可） |
| 日志中文乱码 | 启动命令前加环境变量 `PYTHONIOENCODING=utf-8`（宝塔 Python 项目管理器的「环境变量」处添加），或用 `start-windows.bat` |
| `pip install` 很慢/失败 | 设置清华镜像；Pillow / pydantic 都有 Windows 预编译包，无需安装 VC++ 编译器 |
| 端口 8000 被占用 | `netstat -ano | findstr :8000` 找到 PID，任务管理器结束；或改端口并同步修改 Nginx 反向代理目标 |
| 上传照片 413 | Nginx 未加 `client_max_body_size 30m` |
| App 实时通知不到 / 504 | Nginx 未加 `proxy_read_timeout 300s`（长轮询 25 秒会被默认 60 秒之外的更短超时打断的情况少见，但宝塔某些模板为 30s） |
| 登录后一刷新就退出 | 未配置 `X-Forwarded-Proto`，且用 HTTPS 访问 → 后端签发了非 Secure Cookie 但浏览器拒绝；加上该头后重新登录 |
| `data\diet.db-wal` `.db-shm` 文件 | SQLite WAL 模式的正常文件，勿删；备份请连同 `.db` 一起在停服后复制 |
| 想看 API 文档 | 本机访问 http://127.0.0.1:8000/docs（不要通过公网暴露 8000） |
| 图片目录权限 | 确保运行 Python 的用户对 `backend\data`、`backend\uploads` 有写权限（宝塔默认以 SYSTEM/管理员运行，无需处理） |

## 九、目录与文件说明

- `backend\data\diet.db`：SQLite 数据库（自动创建）
- `backend\uploads\`：餐食照片与 `thumb\` 缩略图
- `backend\data\initial_password.txt`：首次启动生成的管理员密码（登录后可删除）
- 日志：宝塔 Python 项目管理器的「日志」按钮；或 NSSM 服务的 `windows\logs\`
