"""
通知渠道实现。每个渠道：send(cfg, msg) -> (ok, detail)。
msg 字段：title / text / markdown / html / sms_params（短信模板参数列表）。

- email       SMTP（SSL 465 或 STARTTLS 587）
- wecom       企业微信群机器人 Webhook
- qq          QQ 机器人（OneBot v11 HTTP：NapCat / go-cqhttp / LLOneBot）
- serverchan  Server酱（微信推送，支持 SCT 与 SC3 sctp 密钥）
- pushplus    PushPlus（微信推送）
- tencent_sms 腾讯云短信（TC3-HMAC-SHA256 签名，标准库实现，无需 SDK）
"""
import hashlib
import hmac
import json
import re
import smtplib
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Any, Callable, Dict, List, Tuple

import httpx

HTTP_TIMEOUT = 15.0


@dataclass
class Message:
    title: str
    text: str
    markdown: str = ""
    html: str = ""
    sms_params: List[str] = field(default_factory=list)

    def md(self) -> str:
        return self.markdown or self.text


# ---------- 渠道元数据（前端据此渲染表单） ----------
CHANNEL_META: List[Dict[str, Any]] = [
    {
        "key": "email", "label": "邮件（SMTP）",
        "help": "QQ 邮箱：smtp.qq.com 465 SSL，密码填“授权码”；163：smtp.163.com 465；Gmail：smtp.gmail.com 465，密码填应用专用密码。",
        "fields": [
            {"name": "smtp_host", "label": "SMTP 服务器", "type": "text", "placeholder": "smtp.qq.com"},
            {"name": "smtp_port", "label": "端口", "type": "number", "placeholder": "465"},
            {"name": "use_ssl", "label": "SSL（465 端口勾选；587 不勾选走 STARTTLS）", "type": "boolean"},
            {"name": "username", "label": "登录账号", "type": "text", "placeholder": "you@qq.com"},
            {"name": "password", "label": "密码 / 授权码", "type": "password", "secret": True},
            {"name": "from_addr", "label": "发件人地址（留空同账号）", "type": "text"},
            {"name": "to_addrs", "label": "收件人（多个用逗号分隔）", "type": "text", "placeholder": "a@x.com, b@y.com"},
        ],
    },
    {
        "key": "wecom", "label": "企业微信群机器人",
        "help": "企业微信群 → 群机器人 → 添加，复制 Webhook 地址。",
        "fields": [
            {"name": "webhook_url", "label": "Webhook 地址", "type": "password", "secret": True,
             "placeholder": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=..."},
        ],
    },
    {
        "key": "qq", "label": "QQ 机器人（OneBot v11 HTTP）",
        "help": "需自行运行 NapCat / go-cqhttp / LLOneBot 并开启 HTTP 服务；填写其地址与 access_token。",
        "fields": [
            {"name": "api_base", "label": "HTTP API 地址", "type": "text", "placeholder": "http://127.0.0.1:3000"},
            {"name": "access_token", "label": "Access Token（可空）", "type": "password", "secret": True},
            {"name": "target_type", "label": "发送对象类型", "type": "select", "options": [
                {"label": "私聊 QQ 号", "value": "private"}, {"label": "QQ 群号", "value": "group"}]},
            {"name": "target_id", "label": "QQ 号 / 群号", "type": "text"},
        ],
    },
    {
        "key": "serverchan", "label": "Server酱（微信推送）",
        "help": "https://sct.ftqq.com 登录后获取 SendKey（SCT 开头）；Server酱³ 为 sctp 开头。",
        "fields": [
            {"name": "sendkey", "label": "SendKey", "type": "password", "secret": True},
        ],
    },
    {
        "key": "pushplus", "label": "PushPlus（微信推送）",
        "help": "https://www.pushplus.plus 微信扫码登录后获取 token。",
        "fields": [
            {"name": "token", "label": "Token", "type": "password", "secret": True},
        ],
    },
    {
        "key": "tencent_sms", "label": "腾讯云短信",
        "help": "短信是模板制，正文不能自定义。请在腾讯云创建两个模板变量以内的模板，例如“您今天记录了{1}餐，含糖饮料{2}次”。提醒类消息不带变量。",
        "fields": [
            {"name": "secret_id", "label": "SecretId", "type": "text"},
            {"name": "secret_key", "label": "SecretKey", "type": "password", "secret": True},
            {"name": "sdk_app_id", "label": "短信 SdkAppId", "type": "text", "placeholder": "1400xxxxxx"},
            {"name": "sign_name", "label": "签名内容", "type": "text"},
            {"name": "template_id", "label": "模板 ID", "type": "text"},
            {"name": "phone_numbers", "label": "手机号（+86 开头，多个逗号分隔）", "type": "text", "placeholder": "+8613800000000"},
            {"name": "region", "label": "地域", "type": "text", "placeholder": "ap-guangzhou"},
        ],
    },
]

CHANNEL_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "email": {"enabled": False, "smtp_host": "", "smtp_port": 465, "use_ssl": True, "username": "", "password": "",
              "from_addr": "", "to_addrs": ""},
    "wecom": {"enabled": False, "webhook_url": ""},
    "qq": {"enabled": False, "api_base": "http://127.0.0.1:3000", "access_token": "", "target_type": "private", "target_id": ""},
    "serverchan": {"enabled": False, "sendkey": ""},
    "pushplus": {"enabled": False, "token": ""},
    "tencent_sms": {"enabled": False, "secret_id": "", "secret_key": "", "sdk_app_id": "", "sign_name": "",
                    "template_id": "", "phone_numbers": "", "region": "ap-guangzhou"},
}

SECRET_FIELDS: Dict[str, List[str]] = {
    m["key"]: [f["name"] for f in m["fields"] if f.get("secret")] for m in CHANNEL_META
}


def _split_list(s: str) -> List[str]:
    return [x.strip() for x in re.split(r"[,，;；\s]+", s or "") if x.strip()]


# ---------- 各渠道 ----------
def send_email(cfg: Dict[str, Any], msg: Message) -> Tuple[bool, str]:
    to_addrs = _split_list(cfg.get("to_addrs", ""))
    if not cfg.get("smtp_host") or not cfg.get("username") or not to_addrs:
        return False, "SMTP 服务器 / 账号 / 收件人 未填写完整"
    from_addr = cfg.get("from_addr") or cfg["username"]
    mime = MIMEMultipart("alternative")
    mime["Subject"] = msg.title
    mime["From"] = formataddr(("今天吃得怎么样", from_addr))
    mime["To"] = ", ".join(to_addrs)
    mime.attach(MIMEText(msg.text, "plain", "utf-8"))
    if msg.html:
        mime.attach(MIMEText(msg.html, "html", "utf-8"))
    port = int(cfg.get("smtp_port") or 465)
    try:
        if cfg.get("use_ssl", True):
            server = smtplib.SMTP_SSL(cfg["smtp_host"], port, timeout=HTTP_TIMEOUT)
        else:
            server = smtplib.SMTP(cfg["smtp_host"], port, timeout=HTTP_TIMEOUT)
            server.starttls()
        with server:
            server.login(cfg["username"], cfg.get("password", ""))
            server.sendmail(from_addr, to_addrs, mime.as_string())
        return True, f"已发送至 {', '.join(to_addrs)}"
    except Exception as e:  # noqa: BLE001
        return False, f"SMTP 发送失败：{e}"


def send_wecom(cfg: Dict[str, Any], msg: Message) -> Tuple[bool, str]:
    url = cfg.get("webhook_url", "")
    if not url.startswith("https://qyapi.weixin.qq.com/"):
        return False, "Webhook 地址无效"
    content = f"**{msg.title}**\n{msg.md()}"[:4000]
    try:
        r = httpx.post(url, json={"msgtype": "markdown", "markdown": {"content": content}}, timeout=HTTP_TIMEOUT)
        data = r.json()
        if data.get("errcode") == 0:
            return True, "企业微信已接收"
        return False, f"企业微信返回：{data}"
    except Exception as e:  # noqa: BLE001
        return False, f"请求失败：{e}"


def send_qq(cfg: Dict[str, Any], msg: Message) -> Tuple[bool, str]:
    base = (cfg.get("api_base") or "").rstrip("/")
    target = (cfg.get("target_id") or "").strip()
    if not base or not target.isdigit():
        return False, "API 地址或 QQ 号/群号未填写"
    headers = {}
    if cfg.get("access_token"):
        headers["Authorization"] = f"Bearer {cfg['access_token']}"
    text = f"{msg.title}\n{msg.text}"[:3000]
    if cfg.get("target_type") == "group":
        url, body = f"{base}/send_group_msg", {"group_id": int(target), "message": text}
    else:
        url, body = f"{base}/send_private_msg", {"user_id": int(target), "message": text}
    try:
        r = httpx.post(url, json=body, headers=headers, timeout=HTTP_TIMEOUT)
        data = r.json()
        if data.get("status") == "ok" or data.get("retcode") == 0:
            return True, "QQ 机器人已发送"
        return False, f"机器人返回：{str(data)[:300]}"
    except Exception as e:  # noqa: BLE001
        return False, f"请求失败：{e}"


def send_serverchan(cfg: Dict[str, Any], msg: Message) -> Tuple[bool, str]:
    key = (cfg.get("sendkey") or "").strip()
    if not key:
        return False, "SendKey 未填写"
    if key.startswith("sctp"):
        m = re.match(r"sctp(\d+)t", key)
        if not m:
            return False, "Server酱³ SendKey 格式不正确"
        url = f"https://{m.group(1)}.push.ft07.com/send/{key}.send"
    else:
        url = f"https://sctapi.ftqq.com/{key}.send"
    try:
        r = httpx.post(url, data={"title": msg.title[:32], "desp": msg.md()[:30000]}, timeout=HTTP_TIMEOUT)
        data = r.json()
        if data.get("code") == 0:
            return True, "Server酱已接收"
        return False, f"Server酱返回：{str(data)[:300]}"
    except Exception as e:  # noqa: BLE001
        return False, f"请求失败：{e}"


def send_pushplus(cfg: Dict[str, Any], msg: Message) -> Tuple[bool, str]:
    token = (cfg.get("token") or "").strip()
    if not token:
        return False, "Token 未填写"
    try:
        r = httpx.post("https://www.pushplus.plus/send",
                       json={"token": token, "title": msg.title, "content": msg.md(), "template": "markdown"},
                       timeout=HTTP_TIMEOUT)
        data = r.json()
        if data.get("code") == 200:
            return True, "PushPlus 已接收"
        return False, f"PushPlus 返回：{str(data)[:300]}"
    except Exception as e:  # noqa: BLE001
        return False, f"请求失败：{e}"


def _hmac_sha256(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def tencent_tc3_headers(secret_id: str, secret_key: str, service: str, host: str, action: str, version: str,
                        region: str, payload: str, timestamp: int = None) -> Dict[str, str]:  # type: ignore[assignment]
    """腾讯云 API 3.0 TC3-HMAC-SHA256 签名（独立函数便于测试）。"""
    ts = int(timestamp if timestamp is not None else time.time())
    date = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
    ct = "application/json; charset=utf-8"
    canonical_headers = f"content-type:{ct}\nhost:{host}\nx-tc-action:{action.lower()}\n"
    signed_headers = "content-type;host;x-tc-action"
    hashed_payload = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    canonical_request = f"POST\n/\n\n{canonical_headers}\n{signed_headers}\n{hashed_payload}"
    scope = f"{date}/{service}/tc3_request"
    string_to_sign = f"TC3-HMAC-SHA256\n{ts}\n{scope}\n{hashlib.sha256(canonical_request.encode()).hexdigest()}"
    secret_date = _hmac_sha256(("TC3" + secret_key).encode("utf-8"), date)
    secret_service = _hmac_sha256(secret_date, service)
    secret_signing = _hmac_sha256(secret_service, "tc3_request")
    signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    authorization = (f"TC3-HMAC-SHA256 Credential={secret_id}/{scope}, "
                     f"SignedHeaders={signed_headers}, Signature={signature}")
    return {
        "Authorization": authorization, "Content-Type": ct, "Host": host,
        "X-TC-Action": action, "X-TC-Version": version, "X-TC-Timestamp": str(ts), "X-TC-Region": region,
    }


def send_tencent_sms(cfg: Dict[str, Any], msg: Message) -> Tuple[bool, str]:
    phones = _split_list(cfg.get("phone_numbers", ""))
    required = ["secret_id", "secret_key", "sdk_app_id", "sign_name", "template_id"]
    if any(not cfg.get(k) for k in required) or not phones:
        return False, "腾讯云短信参数未填写完整"
    host = "sms.tencentcloudapi.com"
    body = {
        "PhoneNumberSet": phones, "SmsSdkAppId": str(cfg["sdk_app_id"]), "SignName": cfg["sign_name"],
        "TemplateId": str(cfg["template_id"]), "TemplateParamSet": [str(p) for p in msg.sms_params],
    }
    payload = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
    headers = tencent_tc3_headers(cfg["secret_id"], cfg["secret_key"], "sms", host, "SendSms", "2021-01-11",
                                  cfg.get("region") or "ap-guangzhou", payload)
    try:
        r = httpx.post(f"https://{host}", content=payload.encode("utf-8"), headers=headers, timeout=HTTP_TIMEOUT)
        data = r.json().get("Response", {})
        if "Error" in data:
            return False, f"腾讯云返回错误：{data['Error']}"
        statuses = data.get("SendStatusSet", [])
        bad = [s for s in statuses if s.get("Code") != "Ok"]
        if bad:
            return False, f"部分号码发送失败：{bad}"
        return True, f"短信已发送至 {len(statuses)} 个号码"
    except Exception as e:  # noqa: BLE001
        return False, f"请求失败：{e}"


SENDERS: Dict[str, Callable[[Dict[str, Any], Message], Tuple[bool, str]]] = {
    "email": send_email, "wecom": send_wecom, "qq": send_qq, "serverchan": send_serverchan,
    "pushplus": send_pushplus, "tencent_sms": send_tencent_sms,
}
