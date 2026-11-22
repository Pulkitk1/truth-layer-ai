"""Thin wrapper around the Groq SDK. All Groq errors are mapped to LlmError so the
rest of the app never depends on SDK exception types.

Groq limits tokens per minute (for example 8,000 for openai/gpt-oss-120b on the free tier) as well as
requests per day. A burst of fact-checks can exceed the per-minute budget even when the daily
allowance is nearly untouched, so calls are made one at a time, paced using the remaining-token
numbers Groq returns in its response headers, and retried after the wait Groq asks for.
"""
import re
import threading
import time

import groq

from . import config

COMPLETION_RESERVE = 1500  # tokens kept free for the answer (including a reasoning model's thinking)
MAX_RATE_RETRIES = 3
MAX_WAIT_SECONDS = 45.0  # never block one request longer than this on a single wait

_gate = threading.Lock()  # one Groq call at a time: parallel calls would overspend the per-minute budget
_budget: dict = {"remaining": None, "limit": None, "as_of": 0.0}
_sleep = time.sleep  # replaced in tests


class LlmError(Exception):
    def __init__(self, code: str, message: str, status: int = 502, retryable_split: bool = False):
        self.code, self.message, self.status = code, message, status
        # True when the request was too large and may succeed if the input is split.
        self.retryable_split = retryable_split
        super().__init__(message)


def get_client() -> groq.Groq:
    key = config.groq_api_key()
    if not key:
        raise LlmError(
            "groq_not_configured",
            "GROQ_API_KEY is not set. Add it to backend/.env and restart the backend.",
            status=503,
        )
    return groq.Groq(api_key=key, timeout=config.groq_timeout(), max_retries=2)


def _too_large(message: str) -> bool:
    m = message.lower()
    return any(s in m for s in ("context length", "context_length", "too large", "reduce the length", "maximum context"))


# ---------------------------------------------------------------- rate-limit handling

def parse_duration(text: str | None) -> float | None:
    """'922ms', '7.66s', '1m3.2s', '23m2.4s' -> seconds."""
    if not text:
        return None
    parts = re.findall(r"(\d+(?:\.\d+)?)(ms|h|m|s)", text.strip())
    if not parts:
        return None
    scale = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}
    return sum(float(n) * scale[u] for n, u in parts)


def _estimate_tokens(messages: list[dict]) -> int:
    return sum(len(str(m.get("content", ""))) for m in messages) // 3 + COMPLETION_RESERVE


def _record_headers(headers) -> None:
    """Remember how many tokens Groq says are left in the current minute."""
    try:
        rem = headers.get("x-ratelimit-remaining-tokens")
        lim = headers.get("x-ratelimit-limit-tokens")
        if rem is not None and lim is not None:
            _budget.update(remaining=float(rem), limit=float(lim), as_of=time.monotonic())
    except (AttributeError, ValueError):
        pass


def _pace(estimate: int) -> None:
    """Wait (briefly) until the per-minute token budget can cover the next request."""
    rem, lim = _budget["remaining"], _budget["limit"]
    if rem is None or not lim:
        return
    estimate = min(estimate, int(lim * 0.9))  # a request bigger than the whole budget could never be paced
    # The budget refills continuously at limit/60 tokens per second.
    available = min(lim, rem + (time.monotonic() - _budget["as_of"]) * lim / 60.0)
    if available >= estimate:
        return
    wait = min((estimate - available) * 60.0 / lim, MAX_WAIT_SECONDS)
    _sleep(wait + 0.25)


def _limit_kind(text: str) -> tuple[str, bool]:
    """(plain-English name of the limit that was hit, is it a daily limit?)"""
    t = text.lower()
    daily = "per day" in t or "(rpd)" in t or "(tpd)" in t
    if "tokens per day" in t or "(tpd)" in t:
        return "tokens per day", True
    if "requests per day" in t or "(rpd)" in t:
        return "requests per day", True
    if "tokens per minute" in t or "(tpm)" in t:
        return "tokens per minute", daily
    if "requests per minute" in t or "(rpm)" in t:
        return "requests per minute", daily
    return "rate", daily


def _retry_delay(exc: groq.RateLimitError, attempt: int) -> float:
    """How long Groq wants us to wait: the Retry-After header, else the 'try again in 3.2s' hint, else a back-off."""
    headers = getattr(getattr(exc, "response", None), "headers", None) or {}
    after = headers.get("retry-after")
    if after:
        try:
            return float(after)
        except ValueError:
            pass
    m = re.search(r"try again in ([0-9hms.]+)", str(exc), re.I)
    d = parse_duration(m.group(1).rstrip(".")) if m else None
    return d if d is not None else 4.0 * (attempt + 1)


def _create(client, messages):
    raw = client.chat.completions.with_raw_response.create(
        model=config.groq_model(),
        messages=messages,
        temperature=0,
        response_format={"type": "json_object"},
    )
    _record_headers(raw.headers)
    return raw.parse()


def complete(messages: list[dict]) -> str:
    """Send a chat completion in JSON mode and return the raw message content."""
    client = get_client()
    estimate = _estimate_tokens(messages)
    try:
        with _gate:
            resp = None
            for attempt in range(MAX_RATE_RETRIES + 1):
                _pace(estimate)
                try:
                    resp = _create(client, messages)
                    break
                except groq.RateLimitError as e:
                    _record_headers(getattr(getattr(e, "response", None), "headers", None) or {})
                    kind, daily = _limit_kind(str(e))
                    delay = _retry_delay(e, attempt)
                    if daily:
                        raise LlmError(
                            "groq_daily_limit",
                            f"Groq's daily limit ({kind}) for this model was reached. It resets about "
                            f"{_human(delay)} from now; try again then, or choose another model in GROQ_MODEL.",
                            429,
                        ) from e
                    if attempt == MAX_RATE_RETRIES or delay > MAX_WAIT_SECONDS:
                        raise LlmError(
                            "groq_rate_limited",
                            f"Groq's per-minute limit ({kind}) was reached and is still exceeded. "
                            f"Wait about {_human(delay)} and try again; verifying fewer claims at a time also helps.",
                            429,
                        ) from e
                    _budget["remaining"] = 0.0  # we know the minute's budget is spent; wait for it to refill
                    _budget["as_of"] = time.monotonic()
                    _sleep(delay + 0.5)
    except groq.AuthenticationError as e:
        raise LlmError("groq_auth_failed", "The Groq API key was rejected. Check GROQ_API_KEY.", 502) from e
    except groq.PermissionDeniedError as e:
        raise LlmError("groq_auth_failed", "The Groq API key does not have access to this model.", 502) from e
    except groq.APITimeoutError as e:
        raise LlmError("groq_timeout", "The Groq request timed out.", 504) from e
    except groq.APIConnectionError as e:
        raise LlmError("groq_unreachable", "Could not connect to the Groq API.", 502) from e
    except groq.NotFoundError as e:
        raise LlmError(
            "groq_model_not_found", f"Groq model '{config.groq_model()}' was not found. Check GROQ_MODEL.", 502
        ) from e
    except groq.APIStatusError as e:
        text = str(e)
        if e.status_code == 413 or (e.status_code == 400 and _too_large(text)):
            raise LlmError("groq_request_too_large", "Request too large for the model.", 413, retryable_split=True) from e
        raise LlmError("groq_error", f"Groq API error (HTTP {e.status_code}).", 502) from e

    content = resp.choices[0].message.content if resp is not None and resp.choices else None
    if not content:
        raise LlmError("groq_empty_response", "Groq returned an empty response.", 502)
    return content


def _human(seconds: float) -> str:
    s = max(1, round(seconds))
    if s < 90:
        return f"{s} seconds"
    m = round(s / 60)
    return f"{m} minutes" if m < 90 else f"{round(m / 60)} hours"
