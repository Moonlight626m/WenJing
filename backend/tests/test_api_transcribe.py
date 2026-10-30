"""语音识别端点端到端（issue #64 / ADR-0005 §11）。

用假的 `AsrPort` 替掉容器里的空实现——验的是**端点契约与隐私边界**
（鉴权、大小上限、只回文本、失败给信封），不是 provider。

依赖真实 PG；不可用时沿用 `test_api_sessions` 的 client fixture skip。
"""

from __future__ import annotations

import pytest

from app.domain.game.asr import Transcript
from app.infrastructure.errx import codes, new
from tests.test_api_sessions import _csrf, _full_setup
from tests.test_api_sessions import client as _sessions_client  # noqa: F401


@pytest.fixture(scope="module")
def client(_sessions_client):  # noqa: F811 - 复用 test_api_sessions 的装配
    return _sessions_client


class _FakeAsr:
    def __init__(self, *, text: str = "我要去城里找父亲", fail: bool = False) -> None:
        self.calls: list[tuple[bytes, str]] = []
        self._text = text
        self._fail = fail

    async def transcribe(
        self, *, audio: bytes, content_type: str, language: str = ""
    ) -> Transcript:
        self.calls.append((audio, content_type))
        if self._fail:
            # 真实 adapter 抛的就是结构化错误码（`MEDIA_ASR_*`），不是裸异常
            raise new(codes.MEDIA_ASR_FAILED, extra={"reason": "provider down"})
        return Transcript(text=self._text, provider="fake", model="fake-1")

    async def aclose(self) -> None:
        return None


def _swap_asr(monkeypatch, fake: _FakeAsr) -> _FakeAsr:
    """换上假识别端口。

    **必须连编排器一起清掉**：`asr_transcriber` 是整体缓存的（配额要在进程内累积），
    只换 `_asr` 的话第一个用例建好的编排器会被后续用例继续用，替换静默失效。
    真实世界里这两者同生同灭（一次 lifespan 一组），测试里照做。
    """
    from app.composition import get_container

    container = get_container()
    monkeypatch.setattr(container, "_asr", fake)
    monkeypatch.setattr(container, "_asr_transcriber", None)
    return fake


@pytest.fixture
def fake_asr(monkeypatch):
    """把容器的识别端口换成假实现（用例结束自动还原）。"""
    return _swap_asr(monkeypatch, _FakeAsr())


def _post(client, sid: str, data: bytes = b"OggSfake", **form):  # noqa: ANN001, ANN003
    return client.post(
        f"/api/sessions/{sid}/transcribe",
        files={"audio": ("speech.webm", data, "audio/webm")},
        data={"duration_ms": "3000", **form},
        headers=_csrf(client),
    )


def test_transcription_returns_text_and_duration(client, fake_asr):  # noqa: ANN001
    """验收一：语音输入可用——一段音频换回一段文本。"""
    sid, _role = _full_setup(client)
    resp = _post(client, sid)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["text"] == "我要去城里找父亲"
    assert "duration_ms" in body
    assert fake_asr.calls == [(b"OggSfake", "audio/webm")]


def test_response_carries_no_audio_back(client, fake_asr):  # noqa: ANN001
    """隐私：录音**不落库也不回传**——响应里只有文本与时长。"""
    sid, _role = _full_setup(client)
    body = _post(client, sid).json()

    assert set(body) == {"schema_version", "text", "duration_ms"}


def test_empty_transcription_returns_an_envelope(client, monkeypatch):  # noqa: ANN001
    """没听清要给业务信封，前端才好提示改用键盘（验收三）。"""
    _swap_asr(monkeypatch, _FakeAsr(text="   "))
    sid, _role = _full_setup(client)
    resp = _post(client, sid)

    assert resp.status_code == 400
    assert resp.json()["code"] == "MEDIA_ASR_INVALID"


def test_provider_failure_returns_an_envelope(client, monkeypatch):  # noqa: ANN001
    """provider 挂了要给信封而不是 500——前端据此提示改用键盘（验收三）。"""
    _swap_asr(monkeypatch, _FakeAsr(fail=True))
    sid, _role = _full_setup(client)
    resp = _post(client, sid)

    assert resp.status_code >= 400
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.json()["code"]


def test_oversized_audio_is_rejected(client, fake_asr):  # noqa: ANN001
    """大小上限在**读全量之前**就拦住，别把内存交给调用方决定。"""
    sid, _role = _full_setup(client)
    resp = _post(client, sid, data=b"x" * (6 * 1024 * 1024))

    assert resp.status_code == 400
    assert resp.json()["code"] == "MEDIA_ASR_INVALID"
    assert fake_asr.calls == []


def test_unknown_session_is_404(client, fake_asr):  # noqa: ANN001
    ghost = "00000000-0000-0000-0000-000000000001"
    resp = _post(client, ghost)
    assert resp.status_code == 404
    assert resp.json()["code"] == "SESSION_NOT_FOUND"


def test_malformed_session_id_is_a_protocol_envelope(client, fake_asr):  # noqa: ANN001
    resp = _post(client, "not-a-uuid")
    assert resp.status_code == 400
    assert resp.json()["code"] == "PROTOCOL_MALFORMED_MESSAGE"


def test_other_users_session_is_forbidden(client, fake_asr):  # noqa: ANN001
    """权限：别人的会话不能借道识别端点花 org 的钱。

    会话是真实 PG 里的行，改 owner 得用应用自己的会话工厂（`SessionLocal`）。
    """
    import asyncio
    import uuid as _uuid

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.infrastructure.config import get_settings
    from app.infrastructure.models.session import Session as SessionRow
    from app.infrastructure.models.user import User

    sid, _role = _full_setup(client)

    async def _reassign() -> None:
        # 自建引擎而**不是**复用 `SessionLocal`：后者的连接池绑在 TestClient 的事件
        # 循环上，这里 `asyncio.run` 开的是新循环，复用会撞
        # "got Future attached to a different loop"。
        engine = create_async_engine(get_settings().database_url)
        try:
            async with async_sessionmaker(engine)() as db:
                row = await db.get(SessionRow, _uuid.UUID(sid))
                assert row is not None
                # owner 必须指向**真实存在**的另一个用户（FK 约束），随便编一个
                # uuid 会撞外键而不是撞权限；而这套装配默认只建一个账号，
                # 所以没有第二个就现造一个同 org 的学生。
                other = (
                    await db.execute(
                        select(User.id).where(User.id != row.owner_user_id).limit(1)
                    )
                ).scalar_one_or_none()
                if other is None:
                    other_user = User(
                        org_id=row.org_id,
                        role="student",
                        email=f"other-{_uuid.uuid4().hex[:12]}@example.test",
                        nickname="另一个学生",
                        password_hash="x",
                    )
                    db.add(other_user)
                    await db.flush()
                    other = other_user.id
                row.owner_user_id = other
                await db.commit()
        finally:
            await engine.dispose()

    asyncio.run(_reassign())

    resp = _post(client, sid)
    assert resp.status_code == 403
    assert resp.json()["code"] == "AUTH_FORBIDDEN"
    assert fake_asr.calls == []
