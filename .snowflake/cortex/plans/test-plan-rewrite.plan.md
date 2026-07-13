# Plan: Rewrite test_plan.md + Implement Valuable Missing Tests

## Overview

The existing `docs/test_plan.md` is a heavily outdated aspirational spec. The audit found:
- 3 referenced test files don't exist
- ~40 function names are wrong
- ~40 planned tests were never written
- ~30 real tests aren't mentioned at all

This plan: implement the 3 most valuable test gaps (JWT claims, HTTP error mapping, thread CRUD), then rewrite `test_plan.md` as an accurate living document.

---

## Tests to implement

### 1 — JWT auth tests (`tests/unit/test_auth.py`)

Add class `TestJWTAuth` with a fixture that generates a temporary RSA key:

```python
cryptography = pytest.importorskip("cryptography")
jwt_lib = pytest.importorskip("jwt")

@pytest.fixture
def rsa_key_file(tmp_path):
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives import serialization
    private_key = rsa.generate_private_key(65537, 2048, default_backend())
    pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    key_file = tmp_path / "key.p8"
    key_file.write_bytes(pem)
    return key_file
```

Five tests:
- `test_headers_include_authorization_and_keypair_jwt_type` — `headers()` returns both expected keys
- `test_jwt_claims_iss_format` — decode JWT, assert `iss == "MYORG-MYACCOUNT.MYUSER.SHA256:..."`
- `test_jwt_claims_sub_format` — assert `sub == "MYORG-MYACCOUNT.MYUSER"`
- `test_jwt_exp_within_one_hour` — assert `exp - iat <= 3600`
- `test_account_and_user_uppercased` — pass lowercase `account/user`, assert claims are uppercase

**Why valuable:** JWT claim format is security-critical (Snowflake rejects wrong formats). No coverage exists today.

---

### 2 — HTTP 429/500 error tests (`tests/integration/test_runs.py`)

Extend the existing `TestHttpErrors` class:

```python
def test_http_429_raises_rate_limit_error(self, ca_client, httpx_mock):
    from cortex_agents_client.exceptions import RateLimitError
    httpx_mock.add_response(
        status_code=429,
        headers={"Content-Type": "application/json"},
        json={"message": "Rate limit exceeded"},
    )
    with pytest.raises(RateLimitError):
        list(ca_client.runs.stream(messages, agent_path="DB.SC.A"))

def test_http_500_raises_server_error(self, ca_client, httpx_mock):
    from cortex_agents_client.exceptions import ServerError
    httpx_mock.add_response(
        status_code=500,
        headers={"Content-Type": "application/json"},
        json={"message": "Internal server error"},
    )
    with pytest.raises(ServerError):
        list(ca_client.runs.stream(messages, agent_path="DB.SC.A"))
```

**Why valuable:** `RateLimitError` and `ServerError` exist in `exceptions.py` and are mapped in `_raise_for_status` but have no test coverage.

---

### 3 — threads.update() and threads.list() (`tests/integration/test_threads.py`)

Both methods exist in `resources/threads.py` but have zero test coverage.

```python
class TestUpdateThread:
    def test_update_happy_path(self, ca_client, httpx_mock):
        httpx_mock.add_response(method="POST", status_code=200, json={})
        ca_client.threads.update(1234567890, thread_name="My Renamed Thread")

    def test_update_sends_correct_body(self, ca_client, httpx_mock):
        captured = {}
        def responder(request):
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json={})
        httpx_mock.add_callback(responder)
        ca_client.threads.update(1234567890, thread_name="New Name")
        assert captured["body"]["thread_name"] == "New Name"

class TestListThreads:
    def test_list_returns_all(self, ca_client, httpx_mock):
        httpx_mock.add_response(json=[THREAD_CREATE_RESPONSE, THREAD_CREATE_RESPONSE])
        threads = ca_client.threads.list()
        assert len(threads) == 2
        assert threads[0].thread_id == 1234567890

    def test_list_with_origin_filter(self, ca_client, httpx_mock):
        captured = []
        def responder(request):
            captured.append(str(request.url))
            return httpx.Response(200, json=[])
        httpx_mock.add_callback(responder)
        ca_client.threads.list(origin_application="my_app")
        assert "origin_application=my_app" in captured[0]
```

---

## Tests NOT implementing

| Planned test | Reason skipped |
|---|---|
| AppTest chatbot integration tests | High complexity, fragile, low ROI for this project |
| Live tests (`tests/live/`) | Require real Snowflake account |
| `test_session.py` | Unclear scope; `init_session/sis_init_session` already have indirect coverage |
| `test_connection_error_*`, `test_timeout_*` | `httpx_mock` doesn't easily simulate network-level failures; low value vs. cost |
| `test_tool_choice_in_request_body`, `test_permission_decision_in_message` | Already covered by `TestToolExecutor` in `test_utils.py` |

---

## test_plan.md rewrite structure

The rewritten document will:

1. **Accurately name** every test function that exists today (not aspirational names)
2. **Remove** references to `tests/integration/test_thread_class.py`, `tests/streamlit/test_session.py`, `tests/live/test_live.py` (don't exist)
3. **Note** that `TestThreadClass` lives in `test_runs.py`
4. **Include** the newly added tests in the correct sections
5. **Add a "Future coverage" section** for aspirational tests (AppTest chatbot, live tests, connection/timeout errors)
6. **Fix** all stale fixture names (`ca_client` not `mock_client`, `make_sse_response` not `sse_response(events)`)
7. **Correct** the `ResultSet` references (class doesn't exist)
8. **Remove** the inaccurate "Uses AppTest" claim from the Streamlit section
