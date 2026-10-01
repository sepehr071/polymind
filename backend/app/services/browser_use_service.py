import os
import requests
from typing import Optional


class BrowserUseService:
    """Thin REST client for browser-use Cloud API v3."""

    BASE_URL = "https://api.browser-use.com/api/v3"

    @staticmethod
    def get_headers() -> dict:
        api_key = os.environ.get("BROWSER_USE_API_KEY", "")
        return {
            "X-Browser-Use-API-Key": api_key,
            "Content-Type": "application/json",
        }

    @staticmethod
    def create_session(task: str, model: str = "claude-sonnet-4.6") -> dict:
        """Create a new browser-use session for the given task.

        Returns dict with at least: id, status, live_url.
        """
        try:
            resp = requests.post(
                f"{BrowserUseService.BASE_URL}/sessions",
                headers=BrowserUseService.get_headers(),
                json={"task": task, "model": model},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            live_url = (
                data.get("live_url")
                or data.get("liveUrl")
                or data.get("live_session_url")
                or data.get("session_url")
            )
            data["live_url"] = live_url
            return data
        except requests.RequestException as e:
            raise Exception(f"BrowserUse create_session failed: {e}") from e

    @staticmethod
    def get_session(session_id: str) -> dict:
        """Fetch current state of a session."""
        try:
            resp = requests.get(
                f"{BrowserUseService.BASE_URL}/sessions/{session_id}",
                headers=BrowserUseService.get_headers(),
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            live_url = (
                data.get("live_url")
                or data.get("liveUrl")
                or data.get("live_session_url")
                or data.get("session_url")
            )
            data["live_url"] = live_url
            return data
        except requests.RequestException as e:
            raise Exception(f"BrowserUse get_session failed: {e}") from e

    @staticmethod
    def list_messages(
        session_id: str,
        after: Optional[str] = None,
        limit: int = 100,
    ) -> dict:
        """Cursor-paginated messages for a session.

        Returns dict with key 'messages' (list).
        """
        params: dict = {"limit": limit}
        if after:
            params["after"] = after
        try:
            resp = requests.get(
                f"{BrowserUseService.BASE_URL}/sessions/{session_id}/messages",
                headers=BrowserUseService.get_headers(),
                params=params,
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            raise Exception(f"BrowserUse list_messages failed: {e}") from e

    @staticmethod
    def stop_session(session_id: str, strategy: str = "task") -> dict:
        """Stop a session.

        strategy='task'    — cancel current task, keep session alive.
        strategy='session' — hard destroy (use on DELETE).
        """
        try:
            resp = requests.post(
                f"{BrowserUseService.BASE_URL}/sessions/{session_id}/stop",
                headers=BrowserUseService.get_headers(),
                json={"strategy": strategy},
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            raise Exception(f"BrowserUse stop_session failed: {e}") from e
