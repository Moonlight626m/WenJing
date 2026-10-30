"""开放版权图片检索 adapter 测试（issue #44 / ADR-0005 §6）。

- 工厂与端口形状（无外部依赖）。
- Openverse / Wikimedia：mock 响应映射、许可字段、SSRF/content-type/超时降级。
- 真实链路 key-gated 冒烟：`WENJING_TEST_IMAGE_SEARCH=1` 时执行（无需 key）。
"""

from __future__ import annotations

import os

import httpx
import pytest

from app.domain.game.media import ImageSearchPort
from app.infrastructure.config import Settings
from app.infrastructure.errx import Error, codes, match_code
from app.infrastructure.media import (
    NullImageSearch,
    OpenverseImageSearch,
    WikimediaImageSearch,
    build_image_search,
)
from app.infrastructure.media.image_search_common import build_image_fetcher

_REQUIRE_NETWORK = os.environ.get("WENJING_TEST_IMAGE_SEARCH") == "1"

_IMAGE_BYTES = b"\x89PNG\r\n\x1a\nfake-image-bytes"


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _allow_all(_url: str) -> None:
    return None


def _image_response(_req: httpx.Request) -> httpx.Response:
    return httpx.Response(200, headers={"content-type": "image/jpeg"}, content=_IMAGE_BYTES)


# ===== 工厂 =====


def test_build_image_search_null_by_default():
    search = build_image_search(Settings(media_image_search_provider="null"))
    assert isinstance(search, NullImageSearch)


def test_build_image_search_openverse_and_wikimedia_satisfy_port():
    openverse = build_image_search(Settings(media_image_search_provider="openverse"))
    wikimedia = build_image_search(Settings(media_image_search_provider="wikimedia"))
    assert isinstance(openverse, OpenverseImageSearch)
    assert isinstance(wikimedia, WikimediaImageSearch)
    assert isinstance(openverse, ImageSearchPort)
    assert isinstance(wikimedia, ImageSearchPort)


# ===== SafeImageFetcher 安全边界 =====


async def test_fetcher_blocks_private_target():
    fetcher = build_image_fetcher(client=_mock_client(_image_response))
    with pytest.raises(Error) as excinfo:
        await fetcher.fetch("http://169.254.169.254/latest/meta-data/")
    assert match_code(excinfo.value, codes.MEDIA_SEARCH_BLOCKED)


async def test_fetcher_rejects_non_image_content_type():
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html>")

    fetcher = build_image_fetcher(client=_mock_client(handler), validator=_allow_all)
    with pytest.raises(Error) as excinfo:
        await fetcher.fetch("https://example.com/a")
    assert match_code(excinfo.value, codes.MEDIA_SEARCH_FAILED)


async def test_fetcher_rejects_missing_content_type():
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_IMAGE_BYTES)

    fetcher = build_image_fetcher(client=_mock_client(handler), validator=_allow_all)
    with pytest.raises(Error) as excinfo:
        await fetcher.fetch("https://example.com/no-type.jpg")
    assert match_code(excinfo.value, codes.MEDIA_SEARCH_FAILED)


async def test_fetcher_rejects_oversized_body():
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "image/png"}, content=b"x" * 64)

    fetcher = build_image_fetcher(
        client=_mock_client(handler), validator=_allow_all, max_bytes=16
    )
    with pytest.raises(Error) as excinfo:
        await fetcher.fetch("https://example.com/big.png")
    assert match_code(excinfo.value, codes.MEDIA_SEARCH_FAILED)


async def test_fetcher_revalidates_redirect_target():
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/start":
            return httpx.Response(302, headers={"location": "http://127.0.0.1/secret"})
        return _image_response(req)

    def validator(url: str) -> None:
        if "127.0.0.1" in url:
            raise ValueError("blocked target")

    fetcher = build_image_fetcher(client=_mock_client(handler), validator=validator)
    with pytest.raises(Error) as excinfo:
        await fetcher.fetch("https://example.com/start")
    assert match_code(excinfo.value, codes.MEDIA_SEARCH_BLOCKED)


async def test_fetcher_timeout_maps_to_media_search_timeout():
    def handler(_req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("boom")

    fetcher = build_image_fetcher(client=_mock_client(handler), validator=_allow_all)
    with pytest.raises(Error) as excinfo:
        await fetcher.fetch("https://example.com/slow.jpg")
    assert match_code(excinfo.value, codes.MEDIA_SEARCH_TIMEOUT)


# ===== Openverse =====


_OPENVERSE_RESULTS = {
    "results": [
        {
            "url": "https://cdn.example.com/a.jpg",
            "thumbnail": "https://cdn.example.com/a-thumb.jpg",
            "foreign_landing_url": "https://openverse.example/a",
            "license": "cc0",
            "license_version": "1.0",
            "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
            "creator": "Alice",
            "width": 1600,
            "height": 900,
        },
        {
            "url": "https://cdn.example.com/b.jpg",
            "foreign_landing_url": "https://openverse.example/b",
            "license": "by-sa",
            "license_version": "4.0",
            "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
            "creator": "Bob",
            "width": 1200,
            "height": 800,
        },
    ]
}


def _openverse_handler(req: httpx.Request) -> httpx.Response:
    if req.url.host == "api.openverse.org":
        return httpx.Response(200, json=_OPENVERSE_RESULTS)
    return _image_response(req)


async def test_openverse_maps_candidates_with_license():
    search = OpenverseImageSearch(
        client=_mock_client(_openverse_handler), validator=_allow_all
    )
    candidates = await search.search(query="ancient castle", limit=2)
    assert len(candidates) == 2

    first = candidates[0]
    assert first.image_bytes == _IMAGE_BYTES
    assert first.content_type == "image/jpeg"
    assert first.width == 1600 and first.height == 900
    assert first.source_url == "https://openverse.example/a"
    assert first.credit.author == "Alice"
    assert first.credit.license == "CC0 1.0"
    assert first.credit.license_url.endswith("zero/1.0/")
    assert candidates[1].credit.license == "BY-SA 4.0"


async def test_openverse_skips_blocked_candidate_but_keeps_others():
    def validator(url: str) -> None:
        if "b.jpg" in url:
            raise ValueError("blocked target")

    search = OpenverseImageSearch(
        client=_mock_client(_openverse_handler), validator=validator
    )
    candidates = await search.search(query="castle", limit=2)
    assert [c.source_url for c in candidates] == ["https://openverse.example/a"]


async def test_openverse_http_error_raises_media_search_failed():
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable")

    search = OpenverseImageSearch(client=_mock_client(handler), validator=_allow_all)
    with pytest.raises(Error) as excinfo:
        await search.search(query="castle")
    assert match_code(excinfo.value, codes.MEDIA_SEARCH_FAILED)


async def test_openverse_invalid_json_raises_media_search_failed():
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-json", headers={"content-type": "application/json"})

    search = OpenverseImageSearch(client=_mock_client(handler), validator=_allow_all)
    with pytest.raises(Error) as excinfo:
        await search.search(query="castle")
    assert match_code(excinfo.value, codes.MEDIA_SEARCH_FAILED)


async def test_openverse_timeout_raises_media_search_timeout():
    def handler(_req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    search = OpenverseImageSearch(client=_mock_client(handler), validator=_allow_all)
    with pytest.raises(Error) as excinfo:
        await search.search(query="castle")
    assert match_code(excinfo.value, codes.MEDIA_SEARCH_TIMEOUT)


# ===== Wikimedia =====


_WIKIMEDIA_RESPONSE = {
    "query": {
        "pages": [
            {
                "title": "File:Castle.jpg",
                "imageinfo": [
                    {
                        "url": "https://upload.example.com/castle.jpg",
                        "thumburl": "https://upload.example.com/thumb/castle.jpg",
                        "descriptionurl": "https://commons.wikimedia.org/wiki/File:Castle.jpg",
                        "width": 2000,
                        "height": 1200,
                        "thumbwidth": 1280,
                        "thumbheight": 768,
                        "extmetadata": {
                            "LicenseShortName": {"value": "CC BY-SA 4.0"},
                            "LicenseUrl": {
                                "value": "https://creativecommons.org/licenses/by-sa/4.0/"
                            },
                            "Artist": {"value": '<a href="https://x">Zhang San</a>'},
                        },
                    }
                ],
            },
            {"title": "File:NoImage.jpg", "imageinfo": []},
        ]
    }
}


def _wikimedia_handler(req: httpx.Request) -> httpx.Response:
    if req.url.host == "commons.wikimedia.org":
        return httpx.Response(200, json=_WIKIMEDIA_RESPONSE)
    return _image_response(req)


async def test_wikimedia_maps_candidate_and_strips_html_artist():
    search = WikimediaImageSearch(
        client=_mock_client(_wikimedia_handler), validator=_allow_all
    )
    candidates = await search.search(query="castle", limit=4)
    assert len(candidates) == 1

    candidate = candidates[0]
    assert candidate.image_bytes == _IMAGE_BYTES
    assert candidate.content_type == "image/jpeg"
    # 下载的是 thumburl（1280px），尺寸须与字节一致而非原始尺寸
    assert candidate.width == 1280 and candidate.height == 768
    assert candidate.source_url == "https://commons.wikimedia.org/wiki/File:Castle.jpg"
    assert candidate.credit.author == "Zhang San"
    assert candidate.credit.license == "CC BY-SA 4.0"
    assert candidate.credit.license_url.endswith("by-sa/4.0/")


async def test_wikimedia_http_error_raises_media_search_failed():
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    search = WikimediaImageSearch(client=_mock_client(handler), validator=_allow_all)
    with pytest.raises(Error) as excinfo:
        await search.search(query="castle")
    assert match_code(excinfo.value, codes.MEDIA_SEARCH_FAILED)


async def test_wikimedia_timeout_raises_media_search_timeout():
    def handler(_req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    search = WikimediaImageSearch(client=_mock_client(handler), validator=_allow_all)
    with pytest.raises(Error) as excinfo:
        await search.search(query="castle")
    assert match_code(excinfo.value, codes.MEDIA_SEARCH_TIMEOUT)


# ===== 真实链路 key-gated 冒烟（无需 key，需显式开启）=====


@pytest.mark.skipif(not _REQUIRE_NETWORK, reason="set WENJING_TEST_IMAGE_SEARCH=1")
async def test_openverse_real_smoke():
    search = OpenverseImageSearch()
    try:
        candidates = await search.search(query="ancient chinese castle", limit=2)
    finally:
        await search.close()
    assert candidates, "Openverse 真实检索应至少返回一条候选"
    assert candidates[0].credit.license, "候选必须携带许可字段"


@pytest.mark.skipif(not _REQUIRE_NETWORK, reason="set WENJING_TEST_IMAGE_SEARCH=1")
async def test_wikimedia_real_smoke():
    search = WikimediaImageSearch()
    try:
        candidates = await search.search(query="Great Wall", limit=2)
    finally:
        await search.close()
    assert candidates, "Wikimedia 真实检索应至少返回一条候选"
    assert candidates[0].credit.license, "候选必须携带许可字段"
