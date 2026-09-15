"""
数据导入导出路由（Feature 1）。
前缀：/api/data
所有端点需要登录（Depends(get_current_user) 已在每个端点声明）。
"""
import io
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import User
from ..services import exporter

router = APIRouter(prefix="/api/data", tags=["data"])


def _parse_dt(s: Optional[str], is_end: bool = False) -> Optional[datetime]:
    """把 YYYY-MM-DD 字符串解析为 datetime；is_end=True 时取当日末尾。"""
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s)
        if is_end:
            d = d.replace(hour=23, minute=59, second=59)
        return d
    except ValueError:
        raise HTTPException(status_code=400, detail=f"日期格式无效：{s!r}，应为 YYYY-MM-DD")


@router.get("/export")
def export_data(
    format: str = Query("json", description="json | csv | zip"),
    from_: Optional[str] = Query(None, alias="from", description="YYYY-MM-DD"),
    to: Optional[str] = Query(None, description="YYYY-MM-DD"),
    include_images: bool = Query(True),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """导出当前用户的饮食数据（JSON / CSV / ZIP）。"""
    from_dt = _parse_dt(from_)
    to_dt = _parse_dt(to, is_end=True)
    date_tag = datetime.now().strftime("%Y%m%d")

    if format == "json":
        data = exporter.build_export_dict(db, user, from_dt, to_dt)
        import json as _json
        body = _json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        return Response(
            content=body,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="diet-diary-export-{date_tag}.json"'},
        )
    elif format == "csv":
        body = exporter.build_csv_bytes(db, user, from_dt, to_dt)
        return Response(
            content=body,
            media_type="text/csv; charset=utf-8-sig",
            headers={"Content-Disposition": f'attachment; filename="diet-diary-export-{date_tag}.csv"'},
        )
    elif format == "zip":
        body = exporter.build_zip_bytes(db, user, from_dt, to_dt, include_images=include_images)
        return Response(
            content=body,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="diet-diary-export-{date_tag}.zip"'},
        )
    else:
        raise HTTPException(status_code=400, detail="format 参数必须为 json、csv 或 zip")


@router.post("/import")
async def import_data(
    file: UploadFile = File(..., description=".json / .csv / .zip"),
    mode: str = Form("merge", description="merge（合并）或 replace（替换）"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """导入饮食数据文件，支持合并或替换模式。"""
    if mode not in ("merge", "replace"):
        raise HTTPException(status_code=400, detail="mode 必须为 merge 或 replace")

    filename = file.filename or "upload"
    fname_lower = filename.lower()
    if not any(fname_lower.endswith(ext) for ext in (".json", ".csv", ".zip")):
        raise HTTPException(status_code=400, detail="仅支持 .json、.csv、.zip 格式")

    file_bytes = await file.read()
    if len(file_bytes) > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="文件超过 50MB 限制")

    try:
        result = exporter.import_data(db, user, file_bytes, filename, mode=mode)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return result


@router.get("/template.csv")
def download_template(user: User = Depends(get_current_user)):
    """下载 CSV 导入模板（含表头和 3 行示例）。"""
    import csv as _csv
    buf = io.StringIO()
    writer = _csv.writer(buf)
    writer.writerow(exporter.CSV_HEADERS)
    for row in exporter.CSV_EXAMPLE_ROWS:
        writer.writerow(row)
    body = b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": 'attachment; filename="diet-diary-template.csv"'},
    )


@router.get("/summary")
def data_summary(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """返回当前用户各表数据量（供 UI 信息展示）。"""
    return exporter.user_summary(db, user.id)
