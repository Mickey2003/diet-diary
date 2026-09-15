"""
应用配置：从 .env / 环境变量读取。
模型相关配置会被 SQLite settings 表中的值覆盖（见 services/llm_client.get_llm_config）。
"""
import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")

DATA_DIR = Path(os.getenv("DATA_DIR", BACKEND_DIR / "data"))
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", BACKEND_DIR / "uploads"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'diet.db'}")

# 模型配置（默认值，可被设置页覆盖）
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "mock")  # mock 表示离线演示模式
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_TEXT_MODEL = os.getenv("LLM_TEXT_MODEL", "")
LLM_FAST_MODEL = os.getenv("LLM_FAST_MODEL", "")  # 快速模型（查询规划/解释/记忆/分享文案），空则与 text_model 相同
LLM_VISION_MODEL = os.getenv("LLM_VISION_MODEL", "")
# 餐单菜品配图模型（OpenAI 兼容 images.generate）。留空则不生成配图，菜品卡片回退为 emoji/占位图。
LLM_IMAGE_MODEL = os.getenv("LLM_IMAGE_MODEL", "")

# ---------- 生图专用 API 配置（与文本/识图模型解耦，v0.8.6） ----------
# provider: senseaudio | openai | custom（留空则复用文本模型配置）
IMAGE_PROVIDER = os.getenv("IMAGE_PROVIDER", "")
IMAGE_BASE_URL = os.getenv("IMAGE_BASE_URL", "")
IMAGE_API_KEY = os.getenv("IMAGE_API_KEY", "")
IMAGE_MODEL = os.getenv("IMAGE_MODEL", "")
IMAGE_SIZE = os.getenv("IMAGE_SIZE", "1024x1024")
IMAGE_TIMEOUT = float(os.getenv("IMAGE_TIMEOUT", "120"))
# 模型能力清单是否向前端暴露（设置页用）
DISH_EMOJI_FALLBACK = os.getenv("DISH_EMOJI_FALLBACK", "true").lower() in {"1", "true", "yes", "on"}
# 是否允许从网络/图库抓取现成菜品图片（维基百科/维基共享/百度百科等），抓取后由服务端本地托管。默认开启。
DISH_IMAGES_WEB = os.getenv("DISH_IMAGES_WEB", "true").lower() in {"1", "true", "yes", "on"}
# 是否启用 AI 生图（消耗 token 且可能限流）。默认关闭；管理员可在设置页开启。
DISH_AI_IMAGES = os.getenv("DISH_AI_IMAGES", "false").lower() in {"1", "true", "yes", "on"}
# 条码识别在 Open Food Facts 之外，是否再尝试 UPCitemdb / USDA / 国内接口等补充数据源。默认开启。
BARCODE_EXTRA_SOURCES = os.getenv("BARCODE_EXTRA_SOURCES", "true").lower() in {"1", "true", "yes", "on"}
# 可选的国内条码接口模板（含 {code} 占位符），如聚合数据/天行等；留空则不启用
BARCODE_CN_API_URL = os.getenv("BARCODE_CN_API_URL", "")
# USDA FoodData Central 密钥（默认 DEMO_KEY，可自行申请覆盖）
USDA_API_KEY = os.getenv("USDA_API_KEY", "DEMO_KEY")

# ---------- 网络加速（服务器位于中国大陆时，代理转发可能无法直连的海外请求） ----------
# 前缀代理地址：形如 https://proxy.linjiam.in/ ，使用时拼在目标 URL 之前。
NET_PROXY_URL = os.getenv("NET_PROXY_URL", "https://proxy.linjiam.in/")
# 加速模式：auto（自动检测）/ on（强制开启）/ off（关闭）。管理员可在设置页调整。
NET_PROXY_MODE = os.getenv("NET_PROXY_MODE", "auto")
# 自动检测时用于探测“能否直连海外”的探针地址（大陆通常无法直连）
NET_PROXY_PROBE_URL = os.getenv("NET_PROXY_PROBE_URL", "https://www.wikipedia.org/")
# 需要走代理的域名后缀白名单（仅这些海外域名会被加前缀，国内源直连）
NET_PROXY_HOSTS = tuple(
    h.strip() for h in os.getenv(
        "NET_PROXY_HOSTS",
        "wikipedia.org,wikimedia.org,openfoodfacts.org,upcitemdb.com,nal.usda.gov",
    ).split(",") if h.strip()
)
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "60"))
# 图片识别是否交给后台任务；默认关闭，避免快速模型造成通知冗余
LLM_VISION_ASYNC = os.getenv("LLM_VISION_ASYNC", "false").lower() in {"1", "true", "yes", "on"}

TIMEZONE = os.getenv("TIMEZONE", "Asia/Shanghai")
MAX_IMAGE_SIDE = int(os.getenv("MAX_IMAGE_SIDE", "1280"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "10"))

# 通知定时任务（测试时可关闭）
ENABLE_SCHEDULER = os.getenv("ENABLE_SCHEDULER", "1") not in ("0", "false", "False")

CORS_ORIGINS = [o.strip() for o in os.getenv(
    "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
).split(",") if o.strip()]

DISCLAIMER = "识别与估算可能有误，本应用不提供医疗诊断或精确营养数据，仅帮助你观察饮食结构。"
