import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.tools.youtube import play_youtube


class TestYouTubeTools:

    @pytest.mark.asyncio
    async def test_play_youtube_success(self, monkeypatch):
        fake_html = 'watch?v=SnXkhkEvNIM" title="Hikaru Nara Official"'
        with patch("urllib.request.urlopen") as mock_url, patch("webbrowser.open") as mock_browser:
            mock_resp = mock_url.return_value.__enter__.return_value
            mock_resp.read.return_value = fake_html.encode("utf-8")

            res = await play_youtube("Hikaru Nara Goose House")
            assert res.startswith("OK")
            assert "SnXkhkEvNIM" in res
            assert "autoplay=1" in res
            mock_browser.assert_called_once()
            args, _ = mock_browser.call_args
            assert "https://www.youtube.com/watch?v=SnXkhkEvNIM&autoplay=1" in args[0]

    @pytest.mark.asyncio
    async def test_play_youtube_music_platform(self, monkeypatch):
        fake_html = 'watch?v=SnXkhkEvNIM'
        with patch("urllib.request.urlopen") as mock_url, patch("webbrowser.open") as mock_browser:
            mock_resp = mock_url.return_value.__enter__.return_value
            mock_resp.read.return_value = fake_html.encode("utf-8")

            res = await play_youtube("Hikaru Nara", platform="music")
            assert res.startswith("OK")
            assert "music.youtube.com" in res
            mock_browser.assert_called_once()
            args, _ = mock_browser.call_args
            assert "https://music.youtube.com/watch?v=SnXkhkEvNIM" in args[0]

    @pytest.mark.asyncio
    async def test_play_youtube_empty_query(self, monkeypatch):
        with patch("webbrowser.open") as mock_browser:
            res = await play_youtube("")
            assert res.startswith("OK")
            mock_browser.assert_called_once_with("https://www.youtube.com")

    @pytest.mark.asyncio
    async def test_play_youtube_fallback_on_network_error(self, monkeypatch):
        with patch("urllib.request.urlopen", side_effect=Exception("Timeout")), patch("webbrowser.open") as mock_browser:
            res = await play_youtube("Lofi Girl")
            assert res.startswith("OK")
            assert "results?search_query=" in res
            mock_browser.assert_called_once()
