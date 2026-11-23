"""
阶段四：简历上传与解析测试

覆盖：
1. DOCX 上传 → 解析 → 结构化（LLM 关闭时走规则兜底）
2. 同一文件重复上传 → 复用，不重复解析
3. 坏文件 → 201 + failed + 可读错误，不抛 500
4. 同一人不同文件 → 合并为同一候选人
5. 预签名下载 → URL + 审计落库
6. 列表脱敏
7. 校对保存
8. 不支持的扩展名
9. 重新解析

关键前提：
- conftest 已设 LLM_MOCK=true，抽取走正则兜底，测试不联网；
- 上传接口返回时的 status 恒为 pending（后台任务在响应之后才写库），
  因此断言最终状态必须再查 /resume-files/status。
"""
from __future__ import annotations

import io
import os
import sqlite3
import time
import uuid

from docx import Document
from docx.oxml import parse_xml

from app.core.security import hash_password
from app.models.base import utcnow

PREFIX = "/api/v1"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


# ---------------------------------------------------------------- 工具
def _db_path() -> str:
    return os.environ["DATABASE_URL"].split("sqlite+aiosqlite:///", 1)[1]


def _insert_user(name: str, password: str = "Passw0rd!") -> None:
    now = str(utcnow())
    conn = sqlite3.connect(_db_path())
    try:
        conn.execute(
            '''
            INSERT INTO "user"
                (company_id, name, email, password, role, status, email_verified_at,
                 login_fail_count, token_version, create_time, update_time)
            VALUES (1, ?, ?, ?, 'recruiter', 'active', ?, 0, 0, ?, ?)
            ''',
            (name, f"{name}@example.com", hash_password(password), now, now, now),
        )
        conn.commit()
    finally:
        conn.close()


def _headers(client, prefix: str = "cv") -> dict[str, str]:
    name = f"{prefix}_{uuid.uuid4().hex[:8]}"
    _insert_user(name)
    login = client.post(
        f"{PREFIX}/auth/login", json={"account": name, "password": "Passw0rd!"}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _docx(*lines: str) -> bytes:
    doc = Document()
    for line in lines:
        doc.add_paragraph(line)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _docx_textbox(*lines: str) -> bytes:
    """构造“正文全在文本框里”的 DOCX：python-docx 读不到，XML 能读到"""
    from xml.sax.saxutils import escape

    body = "".join(
        f"<w:p><w:r><w:t>{escape(line)}</w:t></w:r></w:p>" for line in lines
    )
    pict = parse_xml(
        '<w:pict xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:v="urn:schemas-microsoft-com:vml">'
        '<v:shape id="resumeTextBox" style="width:400pt;height:300pt">'
        f"<v:textbox><w:txbxContent>{body}</w:txbxContent></v:textbox>"
        "</v:shape></w:pict>"
    )
    doc = Document()
    paragraph = doc.add_paragraph()
    paragraph.add_run()._r.append(pict)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _resume(name: str, phone: str, *, email: str | None = None, skills: str = "技能：Python、MySQL") -> bytes:
    """
    构造一份"像样"的简历

    注意：parser.ensure_quality 有 MIN_TEXT_CHARS=20 的下限，
    文本过短会被判为无效简历，测试数据必须包含足够内容。
    """
    lines = [
        name,
        f"手机：{phone}",
    ]
    if email:
        lines.append(f"邮箱：{email}")
    lines += [
        "现居：上海",
        "工作经历：某科技有限公司 | 后端工程师 | 2023-07 ~ 至今",
        "负责订单服务开发与性能优化，日均处理百万级请求。",
        skills,
    ]
    return _docx(*lines)


def _upload(client, headers, filename: str, data: bytes, mime: str = "application/octet-stream"):
    return client.post(
        f"{PREFIX}/candidates/upload",
        headers=headers,
        files={"files": (filename, data, mime)},
    )


def _resolve(client, headers, item: dict) -> dict:
    """上传响应里的 status 是 pending；再查一次状态接口拿最终结果"""
    file_id = item.get("file_id")
    if not file_id:
        return item
    state = item
    for _ in range(50):
        resp = client.get(
            f"{PREFIX}/resume-files/status", headers=headers, params={"ids": str(file_id)}
        )
        assert resp.status_code == 200, resp.text
        state = resp.json()["items"][0]
        if state["status"] in ("success", "failed"):
            break
        time.sleep(0.1)
    return {**item, **state}


def _upload_one(client, headers, filename: str, data: bytes, mime: str = DOCX_MIME) -> dict:
    resp = _upload(client, headers, filename, data, mime)
    assert resp.status_code == 201, resp.text
    return _resolve(client, headers, resp.json()["items"][0])


def _count(sql: str, params: tuple = ()) -> int:
    conn = sqlite3.connect(_db_path())
    try:
        return conn.execute(sql, params).fetchone()[0]
    finally:
        conn.close()


# ---------------------------------------------------------------- 用例
def test_upload_docx_parsed(client):
    headers = _headers(client)
    phone = "13911112222"
    data = _docx(
        "李四",
        f"手机：{phone}",
        "邮箱：lisi.test@example.com",
        "工作经历：某科技公司 | 后端工程师 | 2023-07 ~ 至今",
        "技能：Python、MySQL",
    )

    item = _upload_one(client, headers, "李四_简历.docx", data)
    assert item["status"] == "success", item
    assert item["candidate_id"]

    detail = client.get(f"{PREFIX}/candidates/{item['candidate_id']}", headers=headers).json()
    assert detail["name"] == "李四"
    assert detail["phone"] == phone                     # 详情页不脱敏
    assert detail["files"][0]["status"] == "success"
    assert detail["files"][0]["parser"] == "python-docx"
    assert detail["structured"]["basic"]["phone"] == phone
    # 测试环境 LLM_MOCK=true，抽取走规则兜底，置信度会被压到 ≤0.55
    assert 0 < detail["field_confidence"]["phone"] <= 0.6
    assert detail["parser_meta"]["extract"]["source"] == "rule"


def test_upload_docx_with_textboxes(client):
    """Word 简历常用文本框排版，python-docx 读不到正文时要用 XML 兜底"""
    headers = _headers(client)
    phone = "13966667777"
    data = _docx_textbox(
        "文本框简历",
        f"手机：{phone}",
        "邮箱：textbox.test@example.com",
        "工作经历：某科技公司 | 后端工程师 | 2023-07 ~ 至今",
        "技能：Python、MySQL",
    )

    item = _upload_one(client, headers, "文本框简历.docx", data)
    assert item["status"] == "success", item
    assert item["candidate_id"]

    detail = client.get(f"{PREFIX}/candidates/{item['candidate_id']}", headers=headers).json()
    assert detail["files"][0]["status"] == "success"
    assert detail["files"][0]["parser"] == "docx-xml"
    assert "文本框简历" in (detail["plain_text"] or "")
    assert detail["structured"]["basic"]["phone"] == phone


def test_same_file_reused(client):
    headers = _headers(client)
    data = _resume("王五", "13933334444", skills="技能：Go")

    first = _upload_one(client, headers, "王五.docx", data)
    assert first["reused"] is False
    assert first["candidate_id"]

    second_resp = _upload(client, headers, "王五_副本.docx", data).json()["items"][0]
    assert second_resp["reused"] is True
    assert second_resp["file_id"] == first["file_id"]
    assert second_resp["candidate_id"] == first["candidate_id"]
    assert "复用" in (second_resp["message"] or "")

    detail = client.get(f"{PREFIX}/candidates/{first['candidate_id']}", headers=headers).json()
    assert len(detail["files"]) == 1


def test_bad_file_returns_failed_not_500(client):
    headers = _headers(client)
    resp = _upload(client, headers, "broken.pdf", b"this is not a pdf", "application/pdf")
    assert resp.status_code == 201, resp.text          # 不抛 500

    item = _resolve(client, headers, resp.json()["items"][0])
    assert item["status"] == "failed", item
    assert item["candidate_id"] is None
    assert item["error_reason"]
    assert "手动录入" in item["error_reason"]


def test_same_person_two_files_merged(client):
    headers = _headers(client)
    phone = "13955556666"

    a = _upload_one(client, headers, "赵六_v1.docx", _resume("赵六", phone, skills="技能：Python"))
    b = _upload_one(
        client, headers, "赵六_v2.docx",
        _resume("赵六", f"{phone[:3]}-{phone[3:7]}-{phone[7:]}", skills="技能：Redis"),
    )

    assert a["candidate_id"] == b["candidate_id"], (a, b)
    assert b["reused"] is False                        # 内容不同，不复用

    detail = client.get(f"{PREFIX}/candidates/{a['candidate_id']}", headers=headers).json()
    assert len(detail["files"]) == 2
    # 规则兜底不抽 skills，这里只验证"合并到同一个人 + 文件挂满 2 份"
    assert {f["status"] for f in detail["files"]} == {"success"}


def test_download_presigned_and_audited(client):
    headers = _headers(client)
    item = _upload_one(client, headers, "孙七.docx", _resume("孙七", "13977778888"))
    assert item["status"] == "success"

    before = _count("select count(*) from audit_log where action = 'resume.download'")
    resp = client.get(f"{PREFIX}/resume-files/{item['file_id']}/download", headers=headers)
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert body["expires_in"] == 600
    assert body["filename"] == "孙七.docx"

    # 本地存储模式返回后端代理地址；MinIO 模式返回对象存储预签名 URL
    if body["url"].startswith("http"):
        assert "X-Amz" in body["url"] or "http" in body["url"]
    else:
        assert body["url"].startswith("/api/v1/files/local/")
        file_resp = client.get(body["url"], headers=headers)
        assert file_resp.status_code == 200, file_resp.text
        assert len(file_resp.content) > 0

    after = _count("select count(*) from audit_log where action = 'resume.download'")
    assert after == before + 1


def test_list_is_masked(client):
    headers = _headers(client)
    _upload_one(
        client, headers, "周八.docx",
        _resume("周八", "13988889999", email="zhouba@example.com"),
    )

    items = client.get(f"{PREFIX}/candidates", headers=headers, params={"page_size": 100}).json()["items"]
    row = next((x for x in items if x["name"] == "周八"), None)
    assert row is not None
    assert row["phone"] and "****" in row["phone"]
    assert row["email"] and "***" in row["email"]


def test_update_candidate(client):
    headers = _headers(client)
    item = _upload_one(client, headers, "吴九.docx", _resume("吴九", "13900001111"))
    cid = item["candidate_id"]

    resp = client.put(
        f"{PREFIX}/candidates/{cid}",
        headers=headers,
        json={"name": "吴九（已校对）", "skills": ["Python", "Kubernetes"], "city": "杭州"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "吴九（已校对）"
    assert body["city"] == "杭州"
    assert set(body["skills"]) == {"Python", "Kubernetes"}


def test_unsupported_extension(client):
    headers = _headers(client)
    resp = _upload(client, headers, "简历.txt", b"plain text resume", "text/plain")
    assert resp.status_code == 201, resp.text
    item = resp.json()["items"][0]
    assert item["status"] == "failed"
    assert "不支持" in (item["message"] or "")
    assert item["file_id"] is None                     # 未落库


def test_reparse(client):
    headers = _headers(client)
    item = _upload_one(client, headers, "坏文件.pdf", b"broken content", "application/pdf")
    assert item["status"] == "failed"

    resp = client.post(f"{PREFIX}/resume-files/{item['file_id']}/reparse", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] in ("pending", "failed")

    assert _count(
        "select count(*) from audit_log where action = 'resume.reparse' and target_id = ?",
        (item["file_id"],),
    ) >= 1


# ---------------------------------------------------------------- 360° 概览
def _create_job(client, headers, title: str = "后端工程师") -> int:
    resp = client.post(
        f"{PREFIX}/jobs", headers=headers, json={"title": title, "department": "技术部"}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_candidate_overview(client):
    headers = _headers(client)
    item = _upload_one(client, headers, "郑十.docx", _resume("郑十", "13912344321"))
    cid = item["candidate_id"]
    job_id = _create_job(client, headers)

    application = client.post(
        f"{PREFIX}/applications",
        headers=headers,
        json={"job_id": job_id, "candidate_id": cid, "source": "upload"},
    )
    assert application.status_code == 201, application.text
    app_id = application.json()["id"]

    moved = client.post(
        f"{PREFIX}/applications/{app_id}/transition",
        headers=headers,
        json={"to_status": "screening", "note": "简历匹配度不错"},
    )
    assert moved.status_code == 200, moved.text

    matched = client.post(f"{PREFIX}/matching/jobs/{job_id}/match", headers=headers)
    assert matched.status_code == 200, matched.text

    resp = client.get(f"{PREFIX}/candidates/{cid}/overview", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # 档案详情仍然完整
    assert body["id"] == cid
    assert body["name"] == "郑十"
    assert body["files"][0]["status"] == "success"

    # 应聘记录
    assert len(body["applications"]) == 1
    app_out = body["applications"][0]
    assert app_out["job_id"] == job_id
    assert app_out["job_title"] == "后端工程师"
    assert app_out["department"] == "技术部"
    assert app_out["status"] == "screening"
    assert app_out["status_label"] == "筛选中"

    # 匹配结果（规则分，不需要 LLM）
    assert body["matches"], body["matches"]
    match = body["matches"][0]
    assert match["job_id"] == job_id
    assert match["job_title"] == "后端工程师"
    assert 0 <= match["score"] <= 100

    # 时间线覆盖建档 / 上传 / 加入流程 / 阶段流转，且按时间倒序
    kinds = {entry["kind"] for entry in body["timeline"]}
    assert {"candidate", "resume", "application", "stage"} <= kinds
    times = [entry["time"] for entry in body["timeline"]]
    assert times == sorted(times, reverse=True)


def test_overview_respects_candidate_scope(client):
    owner = _headers(client, "cv_owner")
    item = _upload_one(client, owner, "钱十一.docx", _resume("钱十一", "13922223333"))
    cid = item["candidate_id"]

    other = _headers(client, "cv_other")
    resp = client.get(f"{PREFIX}/candidates/{cid}/overview", headers=other)
    assert resp.status_code == 403

