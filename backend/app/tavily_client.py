"""Thin wrapper around the Tavily SDK. All SDK errors become TavilyError."""
import time

import tavily.errors as te
from tavily import TavilyClient

from . import config

# Junk/low-signal sites we never want evidence from (saves result slots, not credits).
EXCLUDE_DOMAINS = ["pinterest.com", "quora.com", "facebook.com", "instagram.com", "tiktok.com"]
RATE_LIMIT_RETRY_DELAY = 2.0  # seconds; one retry only


class TavilyError(Exception):
    def __init__(self, code: str, message: str, status: int = 502, fatal: bool = False):
        self.code, self.message, self.status = code, message, status
        # fatal: every further search would fail too (bad key, no credits), so stop the job.
        self.fatal = fatal
        super().__init__(message)


def get_client() -> TavilyClient:
    key = config.tavily_api_key()
    if not key:
        # Checked explicitly: the SDK would otherwise silently fall back to keyless mode.
        raise TavilyError(
            "tavily_not_configured",
            "TAVILY_API_KEY is not set. Add it to backend/.env and restart the backend.",
            status=503,
            fatal=True,
        )
    return TavilyClient(api_key=key)


def _looks_like_credit_limit(msg: str) -> bool:
    m = msg.lower()
    return any(s in m for s in ("plan", "usage limit", "credit", "quota", "pay-as-you-go", "paygo"))


def _search_once(client, query: str) -> dict:
    try:
        return client.search(
            query=query,
            search_depth=config.tavily_search_depth(),
            max_results=config.tavily_fetch_results(),
            exclude_domains=EXCLUDE_DOMAINS,
            include_answer=False,
            include_raw_content=False,
            timeout=config.tavily_timeout(),
        )
    except te.InvalidAPIKeyError as e:
        raise TavilyError("tavily_auth_failed", "The Tavily API key was rejected. Check TAVILY_API_KEY.", 502, True) from e
    except te.MissingAPIKeyError as e:
        raise TavilyError("tavily_not_configured", "TAVILY_API_KEY is not set.", 503, True) from e
    except te.ForbiddenError as e:
        if _looks_like_credit_limit(str(e)):
            raise TavilyError(
                "tavily_credits_exhausted",
                "Your Tavily plan's usage limit has been reached. Add credits or wait for the limit to reset.",
                402,
                True,
            ) from e
        raise TavilyError("tavily_forbidden", "Tavily refused the request (access denied).", 502, True) from e
    except te.UsageLimitExceededError as e:
        if _looks_like_credit_limit(str(e)):
            raise TavilyError(
                "tavily_credits_exhausted",
                "Your Tavily plan's usage limit has been reached. Add credits or wait for the limit to reset.",
                402,
                True,
            ) from e
        raise TavilyError("tavily_rate_limited", "Tavily rate limit reached. Try again in a moment.", 429) from e
    except te.TimeoutError as e:
        raise TavilyError("tavily_timeout", "The Tavily search timed out.", 504) from e
    except te.BadRequestError as e:
        raise TavilyError("tavily_bad_request", "Tavily rejected the search query.", 502) from e
    except Exception as e:  # network errors, 5xx, anything unexpected
        raise TavilyError("tavily_error", "The Tavily search failed.", 502) from e


def search_web(query: str) -> dict:
    """Run one Tavily search (retrying once if rate-limited) and return the raw response."""
    client = get_client()
    try:
        data = _search_once(client, query)
    except TavilyError as e:
        if e.code != "tavily_rate_limited":
            raise
        time.sleep(RATE_LIMIT_RETRY_DELAY)
        data = _search_once(client, query)
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise TavilyError("tavily_malformed_response", "Tavily returned a response in an unexpected format.", 502)
    return data
