import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.tools.spotify import play_spotify, pause_spotify, next_spotify


class TestSpotifyTools:

    @pytest.mark.asyncio
    async def test_play_spotify_missing_credentials(self, monkeypatch):
        monkeypatch.delenv("SPOTIPY_CLIENT_ID", raising=False)
        monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
        monkeypatch.delenv("SPOTIPY_CLIENT_SECRET", raising=False)
        monkeypatch.delenv("SPOTIFY_CLIENT_SECRET", raising=False)

        res = await play_spotify("Hikaru Nara")
        assert "ERROR" in res
        assert "Kredensial Spotify belum dikonfigurasi" in res

    @pytest.mark.asyncio
    async def test_play_spotify_success(self, monkeypatch):
        fake_sp = MagicMock()
        fake_sp.devices.return_value = {
            "devices": [{"id": "dev_123", "name": "PC", "is_active": True}]
        }
        fake_sp.search.return_value = {
            "tracks": {
                "items": [
                    {
                        "name": "Hikaru Nara",
                        "artists": [{"name": "Goose house"}],
                        "uri": "spotify:track:12345",
                    }
                ]
            }
        }

        with patch("agent.tools.spotify._get_spotify_client", return_value=(fake_sp, None)):
            res = await play_spotify("Hikaru Nara Goose House")
            assert res.startswith("OK")
            assert "Hikaru Nara" in res
            assert "Goose house" in res
            fake_sp.start_playback.assert_called_once_with(
                device_id="dev_123", uris=["spotify:track:12345"]
            )

    @pytest.mark.asyncio
    async def test_play_spotify_resume(self, monkeypatch):
        fake_sp = MagicMock()
        fake_sp.devices.return_value = {
            "devices": [{"id": "dev_123", "name": "PC", "is_active": True}]
        }

        with patch("agent.tools.spotify._get_spotify_client", return_value=(fake_sp, None)):
            res = await play_spotify("")
            assert res.startswith("OK")
            assert "Melanjutkan pemutaran" in res
            fake_sp.start_playback.assert_called_once_with(device_id="dev_123")

    @pytest.mark.asyncio
    async def test_pause_spotify_success(self, monkeypatch):
        fake_sp = MagicMock()
        fake_sp.devices.return_value = {
            "devices": [{"id": "dev_123", "name": "PC", "is_active": True}]
        }

        with patch("agent.tools.spotify._get_spotify_client", return_value=(fake_sp, None)):
            res = await pause_spotify()
            assert res.startswith("OK")
            assert "dijeda" in res
            fake_sp.pause_playback.assert_called_once_with(device_id="dev_123")

    @pytest.mark.asyncio
    async def test_next_spotify_success(self, monkeypatch):
        fake_sp = MagicMock()
        fake_sp.devices.return_value = {
            "devices": [{"id": "dev_123", "name": "PC", "is_active": True}]
        }

        with patch("agent.tools.spotify._get_spotify_client", return_value=(fake_sp, None)):
            res = await next_spotify()
            assert res.startswith("OK")
            assert "berikutnya" in res
            fake_sp.next_track.assert_called_once_with(device_id="dev_123")

    @pytest.mark.asyncio
    async def test_play_spotify_no_devices(self, monkeypatch):
        fake_sp = MagicMock()
        fake_sp.devices.return_value = {"devices": []}

        with patch("agent.tools.spotify._get_spotify_client", return_value=(fake_sp, None)):
            res = await play_spotify("Hikaru Nara")
            assert "ERROR" in res
            assert "Tidak ada perangkat Spotify" in res
