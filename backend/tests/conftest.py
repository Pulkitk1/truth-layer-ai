import pytest

from app import llm


@pytest.fixture(autouse=True)
def _no_real_waiting(monkeypatch):
    """The Groq wrapper waits and retries on rate limits. Tests must never really sleep, and each test starts
    with a fresh view of the rate-limit budget."""
    monkeypatch.setattr(llm, "_sleep", lambda s: None)
    llm._budget.update(remaining=None, limit=None, as_of=0.0)
    yield
    llm._budget.update(remaining=None, limit=None, as_of=0.0)


@pytest.fixture(scope="session", autouse=True)
def _test_database(tmp_path_factory):
    """Every test runs against a throw-away SQLite database and file store, never the real Neon database.
    (The live Neon checks are in test_neon_live.py and only run when RUN_NEON_TESTS=1.)"""
    from app import filestore
    from app.db import models, session

    root = tmp_path_factory.mktemp("db")
    engine = session.build_engine(f"sqlite:///{root / 'test.db'}")
    models.Base.metadata.create_all(engine)
    session.set_engine(engine)
    filestore.set_store(None)
    yield engine
    session.set_engine(None)
    filestore.set_store(None)


_TOKENS: dict[str, str] = {}
_ID_RE = __import__("re").compile(r"[0-9a-f]{32}")


@pytest.fixture(scope="session", autouse=True)
def _auto_auth():
    """Every document request needs its owner's token. The existing tests predate that, so the test client attaches
    the token it was given at upload (or a well-formed dummy for documents it never uploaded). The security tests
    switch this off with `client.auto_auth = False` and send tokens explicitly."""
    from fastapi.testclient import TestClient

    original = TestClient.request

    def request(self, method, url, **kw):
        if getattr(self, "auto_auth", True):
            headers = kw.get("headers") or {}
            if not any(k.lower() == "authorization" for k in headers):
                m = _ID_RE.search(str(url))
                fid = m.group(0) if m else (kw.get("json") or {}).get("file_id") if isinstance(kw.get("json"), dict) else None
                if fid:
                    kw["headers"] = {**headers, "Authorization": f"Bearer {_TOKENS.get(fid, 'unknown-token-' + 'x' * 20)}"}
        resp = original(self, method, url, **kw)
        if method.upper() == "POST" and str(url).endswith("/api/upload") and resp.status_code == 200:
            _TOKENS[resp.json()["file_id"]] = resp.json()["access_token"]
        return resp

    TestClient.request = request
    yield
    TestClient.request = original


@pytest.fixture(autouse=True)
def _rate_limits_off_by_default(monkeypatch):
    """Only the rate-limit tests switch limiting on; everything else makes hundreds of requests from one 'IP'."""
    from app import middleware

    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    middleware.limiter.reset()
    yield
    middleware.limiter.reset()
