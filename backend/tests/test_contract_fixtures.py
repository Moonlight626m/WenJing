"""Shared Contracts fixture 同步测试：前后端共享同一份契约 fixtures。

对应 ticket #2 验收：
- 后端与前端共享同一份 contract fixtures（样例材料/剧本/命令/事件/消息）
- 契约一致性测试通过：fixture 与前后端类型同步断言

规则：
- `contracts/fixtures/*.json` 是权威 fixture，任何样例数据只允许改这里。
- `frontend/src/lib/contracts/fixtures/*.json` 是前端逐字节副本，供 TS 类型检查使用。
- 本测试三向断言：fixture 可解析到后端契约、manifest 与契约导出对齐、前端副本与权威逐字节一致。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.contracts import (
    DomainEvent,
    ErrorEnvelope,
    Material,
    MaterialInput,
    PlayerCommand,
    RuntimeState,
    RuntimeUpdate,
    ScriptPackage,
)
from app.contracts.protocol import RuntimeView, SessionView

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO_ROOT / "contracts" / "fixtures"
FRONTEND_FIXTURES_DIR = REPO_ROOT / "frontend" / "src" / "lib" / "contracts" / "fixtures"
MANIFEST_PATH = REPO_ROOT / "contracts" / "manifest.json"
# manifest 中每个契约名 → 对应的 Pydantic 模型（fixture 解析用）
FIXTURE_MODELS = {
    "MaterialInput": MaterialInput,
    "Material": Material,
    "ScriptPackage": ScriptPackage,
    "PlayerCommand": PlayerCommand,
    "DomainEvent": DomainEvent,
    "RuntimeState": RuntimeState,
    "RuntimeUpdate": RuntimeUpdate,
    "ErrorEnvelope": ErrorEnvelope,
    "SessionView": SessionView,
    "RuntimeView": RuntimeView,
}


def _load_fixture(name: str) -> dict:
    path = FIXTURES_DIR / name
    assert path.exists(), f"缺失权威 fixture: {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def test_manifest_lists_expected_contracts():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    names = {entry["name"] for entry in manifest["contracts"]}
    assert names == set(FIXTURE_MODELS)


def test_manifest_entries_exported_from_contracts_package():
    import app.contracts as contracts

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    for entry in manifest["contracts"]:
        assert hasattr(contracts, entry["name"]), f"契约 {entry['name']} 未从 app.contracts 导出"


def test_every_manifest_fixture_parses_into_its_contract():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    for entry in manifest["contracts"]:
        model = FIXTURE_MODELS[entry["name"]]
        fixture = _load_fixture(entry["fixture"])
        parsed = model.model_validate(fixture)
        assert parsed.schema_version == entry["schema_version"], (
            f"{entry['name']} fixture schema_version 与 manifest 不一致"
        )


def test_fixture_files_match_manifest_set():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    defined = {entry["fixture"] for entry in manifest["contracts"]}
    on_disk = {p.name for p in FIXTURES_DIR.glob("*.json")}
    assert on_disk == defined, f"fixture 文件与 manifest 不一致: {on_disk ^ defined}"


def test_script_package_fixture_invariants():
    pkg = ScriptPackage.model_validate(_load_fixture("script_package.json"))
    names = {c.name for c in pkg.characters}
    assert set(pkg.player_playable_roles) <= names, "可扮演角色必须是 characters 中的成员"
    ending_ids = {b.beat_id for b in pkg.stage2_beats}
    assert pkg.stage2_ending_beat_id in ending_ids, "结局 beat 必须存在"
    for beat in pkg.stage2_beats:
        assert len(beat.evidence) >= 1, "每个 Stage2 关键 beat 必须带原文证据"
        assert all(e.source_type == "original" for e in beat.evidence), "Stage2 证据只接受原文"
    material = Material.model_validate(_load_fixture("material.json"))
    expected = hashlib.sha256(material.raw_text.encode("utf-8")).hexdigest()
    assert material.content_hash == expected


def test_frontend_fixture_copies_are_byte_identical():
    assert FRONTEND_FIXTURES_DIR.is_dir(), f"前端 fixture 目录缺失: {FRONTEND_FIXTURES_DIR}"
    for src in sorted(FIXTURES_DIR.glob("*.json")):
        dst = FRONTEND_FIXTURES_DIR / src.name
        assert dst.exists(), f"前端缺少 fixture 副本: {dst.name}"
        assert src.read_bytes() == dst.read_bytes(), f"前端副本与权威不一致: {src.name}"


def test_protocol_dto_fixtures_parse():
    """REST DTO 样例（session_view / runtime_view）必须可解析，供前端 mock 使用。"""
    from app.contracts.protocol import RuntimeView, SessionView

    for name, model in (("session_view.json", SessionView), ("runtime_view.json", RuntimeView)):
        path = FIXTURES_DIR / name
        assert path.exists(), f"缺失 DTO fixture: {path.name}"
        model.model_validate(json.loads(path.read_text(encoding="utf-8")))
