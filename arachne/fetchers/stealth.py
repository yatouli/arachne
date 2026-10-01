"""Stealth browser fetcher.

A :class:`DynamicFetcher` hardened with browser-fingerprint spoofing: it strips
``navigator.webdriver``, fabricates ``navigator.plugins``/``window.chrome``,
aligns client hints with the chosen profile, and waits out Cloudflare Turnstile /
interstitial challenges. This is the fallback of last resort for hard-protected
sites, inspired by Scrapling's ``StealthyFetcher``.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from ..antidetect.fingerprints import fingerprint_for
from ..exceptions import ChallengeError
from ..log import get_logger
from ..page import Page
from .dynamic import DynamicFetcher, _headers_from_response, _HAS_PLAYWRIGHT

logger = get_logger("stealth")


def stealth_script(profile: dict[str, Any]) -> str:
    """Return a Playwright ``init_script`` that hides automation signals."""
    platform = profile.get("platform", "Win32")
    languages = profile.get("accept_language", "en-US,en;q=0.9").split(",")
    languages = [lang.split(";")[0] for lang in languages]
    concurrency = profile.get("hardware_concurrency", 8)
    device_memory = profile.get("device_memory", 8)
    languages_json = str(languages).replace("'", '"')

    return f"""
(() => {{
    // 1. Hide webdriver flag
    Object.defineProperty(navigator, 'webdriver', {{get: () => undefined}});

    // 2. Spoof navigator properties
    Object.defineProperty(navigator, 'languages', {{get: () => {languages_json}}});
    Object.defineProperty(navigator, 'language', {{get: () => '{languages[0]}'}});
    Object.defineProperty(navigator, 'platform', {{get: () => '{platform}'}});
    Object.defineProperty(navigator, 'hardwareConcurrency', {{get: () => {concurrency}}});
    Object.defineProperty(navigator, 'deviceMemory', {{get: () => {device_memory}}});
    Object.defineProperty(navigator, 'maxTouchPoints', {{get: () => 0}});

    // 3. Fabricate plugins & mimeTypes
    const makePlugins = () => {{
        const p = [
            {{name: 'PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format'}},
            {{name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: ''}},
            {{name: 'Chromium PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: ''}},
        ];
        p.forEach(pl => {{ pl.length = 1; pl[0] = {{type: 'application/pdf'}}; }});
        return p;
    }};
    Object.defineProperty(navigator, 'plugins', {{get: () => makePlugins()}});

    // 4. Fake window.chrome
    window.chrome = window.chrome || {{}};
    window.chrome.runtime = window.chrome.runtime || {{}};
    window.chrome.loadTimes = () => ({{ commitLoadTime: Date.now()/1000 }});
    window.chrome.csi = () => ({{ startE: Date.now(), onloadT: 0, pageT: 100, tran: 10 }});

    // 5. Neutralize permission queries
    const originalQuery = window.navigator.permissions && window.navigator.permissions.query;
    if (originalQuery) {{
        window.navigator.permissions.query = (params) => (
            params.name === 'notifications'
                ? Promise.resolve({{state: Notification.permission}})
                : originalQuery(params)
        );
    }}

    // 6. Hide Playwright/automation markers
    for (const key of ['__playwright', '__pw_manual', '__PW_inspect']) {{
        try {{ delete window[key]; }} catch (e) {{}}
    }}
    const propNames = ['_playwright', '__webdriverFunc', 'domAutomation', 'domAutomationController'];
    for (const name of propNames) {{
        try {{ delete window.document[name]; }} catch (e) {{}}
    }}
}})();
"""


class StealthyFetcher(DynamicFetcher):
    """Browser fetcher with stealth patches and challenge auto-resolution."""

    name = "stealth"

    def _get_profile(self) -> dict[str, Any]:
        return fingerprint_for(
            self.settings.impersonate,
            user_agent=self.settings.user_agent,
            locale=self.settings.locale or None,
            timezone=self.settings.timezone or None,
            viewport=self.settings.viewport,
            randomize=self.settings.user_agent_rotation,
        )

    def _new_context(self, extra_headers: Optional[dict] = None):
        profile = self._get_profile()
        context = super()._new_context(extra_headers)
        context.add_init_script(stealth_script(profile))
        return context

    def _do_fetch(self, url: str, method: str, session_id: str, **kwargs) -> Page:
        challenge_wait = kwargs.pop("challenge_wait", 15.0)
        challenge_poll = kwargs.pop("challenge_poll", 1.0)
        page = super()._do_fetch(url, method, session_id, **kwargs)

        # If we hit a challenge, wait for the browser to clear it, then re-read.
        from ..antidetect.challenge import detect_block

        if detect_block(page).blocked and challenge_wait > 0:
            logger.debug("[stealth] challenge detected on %s; waiting up to %.1fs", url, challenge_wait)
            deadline = time.monotonic() + challenge_wait
            browser = self._get_browser()
            context = self._new_context()
            try:
                p = context.new_page()
                p.goto(url, wait_until="domcontentloaded", timeout=self.settings.timeout * 1000)
                while time.monotonic() < deadline:
                    p.wait_for_timeout(int(challenge_poll * 1000))
                    content = p.content()
                    fresh = self._to_page(
                        url, 200, content.encode("utf-8"), {}, 0.0, session_id,
                        captured_xhr=page.captured_xhr,
                    )
                    if not detect_block(fresh).blocked:
                        return fresh
            finally:
                context.close()
            raise ChallengeError(f"challenge not cleared within {challenge_wait:.0f}s", url=url)
        return page
