"""零依赖的 OpenAI 兼容 LLM 客户端。

直接用已内置的 ``httpx`` 调用任意 OpenAI 兼容的 ``/chat/completions`` 接口，
无需安装 ``openai`` SDK。支持：OpenAI、本地 Ollama、vLLM、LM Studio、DeepSeek 等。

用法：
    client = LLMClient(base_url="http://localhost:11434/v1", model="qwen2.5")
    text = client.complete("你好")

    # 或通过 Settings / 环境变量 ARACHNE_LLM_BASE_URL / ARACHNE_LLM_API_KEY
"""

from __future__ import annotations

from typing import Any, Optional

from ..config import Settings
from ..exceptions import ArachneError
from ..log import get_logger

logger = get_logger("ai")


def _chat_url(base_url: Optional[str]) -> str:
    base = (base_url or "").rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return base + "/chat/completions"
    return base + "/chat/completions"


class LLMClient:
    """Thin client over any OpenAI-compatible chat completions endpoint."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: str = "gpt-4o-mini",
        timeout: float = 60.0,
    ):
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    @classmethod
    def from_settings(cls, settings: Settings) -> "LLMClient":
        return cls(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            timeout=settings.llm_timeout,
        )

    def chat(self, messages: list[dict[str, str]], *, temperature: float = 0.0, **kwargs) -> str:
        import httpx

        if not self.base_url:
            raise ArachneError("未配置 LLM base_url（请设置 ARACHNE_LLM_BASE_URL）")

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        payload.update(kwargs)

        try:
            resp = httpx.post(
                _chat_url(self.base_url), json=payload, headers=headers, timeout=self.timeout
            )
        except Exception as exc:  # noqa: BLE001
            raise ArachneError(f"LLM 请求失败：{exc}") from exc

        ctype = (resp.headers.get("content-type") or "").lower()
        is_html = "text/html" in ctype or resp.text.lstrip().startswith("<!DOCTYPE") or resp.text.lstrip().startswith("<html")
        if resp.status_code != 200:
            hint = ""
            if is_html:
                hint = (
                    "（返回的是 HTML 页面而非 JSON，通常是 base_url 配置错误、"
                    "接口被 WAF/Cloudflare 拦截、或触发限流）"
                )
            elif resp.status_code == 429:
                hint = "（429 限流，可稍后重试或降低请求频率）"
            raise ArachneError(f"LLM 返回 {resp.status_code}：{resp.text[:300]}{hint}")

        if is_html:
            raise ArachneError(
                "LLM 接口返回了 HTML 页面（不是预期的 JSON），请检查 base_url 是否正确指向 "
                f"OpenAI 兼容的 /v1 地址。当前 base_url={self.base_url!r}，响应前 200 字：{resp.text[:200]}"
            )

        data = resp.json()
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise ArachneError(f"无法解析 LLM 响应：{str(data)[:300]}") from exc

    def complete(self, prompt: str, *, system: Optional[str] = None, **kwargs) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return self.chat(messages, **kwargs)


def get_client(settings: Optional[Settings] = None) -> LLMClient:
    settings = settings or Settings()
    if not settings.llm_api_key and not settings.llm_base_url:
        raise ArachneError(
            "no LLM configured; set llm_base_url/llm_api_key in Settings "
            "(or ARACHNE_LLM_BASE_URL / ARACHNE_LLM_API_KEY)"
        )
    return LLMClient.from_settings(settings)
