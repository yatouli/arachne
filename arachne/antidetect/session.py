"""Session & cookie management across requests."""

from __future__ import annotations

from http.cookiejar import Cookie, CookieJar
from typing import Optional
from urllib.parse import urlparse
from urllib.request import Request

from ..exceptions import ArachneError


class CookieStore:
    """A minimal cookie jar keyed by domain.

    We don't reinvent cookie parsing: we delegate to the standard-library
    :class:`http.cookiejar.CookieJar` and only add per-session convenience.
    """

    def __init__(self):
        self._jar = CookieJar()

    def update_from_response(self, url: str, headers: dict[str, str]) -> None:
        set_cookie = headers.get("set-cookie")
        if set_cookie:
            # CookieJar.extract_cookies expects a response-like object.
            class _Resp:
                def __init__(self, headers):
                    self.headers = headers

                def info(self):
                    return self.headers

            try:
                self._jar.extract_cookies(_Resp(headers), Request(url))
            except Exception:
                pass

    def set(self, domain: str, name: str, value: str, path: str = "/") -> None:
        cookie = Cookie(
            version=0, name=name, value=value, port=None, port_specified=False,
            domain=domain, domain_specified=True, domain_initial_dot=domain.startswith("."),
            path=path, path_specified=True, secure=False, expires=None, discard=True,
            comment=None, comment_url=None, rest={}, rfc2109=False,
        )
        self._jar.set_cookie(cookie)

    def get_header(self, url: str) -> str:
        try:
            return self._jar.add_cookie_header(Request(url)) or ""
        except Exception:
            return ""

    def get_cookies(self, url: str) -> dict[str, str]:
        parsed = urlparse(url)
        cookies = {}
        for cookie in self._jar:
            if cookie.domain and _domain_matches(cookie.domain, parsed.hostname or ""):
                cookies[cookie.name] = cookie.value
        return cookies

    def clear(self) -> None:
        self._jar.clear()

    def __bool__(self) -> bool:
        return len(self._jar) > 0


def _domain_matches(cookie_domain: str, host: str) -> bool:
    domain = cookie_domain.lstrip(".")
    return host == domain or host.endswith("." + domain)


class SessionManager:
    """Named cookie sessions, so one spider can juggle several identities."""

    def __init__(self):
        self._sessions: dict[str, CookieStore] = {}

    def store(self, session_id: str = "default") -> CookieStore:
        if session_id not in self._sessions:
            self._sessions[session_id] = CookieStore()
        return self._sessions[session_id]

    def clear(self, session_id: Optional[str] = None) -> None:
        if session_id is None:
            self._sessions.clear()
        else:
            self._sessions.pop(session_id, None)

    def cookies_for(self, url: str, session_id: str = "default") -> dict[str, str]:
        return self.store(session_id).get_cookies(url)

    def header_for(self, url: str, session_id: str = "default") -> str:
        return self.store(session_id).get_header(url)
