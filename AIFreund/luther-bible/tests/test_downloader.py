"""
test_downloader.py — Unit tests for luther_mcp.downloader.get_download_url

No network calls: urllib.request.urlopen is mocked.
"""

import json
from unittest.mock import MagicMock

import pytest


def _fake_response(body: dict):
    resp = MagicMock()
    resp.read.return_value = json.dumps(body).encode()
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


RELEASE_BODY = {
    "tag_name": "v1.0.0",
    "assets": [
        {
            "name": "bible_chroma_db.tar.gz",
            "browser_download_url": "https://example.com/bible_chroma_db.tar.gz",
        },
    ],
}


class TestGetDownloadUrl:
    def test_returns_asset_url(self, monkeypatch):
        from luther_mcp import downloader

        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        mock_urlopen = MagicMock(return_value=_fake_response(RELEASE_BODY))
        monkeypatch.setattr(downloader.urllib.request, "urlopen", mock_urlopen)

        url = downloader.get_download_url()
        assert url == "https://example.com/bible_chroma_db.tar.gz"

    def test_no_authorization_header_without_token(self, monkeypatch):
        from luther_mcp import downloader

        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        mock_urlopen = MagicMock(return_value=_fake_response(RELEASE_BODY))
        monkeypatch.setattr(downloader.urllib.request, "urlopen", mock_urlopen)

        downloader.get_download_url()
        sent_request = mock_urlopen.call_args[0][0]
        assert sent_request.get_header("Authorization") is None

    def test_sends_bearer_token_when_github_token_set(self, monkeypatch):
        # HF Spaces builds hit GitHub API's anonymous rate limit (60 req/hour
        # per IP), shared across many Spaces' builders. Authenticating with a
        # GITHUB_TOKEN raises that limit to 5000/hour.
        from luther_mcp import downloader

        monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret123")
        mock_urlopen = MagicMock(return_value=_fake_response(RELEASE_BODY))
        monkeypatch.setattr(downloader.urllib.request, "urlopen", mock_urlopen)

        downloader.get_download_url()
        sent_request = mock_urlopen.call_args[0][0]
        assert sent_request.get_header("Authorization") == "Bearer ghp_secret123"

    def test_raises_when_asset_missing(self, monkeypatch):
        from luther_mcp import downloader

        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        mock_urlopen = MagicMock(
            return_value=_fake_response({"tag_name": "v1.0.0", "assets": []})
        )
        monkeypatch.setattr(downloader.urllib.request, "urlopen", mock_urlopen)

        with pytest.raises(RuntimeError):
            downloader.get_download_url()
