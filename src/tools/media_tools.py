"""
Media playback tools: play_music, pause_music, skip_track.

Spotify playback uses two strategies, in priority order:

  Strategy A — Spotify Web API (spotipy)
    Requires a one-time setup in config/settings.yaml:
      spotify:
        client_id: "your_client_id"
        client_secret: "your_client_secret"
        redirect_uri: "http://localhost:8888/callback"

    Get credentials at: https://developer.spotify.com/dashboard
    First run will open a browser for OAuth — token is then cached.
    This strategy actually starts playback on your active device.

  Strategy B — URI + keyboard automation (fallback, no setup needed)
    Opens the Spotify app via the `spotify:search:` URI,
    then waits 2 seconds and sends Enter to auto-play the first result.
    Works best when Spotify is already running.
"""

from __future__ import annotations

import os
import subprocess
import platform
import time
import urllib.parse
import webbrowser
from pathlib import Path

from src.tools.base import PermissionLevel, ToolParameter, ToolResult
from src.tools.registry import register
from src.utils.logger import get_logger

logger = get_logger("tools.media")

# ─── Spotify API (spotipy) ────────────────────────────────────────────────────

def _get_spotipy_client():
    """
    Try to build an authenticated spotipy client.
    Returns None if spotipy is not installed or credentials are not configured.
    """
    try:
        import spotipy
        from spotipy.oauth2 import SpotifyOAuth
    except ImportError:
        return None

    # Read credentials from environment variables first, then try config
    client_id = os.environ.get("SPOTIFY_CLIENT_ID")
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET")
    redirect_uri = os.environ.get("SPOTIFY_REDIRECT_URI", "http://localhost:8888/callback")

    # Try settings.yaml as fallback
    if not (client_id and client_secret):
        try:
            import yaml
            config_path = Path("config/settings.yaml")
            if config_path.exists():
                with open(config_path) as f:
                    cfg = yaml.safe_load(f) or {}
                spotify_cfg = cfg.get("spotify", {})
                client_id = client_id or spotify_cfg.get("client_id")
                client_secret = client_secret or spotify_cfg.get("client_secret")
                redirect_uri = spotify_cfg.get("redirect_uri", redirect_uri)
        except Exception:
            pass

    if not (client_id and client_secret):
        return None

    try:
        auth = SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scope="user-modify-playback-state user-read-playback-state user-read-currently-playing user-library-read",
            open_browser=True,
            cache_path=".spotify_token_cache",
        )
        return spotipy.Spotify(auth_manager=auth)
    except Exception as e:
        logger.warning(f"Spotipy auth failed: {e}")
        return None


def _play_via_api(query: str) -> ToolResult:
    """Play music using the Spotify Web API."""
    sp = _get_spotipy_client()
    if sp is None:
        return ToolResult(success=False, error="Spotify API not configured")

    try:
        # Check for Liked Songs / Favorites
        query_lower = query.lower().strip()
        is_liked = any(
            x in query_lower 
            for x in ("liked song", "favorite", "favourite", "my likes")
        )

        if is_liked:
            # Fetch user's saved tracks
            saved = sp.current_user_saved_tracks(limit=30)
            items = saved.get("items", [])
            if not items:
                return ToolResult(
                    success=False, 
                    error="No liked songs found",
                    message="You don't have any saved/liked tracks on Spotify."
                )
            uris = [item["track"]["uri"] for item in items]
            
            devices = sp.devices()
            device_list = devices.get("devices", [])
            if not device_list:
                return ToolResult(
                    success=False,
                    error="No active Spotify device found",
                    message="Please open Spotify on any device first, then try again.",
                )
            active = next((d for d in device_list if d["is_active"]), device_list[0])
            device_id = active["id"]

            sp.start_playback(device_id=device_id, uris=uris)
            return ToolResult(
                success=True,
                message="Playing your Liked Songs.",
                data={"type": "liked_songs", "count": len(uris)}
            )

        # Normal Search
        results = sp.search(q=query, limit=5, type="track,artist,album,playlist")

        # Try tracks first
        tracks = results.get("tracks", {}).get("items", [])
        if tracks:
            track = tracks[0]
            track_uri = track["uri"]
            track_name = track["name"]
            artist_name = track["artists"][0]["name"]

            # Get active device
            devices = sp.devices()
            device_list = devices.get("devices", [])

            if not device_list:
                return ToolResult(
                    success=False,
                    error="No active Spotify device found",
                    message="Please open Spotify on any device first, then try again.",
                )

            # Prefer active device, otherwise use first available
            active = next((d for d in device_list if d["is_active"]), device_list[0])
            device_id = active["id"]

            sp.start_playback(device_id=device_id, uris=[track_uri])
            return ToolResult(
                success=True,
                message=f"Now playing: {track_name} by {artist_name}",
                data={"track": track_name, "artist": artist_name, "uri": track_uri},
            )

        return ToolResult(
            success=False,
            error=f"No tracks found for: {query}",
            message=f"Couldn't find '{query}' on Spotify.",
        )

    except Exception as e:
        return ToolResult(success=False, error=f"{type(e).__name__}: {e}")


def _play_via_uri_keyboard(query: str) -> ToolResult:
    """
    Fallback: open Spotify search URI, wait, then press Enter to auto-play.
    Works on Windows when Spotify desktop app is installed.
    """
    if platform.system() != "Windows":
        return ToolResult(success=False, error="URI fallback is Windows-only")

    encoded = urllib.parse.quote(query)
    spotify_uri = f"spotify:search:{encoded}"

    try:
        subprocess.Popen(["start", "", spotify_uri], shell=True)
    except Exception as e:
        return ToolResult(success=False, error=f"Could not launch Spotify: {e}")

    # Wait for Spotify to open and search, then press Enter to play first result
    time.sleep(2.5)

    ps_enter = """
Add-Type -AssemblyName Microsoft.VisualBasic
Start-Sleep -Milliseconds 500
[Microsoft.VisualBasic.Interaction]::AppActivate("Spotify")
Start-Sleep -Milliseconds 300
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.SendKeys]::SendWait("{ENTER}")
"""
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_enter],
            capture_output=True,
            timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return ToolResult(
            success=True,
            message=f"Playing: {query}",
            data={"query": query, "method": "uri_keyboard"},
        )
    except Exception as e:
        return ToolResult(
            success=True,  # Spotify was opened at least
            message=f"Opened Spotify search for: {query} (press Enter in Spotify to play)",
            data={"query": query, "method": "uri_only"},
        )


# ─── Registered Tools ────────────────────────────────────────────────────────

@register(
    name="play_music",
    description="Play a song, artist, album, or playlist on Spotify",
    permission=PermissionLevel.SAFE,
    category="media",
    parameters=[
        ToolParameter(
            name="query",
            type="string",
            description="What to play — song name, artist, playlist, or genre",
        ),
    ],
)
def play_music(query: str) -> ToolResult:
    """Play music via Spotify — tries Web API first, then URI + keyboard fallback."""
    query = query.strip()
    if not query:
        return ToolResult(success=False, error="Empty query", message="What would you like me to play?")

    # Strategy A: Spotify Web API (actually starts playback)
    api_result = _play_via_api(query)
    if api_result.success:
        return api_result

    # Log why API failed (if it was configured but errored)
    if "not configured" not in (api_result.error or ""):
        logger.warning(f"Spotify API failed ({api_result.error}), falling back to URI method")

    # Strategy B: URI + keyboard automation
    return _play_via_uri_keyboard(query)


def _send_media_key(vk_code: int) -> None:
    """Send hardware media key instantly via Win32 keybd_event (<0.01ms, 0 subprocesses)."""
    if platform.system() == "Windows":
        try:
            import ctypes
            KEYEVENTF_KEYUP = 0x0002
            ctypes.windll.user32.keybd_event(vk_code, 0, 0, 0)
            ctypes.windll.user32.keybd_event(vk_code, 0, KEYEVENTF_KEYUP, 0)
        except Exception as e:
            logger.warning(f"Failed to send media key {vk_code}: {e}")


# ─── Registered Tools ────────────────────────────────────────────────────────

@register(
    name="play_music",
    description="Play a song, artist, album, or playlist on Spotify",
    permission=PermissionLevel.SAFE,
    category="media",
    parameters=[
        ToolParameter(
            name="query",
            type="string",
            description="What to play — song name, artist, playlist, or genre",
        ),
    ],
)
def play_music(query: str) -> ToolResult:
    """Play music via Spotify — tries Web API first, then URI + keyboard fallback."""
    query = query.strip()
    if not query:
        return ToolResult(success=False, error="Empty query", message="What would you like me to play?")

    # Strategy A: Spotify Web API (actually starts playback)
    api_result = _play_via_api(query)
    if api_result.success:
        return api_result

    # Log why API failed (if it was configured but errored)
    if "not configured" not in (api_result.error or ""):
        logger.warning(f"Spotify API failed ({api_result.error}), falling back to URI method")

    # Strategy B: URI + keyboard automation
    return _play_via_uri_keyboard(query)


@register(
    name="pause_music",
    description="Pause the currently playing music or media",
    permission=PermissionLevel.SAFE,
    category="media",
)
def pause_music() -> ToolResult:
    """Pause playback via Spotify API first, then Win32 media key fallback."""
    sp = _get_spotipy_client()
    if sp:
        try:
            playback = sp.current_playback()
            if playback and playback.get("is_playing"):
                sp.pause_playback()
                return ToolResult(success=True, message="Music paused.")
        except Exception as e:
            logger.warning(f"Spotify API pause failed: {e}, falling back to media key")

    # Fallback: send Play/Pause media key (0xB3)
    _send_media_key(0xB3)
    return ToolResult(success=True, message="Music paused.")


@register(
    name="resume_music",
    description="Resume or unpause playback of music or media",
    permission=PermissionLevel.SAFE,
    category="media",
)
def resume_music() -> ToolResult:
    """Resume playback via Spotify API first, then Win32 media key fallback."""
    sp = _get_spotipy_client()
    if sp:
        try:
            playback = sp.current_playback()
            if playback and not playback.get("is_playing"):
                sp.start_playback()
                return ToolResult(success=True, message="Music resumed.")
        except Exception as e:
            logger.warning(f"Spotify API resume failed: {e}, falling back to media key")

    # Fallback: send Play/Pause media key (0xB3)
    _send_media_key(0xB3)
    return ToolResult(success=True, message="Music resumed.")


@register(
    name="skip_track",
    description="Skip to the next song or track",
    permission=PermissionLevel.SAFE,
    category="media",
)
def skip_track() -> ToolResult:
    """Skip via Spotify API first, then Next Track media key fallback."""
    sp = _get_spotipy_client()
    if sp:
        try:
            sp.next_track()
            return ToolResult(success=True, message="Skipped to next track.")
        except Exception as e:
            logger.warning(f"Spotify API skip failed: {e}, falling back to media key")

    # Fallback: Next Track key (0xB0)
    _send_media_key(0xB0)
    return ToolResult(success=True, message="Skipped to next track.")


@register(
    name="previous_track",
    description="Go back to the previous song or track",
    permission=PermissionLevel.SAFE,
    category="media",
)
def previous_track() -> ToolResult:
    """Previous track via Spotify API first, then Prev Track media key fallback."""
    sp = _get_spotipy_client()
    if sp:
        try:
            sp.previous_track()
            return ToolResult(success=True, message="Playing previous track.")
        except Exception as e:
            logger.warning(f"Spotify API previous track failed: {e}, falling back to media key")

    # Fallback: Prev Track key (0xB1)
    _send_media_key(0xB1)
    return ToolResult(success=True, message="Playing previous track.")


@register(
    name="get_current_track",
    description="Check what song or music is currently playing",
    permission=PermissionLevel.SAFE,
    category="media",
)
def get_current_track() -> ToolResult:
    """Check currently playing song via Spotify API."""
    sp = _get_spotipy_client()
    if sp:
        try:
            item = sp.currently_playing()
            if item and item.get("item"):
                track = item["item"]
                title = track.get("name", "Unknown Track")
                artists = ", ".join(a.get("name", "") for a in track.get("artists", []))
                is_playing = item.get("is_playing", False)
                status = "Now playing" if is_playing else "Paused"
                return ToolResult(
                    success=True,
                    message=f"{status}: {title} by {artists}.",
                    data={"title": title, "artists": artists, "is_playing": is_playing},
                )
        except Exception as e:
            logger.warning(f"Spotify currently playing query failed: {e}")

    return ToolResult(
        success=True,
        message="I couldn't identify the currently playing track. Make sure Spotify is active.",
    )

