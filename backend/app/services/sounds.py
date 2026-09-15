"""
提醒音效：服务器预设（程序合成的 WAV，无版权问题）+ 用户上传（mp3/wav/ogg/m4a ≤ 3MB）。
就餐提醒设置保存在 user_settings.meal_alert（JSON）。
"""
import io
import json
import math
import struct
import uuid
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from .. import config
from ..models import Setting, SoundFile, UserSetting

PRESET_META_KEY = "sound_presets"   # settings 表：{"hidden": [name...], "names": {name: 显示名}}
MAX_SYSTEM_SOUNDS = 50

PRESET_DIR = Path(config.DATA_DIR) / "sounds"
USER_DIR = Path(config.UPLOAD_DIR) / "sounds"
ALERT_KEY = "meal_alert"
MAX_SOUND_BYTES = 3 * 1024 * 1024
ALLOWED_MIME = {"audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/wav": "wav", "audio/x-wav": "wav", "audio/wave": "wav",
                "audio/ogg": "ogg", "audio/mp4": "m4a", "audio/x-m4a": "m4a", "audio/aac": "aac"}

# 预设音效：名称 → (中文名, [(频率Hz, 起始秒, 时长秒, 音量)])
PRESETS: Dict[str, Tuple[str, List[Tuple[float, float, float, float]]]] = {
    "chime": ("清脆钟声", [(880, 0.0, 0.5, 0.6), (1108.7, 0.25, 0.6, 0.5), (1318.5, 0.5, 0.9, 0.45)]),
    "bell": ("餐铃", [(659.3, 0.0, 1.2, 0.6), (1318.5, 0.0, 0.8, 0.25), (1975.5, 0.0, 0.5, 0.12)]),
    "ding": ("叮", [(1568, 0.0, 0.7, 0.7)]),
    "marimba": ("木琴", [(523.3, 0.0, 0.35, 0.6), (659.3, 0.3, 0.35, 0.6), (784, 0.6, 0.35, 0.6), (1046.5, 0.9, 0.7, 0.6)]),
    "soft": ("轻柔提示", [(440, 0.0, 0.8, 0.4), (554.4, 0.4, 0.9, 0.35)]),
    "twinkle": ("星星", [(1046.5, 0.0, 0.25, 0.5), (1318.5, 0.2, 0.25, 0.5), (1568, 0.4, 0.25, 0.5), (2093, 0.6, 0.6, 0.5)]),
}

DEFAULT_ALERT: Dict[str, Any] = {
    "enabled": False,
    "sound": "preset:chime",          # preset:<name> | user:<id>
    "lead_minutes": 0,                # 提前几分钟
    "meal_types": ["早餐", "午餐", "晚餐", "加餐"],
    "volume": 0.8,
    "vibrate": True,
}


def _synth(notes: List[Tuple[float, float, float, float]], rate: int = 22050) -> bytes:
    total = max(s + d for _f, s, d, _v in notes) + 0.15
    n = int(total * rate)
    buf = [0.0] * n
    for freq, start, dur, vol in notes:
        s0 = int(start * rate)
        cnt = int(dur * rate)
        for i in range(cnt):
            t = i / rate
            env = math.exp(-4.0 * t / dur) * min(1.0, i / (0.01 * rate))  # 快速起音 + 指数衰减
            idx = s0 + i
            if idx < n:
                buf[idx] += vol * env * (math.sin(2 * math.pi * freq * t) + 0.3 * math.sin(2 * math.pi * freq * 2 * t))
    peak = max(1e-6, max(abs(x) for x in buf))
    scale = 0.9 / peak if peak > 0.9 else 1.0
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(max(-1.0, min(1.0, x * scale)) * 32767)) for x in buf))
    return out.getvalue()


def ensure_presets() -> None:
    """启动时生成预设 WAV（已存在则跳过）。"""
    PRESET_DIR.mkdir(parents=True, exist_ok=True)
    USER_DIR.mkdir(parents=True, exist_ok=True)
    for name, (_label, notes) in PRESETS.items():
        p = PRESET_DIR / f"{name}.wav"
        if not p.exists():
            p.write_bytes(_synth(notes))


def preset_path(name: str) -> Optional[Path]:
    if name not in PRESETS:
        return None
    ensure_presets()
    return PRESET_DIR / f"{name}.wav"


# ---------- 内置预设的管理员元数据（隐藏 / 重命名） ----------
def get_preset_meta(db: Session) -> Dict[str, Any]:
    row = db.get(Setting, PRESET_META_KEY)
    meta: Dict[str, Any] = {"hidden": [], "names": {}}
    if row and row.value:
        try:
            raw = json.loads(row.value)
            meta["hidden"] = [n for n in raw.get("hidden", []) if n in PRESETS]
            meta["names"] = {k: str(v)[:60] for k, v in raw.get("names", {}).items() if k in PRESETS and str(v).strip()}
        except (json.JSONDecodeError, AttributeError):
            pass
    return meta


def set_builtin_preset(db: Session, name: str, label: Optional[str] = None, hidden: Optional[bool] = None) -> Dict[str, Any]:
    if name not in PRESETS:
        raise ValueError("内置预设不存在")
    meta = get_preset_meta(db)
    if label is not None:
        label = label.strip()
        if label and label != PRESETS[name][0]:
            meta["names"][name] = label[:60]
        else:
            meta["names"].pop(name, None)
    if hidden is not None:
        if hidden and name not in meta["hidden"]:
            meta["hidden"].append(name)
        if not hidden and name in meta["hidden"]:
            meta["hidden"].remove(name)
    if hidden and len(meta["hidden"]) >= len(PRESETS) and not db.query(SoundFile).filter(SoundFile.is_system == True).count():  # noqa: E712
        raise ValueError("至少保留一个可用的预设音效")
    row = db.get(Setting, PRESET_META_KEY)
    if row is None:
        db.add(Setting(key=PRESET_META_KEY, value=json.dumps(meta, ensure_ascii=False)))
    else:
        row.value = json.dumps(meta, ensure_ascii=False)
    db.commit()
    return meta


def _system_row_out(r: SoundFile) -> Dict[str, Any]:
    return {"key": f"system:{r.id}", "id": r.id, "name": r.name, "url": f"/api/sounds/file/{r.id}", "mime": r.mime,
            "size": r.size, "created_at": r.created_at, "builtin": False, "hidden": False}


def list_presets(db: Optional[Session] = None, include_hidden: bool = False) -> List[Dict[str, Any]]:
    """预设 = 内置合成音效（可被管理员隐藏 / 重命名）+ 管理员上传的系统音效。"""
    meta = get_preset_meta(db) if db is not None else {"hidden": [], "names": {}}
    out: List[Dict[str, Any]] = []
    for k, v in PRESETS.items():
        hidden = k in meta["hidden"]
        if hidden and not include_hidden:
            continue
        out.append({"key": f"preset:{k}", "name": meta["names"].get(k, v[0]), "default_name": v[0],
                    "url": f"/api/sounds/preset/{k}", "builtin": True, "hidden": hidden})
    if db is not None:
        rows = db.query(SoundFile).filter(SoundFile.is_system == True).order_by(SoundFile.id).all()  # noqa: E712
        out.extend(_system_row_out(r) for r in rows)
    return out


def list_user_sounds(db: Session, user_id: int) -> List[Dict[str, Any]]:
    rows = db.query(SoundFile).filter(SoundFile.user_id == user_id, SoundFile.is_system == False).order_by(SoundFile.id.desc()).all()  # noqa: E712
    return [{"key": f"user:{r.id}", "id": r.id, "name": r.name, "url": f"/api/sounds/file/{r.id}", "mime": r.mime,
             "size": r.size, "created_at": r.created_at} for r in rows]


def rename_sound(db: Session, sound_id: int, name: str, user_id: int, is_admin: bool) -> Optional[SoundFile]:
    """重命名：自己的音效任何人可改；系统音效仅管理员可改。"""
    row = db.get(SoundFile, sound_id)
    if not row:
        return None
    if row.is_system and not is_admin:
        return None
    if not row.is_system and row.user_id != user_id:
        return None
    name = (name or "").strip()
    if not name:
        raise ValueError("名称不能为空")
    row.name = name[:60]
    db.commit()
    db.refresh(row)
    return row


def save_user_sound(db: Session, user_id: int, name: str, data: bytes, mime: str, orig_name: str,
                    is_system: bool = False) -> SoundFile:
    if len(data) > MAX_SOUND_BYTES:
        raise ValueError("音频文件超过 3MB 限制")
    ext = ALLOWED_MIME.get((mime or "").lower())
    if ext is None:
        lower = (orig_name or "").lower()
        for e in ("mp3", "wav", "ogg", "m4a", "aac"):
            if lower.endswith("." + e):
                ext = e
                mime = {"mp3": "audio/mpeg", "wav": "audio/wav", "ogg": "audio/ogg", "m4a": "audio/mp4", "aac": "audio/aac"}[e]
                break
    if ext is None:
        raise ValueError("仅支持 mp3 / wav / ogg / m4a / aac")
    if is_system:
        if db.query(SoundFile).filter(SoundFile.is_system == True).count() >= MAX_SYSTEM_SOUNDS:  # noqa: E712
            raise ValueError(f"系统预设最多 {MAX_SYSTEM_SOUNDS} 个，请先删除一些")
    elif db.query(SoundFile).filter(SoundFile.user_id == user_id, SoundFile.is_system == False).count() >= 20:  # noqa: E712
        raise ValueError("最多保存 20 个自定义音效，请先删除一些")
    USER_DIR.mkdir(parents=True, exist_ok=True)
    fname = f"{'sys' if is_system else user_id}_{uuid.uuid4().hex[:10]}.{ext}"
    (USER_DIR / fname).write_bytes(data)
    row = SoundFile(user_id=user_id, name=(name or orig_name or "自定义音效")[:60], filename=fname, mime=mime,
                    size=len(data), is_system=is_system)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def delete_user_sound(db: Session, user_id: int, sound_id: int, is_admin: bool = False) -> bool:
    """删除：自己的音效；系统音效需管理员。引用了被删系统音效的用户设置在 resolve_sound_url 时回退到默认。"""
    row = db.get(SoundFile, sound_id)
    if not row:
        return False
    if row.is_system:
        if not is_admin:
            return False
    elif row.user_id != user_id:
        return False
    try:
        (USER_DIR / row.filename).unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass
    db.delete(row)
    db.commit()
    # 若当前提醒正使用该音效，回退到预设
    cfg = get_alert_settings(db, user_id)
    if cfg.get("sound") == f"user:{sound_id}":
        cfg["sound"] = DEFAULT_ALERT["sound"]
        save_alert_settings(db, user_id, cfg)
    return True


def user_sound_path(db: Session, user_id: int, sound_id: int) -> Optional[Tuple[Path, str]]:
    """系统音效所有登录用户可读；个人音效仅本人可读。"""
    row = db.get(SoundFile, sound_id)
    if not row or (not row.is_system and row.user_id != user_id):
        return None
    p = USER_DIR / row.filename
    return (p, row.mime) if p.is_file() else None


# ---------- 提醒设置 ----------
def _row(db: Session, user_id: int) -> Optional[UserSetting]:
    return db.query(UserSetting).filter(UserSetting.user_id == user_id, UserSetting.key == ALERT_KEY).first()


def get_alert_settings(db: Session, user_id: int) -> Dict[str, Any]:
    row = _row(db, user_id)
    cfg = dict(DEFAULT_ALERT)
    if row and row.value:
        try:
            cfg.update({k: v for k, v in json.loads(row.value).items() if k in DEFAULT_ALERT})
        except json.JSONDecodeError:
            pass
    return cfg


def save_alert_settings(db: Session, user_id: int, incoming: Dict[str, Any]) -> Dict[str, Any]:
    cfg = get_alert_settings(db, user_id)
    for k in DEFAULT_ALERT:
        if k in incoming and incoming[k] is not None:
            cfg[k] = incoming[k]
    cfg["lead_minutes"] = int(max(0, min(60, int(cfg.get("lead_minutes") or 0))))
    cfg["volume"] = float(max(0.0, min(1.0, float(cfg.get("volume") or 0.8))))
    if not isinstance(cfg.get("meal_types"), list):
        cfg["meal_types"] = list(DEFAULT_ALERT["meal_types"])
    sound = str(cfg.get("sound") or "preset:chime")
    if not (sound.startswith("preset:") and sound[7:] in PRESETS) and not sound.startswith(("user:", "system:")):
        sound = "preset:chime"
    cfg["sound"] = sound
    row = _row(db, user_id)
    if row is None:
        db.add(UserSetting(user_id=user_id, key=ALERT_KEY, value=json.dumps(cfg, ensure_ascii=False)))
    else:
        row.value = json.dumps(cfg, ensure_ascii=False)
    db.commit()
    return cfg


def _fallback_preset(db: Session) -> str:
    """默认回退：第一个未被隐藏的内置预设，否则第一个系统音效，最后 chime。"""
    hidden = get_preset_meta(db)["hidden"]
    for k in PRESETS:
        if k not in hidden:
            return f"/api/sounds/preset/{k}"
    row = db.query(SoundFile).filter(SoundFile.is_system == True).order_by(SoundFile.id).first()  # noqa: E712
    return f"/api/sounds/file/{row.id}" if row else "/api/sounds/preset/chime"


def resolve_sound_url(db: Session, user_id: int, sound_key: str) -> str:
    if sound_key.startswith(("user:", "system:")):
        try:
            sid = int(sound_key.split(":", 1)[1])
        except ValueError:
            sid = -1
        if user_sound_path(db, user_id, sid):
            return f"/api/sounds/file/{sid}"
        return _fallback_preset(db)
    name = sound_key[7:] if sound_key.startswith("preset:") else ""
    if name in PRESETS and name not in get_preset_meta(db)["hidden"]:
        return f"/api/sounds/preset/{name}"
    return _fallback_preset(db)  # 被管理员隐藏 / 不存在的预设 → 回退
