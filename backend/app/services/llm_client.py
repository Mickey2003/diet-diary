"""
统一模型接入层。

设计要点：
1. 所有供应商都走 OpenAI 兼容的 Chat Completions 协议（openai SDK + 自定义 base_url），
   因此一套代码可以覆盖 OpenAI、通义千问、智谱、DeepSeek、硅基流动、Moonshot、Ollama 以及任何自定义端点。
2. 配置优先级：SQLite settings 表（设置页写入） > .env 环境变量 > 供应商预设默认值。
3. provider = "mock" 时不联网，返回可预期的假数据，用于无密钥演示、离线开发与自动化测试。
4. 密钥只在后端使用，接口返回时一律掩码。
"""
import json
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from .. import config
from ..models import Setting

PROVIDER_PRESETS: Dict[str, Dict[str, str]] = {
    "mock": {
        "label": "离线演示（不调用模型）",
        "base_url": "",
        "text_model": "mock",
        "fast_model": "mock",
        "vision_model": "mock",
    },
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "text_model": "gpt-4o-mini",
        "fast_model": "gpt-4o-mini",
        "vision_model": "gpt-4o-mini",
    },
    "dashscope": {
        "label": "阿里云通义千问（DashScope 兼容模式）",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "text_model": "qwen-plus",
        "fast_model": "qwen-turbo",
        "vision_model": "qwen-vl-plus",
    },
    "zhipu": {
        "label": "智谱 GLM",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "text_model": "glm-4-flash",
        "fast_model": "glm-4-flash",
        "vision_model": "glm-4v-flash",
    },
    "siliconflow": {
        "label": "硅基流动 SiliconFlow",
        "base_url": "https://api.siliconflow.cn/v1",
        "text_model": "Qwen/Qwen2.5-7B-Instruct",
        "fast_model": "Qwen/Qwen2.5-7B-Instruct",
        "vision_model": "Qwen/Qwen2.5-VL-7B-Instruct",
    },
    "deepseek": {
        "label": "DeepSeek（仅文本，视觉需另配）",
        "base_url": "https://api.deepseek.com/v1",
        "text_model": "deepseek-chat",
        "fast_model": "deepseek-chat",
        "vision_model": "",
    },
    "moonshot": {
        "label": "Moonshot Kimi",
        "base_url": "https://api.moonshot.cn/v1",
        "text_model": "moonshot-v1-8k",
        "fast_model": "moonshot-v1-8k",
        "vision_model": "moonshot-v1-8k-vision-preview",
    },
    "ollama": {
        "label": "Ollama 本地",
        "base_url": "http://localhost:11434/v1",
        "text_model": "qwen2.5:7b",
        "fast_model": "qwen2.5:3b",
        "vision_model": "qwen2.5vl:7b",
    },
    "custom": {
        "label": "自定义 OpenAI 兼容接口",
        "base_url": "",
        "text_model": "",
        "fast_model": "",
        "vision_model": "",
    },
}

SETTING_KEYS = ["provider", "base_url", "text_model", "fast_model", "vision_model", "image_model", "api_key"]


@dataclass
class LLMConfig:
    provider: str
    base_url: str
    api_key: str
    text_model: str
    vision_model: str
    source: str  # env / db / mixed
    fast_model: str = ""  # 快速模型（查询规划/解释/记忆抽取/分享文案），空则用 text_model
    image_model: str = ""  # 餐单菜品配图模型（OpenAI 兼容 images.generate），空则不生成配图

    @property
    def is_mock(self) -> bool:
        return self.provider == "mock" or not self.api_key and self.provider != "ollama"


def read_db_settings(db: Session) -> Dict[str, str]:
    rows = db.query(Setting).filter(Setting.key.in_(SETTING_KEYS)).all()
    return {r.key: (r.value or "") for r in rows}


def get_llm_config(db: Optional[Session]) -> LLMConfig:
    env = {
        "provider": config.LLM_PROVIDER,
        "base_url": config.LLM_BASE_URL,
        "api_key": config.LLM_API_KEY,
        "text_model": config.LLM_TEXT_MODEL,
        "fast_model": config.LLM_FAST_MODEL,
        "vision_model": config.LLM_VISION_MODEL,
        "image_model": config.LLM_IMAGE_MODEL,
    }
    dbv: Dict[str, str] = read_db_settings(db) if db is not None else {}
    merged = {k: (dbv.get(k) or env.get(k) or "") for k in env}
    provider = merged["provider"] or "mock"
    preset = PROVIDER_PRESETS.get(provider, PROVIDER_PRESETS["custom"])
    base_url = merged["base_url"] or preset["base_url"]
    text_model = merged["text_model"] or preset["text_model"]
    vision_model = merged["vision_model"] or preset["vision_model"] or text_model
    fast_model = merged["fast_model"] or preset.get("fast_model", "") or text_model
    image_model = merged["image_model"] or preset.get("image_model", "") or ""
    if dbv and any(dbv.values()):
        source = "mixed" if any(env.values()) else "db"
    else:
        source = "env"
    return LLMConfig(provider=provider, base_url=base_url, api_key=merged["api_key"],
                     text_model=text_model, vision_model=vision_model, source=source,
                     fast_model=fast_model, image_model=image_model)


def mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return key[:4] + "*" * 6 + key[-4:]


# ---------- JSON 工具 ----------
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


def strip_json_fence(text: str) -> str:
    """去掉 ```json ... ``` 围栏；若正文前后有解释文字，截取最外层的 JSON 对象或数组。"""
    if text is None:
        return ""
    t = _FENCE_RE.sub("", text.strip()).strip()
    if t.startswith("{") or t.startswith("["):
        return t
    starts = [i for i in (t.find("{"), t.find("[")) if i >= 0]
    if not starts:
        return t
    start = min(starts)
    closer = "}" if t[start] == "{" else "]"
    end = t.rfind(closer)
    return t[start: end + 1] if end > start else t


def parse_json(text: str) -> Any:
    """Parse tolerant model JSON, including fenced and prose-wrapped responses."""
    cleaned = strip_json_fence(text or '').strip()
    if not cleaned:
        raise ValueError('模型返回为空')
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        for index, char in enumerate(cleaned):
            if char not in '{[':
                continue
            try:
                value, _ = decoder.raw_decode(cleaned[index:])
                return value
            except json.JSONDecodeError:
                continue
        raise


# ---------- 任务分流 ----------
# 走快速模型的任务：结构化、短输出、对延迟敏感
FAST_TASKS = {"plan", "explain", "memory_extract", "share_copy", "meal_plan_slot", "generic"}
# 每类任务的输出长度上限：既省钱又明显降低等待时间
TASK_MAX_TOKENS: Dict[str, int] = {
    "plan": 400, "explain": 500, "memory_extract": 600, "share_copy": 300, "vision": 1200,
    "report": 1500, "meal_plan": 8000, "meal_plan_slot": 800, "generic": 200,
}


# ---------- 客户端 ----------
class LLMError(Exception):
    pass


class LLMClient:
    def __init__(self, cfg: LLMConfig, db: Optional[Session] = None):
        self.cfg = cfg
        self._db = db
        self._client = None
        self.image_model = cfg.image_model
        if not cfg.is_mock:
            from openai import OpenAI  # 延迟导入，mock 模式无需依赖网络
            self._client = OpenAI(
                api_key=cfg.api_key or "ollama",
                base_url=cfg.base_url or None,
                timeout=config.LLM_TIMEOUT,
                max_retries=1,
            )

    def _record(self, task: str, model: str, t0: float, ok: bool, prompt_tokens: int = 0,
                completion_tokens: int = 0, error: Optional[str] = None) -> None:
        """写入用量记录（含 mock 与失败），失败不影响业务。"""
        if self._db is None:
            return
        try:
            from ..deps import current_user_id
            from .usage import record_usage
            record_usage(self._db, user_id=current_user_id.get(), provider=self.cfg.provider, model=model, task=task,
                         prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                         latency_ms=int((time.time() - t0) * 1000), ok=ok, error=error)
        except Exception:  # noqa: BLE001
            pass

    def pick_model(self, task: str, vision: bool = False) -> str:
        """按任务选择模型：视觉任务用 vision_model；FAST_TASKS 用 fast_model；其余用 text_model（质量优先）。"""
        if vision:
            return self.cfg.vision_model
        if task in FAST_TASKS and self.cfg.fast_model:
            return self.cfg.fast_model
        return self.cfg.text_model

    # task 决定：mock 返回什么、用量归类、快/慢模型与输出长度上限
    def chat(self, messages: List[Dict[str, Any]], *, vision: bool = False,
             task: str = "generic", temperature: float = 0.2,
             json_mode: bool = False, mock_context: Optional[Dict[str, Any]] = None,
             max_tokens: Optional[int] = None) -> str:
        t0 = time.time()
        if self.cfg.is_mock:
            from .mock_llm import mock_reply
            out = mock_reply(task, messages, mock_context or {})
            self._record(task, "mock", t0, True)
            return out
        model = self.pick_model(task, vision)
        if not model:
            raise LLMError("未配置模型名称，请在设置页填写 text_model / vision_model")
        kwargs: Dict[str, Any] = dict(model=model, messages=messages, temperature=temperature)
        limit = max_tokens or TASK_MAX_TOKENS.get(task)
        if limit:
            kwargs["max_tokens"] = limit
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        try:
            resp = self._client.chat.completions.create(**kwargs)
        except Exception as e:  # noqa: BLE001
            # 部分供应商不支持 response_format，去掉后重试一次
            if json_mode:
                kwargs.pop("response_format", None)
                try:
                    resp = self._client.chat.completions.create(**kwargs)
                except Exception as e2:  # noqa: BLE001
                    self._record(task, model, t0, False, error=str(e2))
                    raise LLMError(f"模型调用失败：{e2}") from e2
            else:
                self._record(task, model, t0, False, error=str(e))
                raise LLMError(f"模型调用失败：{e}") from e
        usage = getattr(resp, "usage", None)
        p_tok = int(getattr(usage, "prompt_tokens", 0) or 0) if usage else 0
        c_tok = int(getattr(usage, "completion_tokens", 0) or 0) if usage else 0
        try:
            content = resp.choices[0].message.content or ""
        except Exception as e:  # noqa: BLE001
            self._record(task, model, t0, False, p_tok, c_tok, error=f"返回格式异常：{e}")
            raise LLMError(f"模型返回格式异常：{e}") from e
        self._record(task, model, t0, True, p_tok, c_tok)
        return content

    def model_name(self, vision: bool = False, task: str = "report") -> str:
        if self.cfg.is_mock:
            return "mock"
        return self.pick_model(task, vision)

    def test_connection(self) -> Dict[str, Any]:
        t0 = time.time()
        if self.cfg.is_mock:
            return {"ok": True, "message": "当前为离线演示模式（mock），未调用真实模型。",
                    "latency_ms": 0, "model": "mock"}
        try:
            txt = self.chat([{"role": "user", "content": "请只回复两个字：成功"}], temperature=0)
            return {"ok": True, "message": f"连接成功，模型回复：{txt.strip()[:40]}",
                    "latency_ms": int((time.time() - t0) * 1000), "model": self.cfg.text_model}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "message": str(e), "latency_ms": int((time.time() - t0) * 1000),
                    "model": self.cfg.text_model}


def get_client(db: Optional[Session]) -> LLMClient:
    return LLMClient(get_llm_config(db), db)


def get_vision_async(db: Optional[Session]) -> bool:
    """后台异步图片分析开关：默认关闭，可由 settings 表的 vision_async 覆盖。"""
    if db is None:
        return config.LLM_VISION_ASYNC
    row = db.get(Setting, "vision_async")
    if row is None or not row.value:
        return config.LLM_VISION_ASYNC
    return row.value.strip().lower() in {"1", "true", "yes", "on"}
