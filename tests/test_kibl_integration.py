import pytest

from mlb_app.database import create_tables, get_engine, get_session
from mlb_app.kibl_integration import (
    KIBL_FIXTURES_PATH,
    KIBL_LIVE_BETTING_TYPE_ID,
    KIBL_PREMATCH_BETTING_TYPE_ID,
    KiblApiClient,
    KiblAuthClient,
    KiblConfig,
    KiblFixture,
    KiblMarket,
    KiblSyncWatermark,
    extract_rows,
    get_watermark,
    newest_kibl_timestamp,
    redact_secrets,
    sync_kibl_endpoint,
    upsert_fixtures,
    upsert_markets,
)


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if not self.responses:
            raise AssertionError("No fake response queued")
        return self.responses.pop(0)


class StubClient:
    def __init__(self, config, fixture_rows=None, market_rows=None):
        self.config = config
        self.fixture_rows = fixture_rows if fixture_rows is not None else []
        self.market_rows = market_rows if market_rows is not None else []
        self.fixture_calls = []
        self.market_calls = []

    def fixtures(self, betting_type_id, league_id, watermark):
        self.fixture_calls.append((betting_type_id, league_id, watermark))
        return self.fixture_rows

    def markets(self, betting_type_id, league_id, watermark):
        self.market_calls.append((betting_type_id, league_id, watermark))
        return self.market_rows


@pytest.fixture()
def config():
    return KiblConfig(
        cognito_region="us-west-2",
        cognito_client_id="client-id",
        username="user@example.com",
        password="super-secret",
        base_url="https://api.kibl.io/sports/get",
        feed_source_id=171,
        default_league_ids="20,643",
        from_cache=False,
    )


@pytest.fixture()
def db_session():
    engine = get_engine("sqlite:///:memory:")
    create_tables(engine)
    SessionLocal = get_session(engine)
    with SessionLocal() as session:
        yield session


def test_cognito_auth_request_uses_expected_password_flow(config):
    http = FakeSession([
        FakeResponse(payload={"AuthenticationResult": {"AccessToken": "token-1", "ExpiresIn": 3600}})
    ])
    auth = KiblAuthClient(config, http_session=http)

    assert auth.get_access_token() == "token-1"

    call = http.calls[0]
    assert call["url"] == "https://cognito-idp.us-west-2.amazonaws.com/"
    assert call["headers"]["X-Amz-Target"] == "AWSCognitoIdentityProviderService.InitiateAuth"
    assert call["json"]["AuthFlow"] == "USER_PASSWORD_AUTH"
    assert call["json"]["ClientId"] == "client-id"
    assert call["json"]["AuthParameters"] == {
        "USERNAME": "user@example.com",
        "PASSWORD": "super-secret",
    }


def test_kibl_request_uses_bearer_token_and_strips_server_fields(config):
    auth_http = FakeSession([
        FakeResponse(payload={"AuthenticationResult": {"AccessToken": "token-1", "ExpiresIn": 3600}})
    ])
    kibl_http = FakeSession([FakeResponse(payload={"data": []})])
    client = KiblApiClient(config, KiblAuthClient(config, auth_http), http_session=kibl_http)

    client.post(KIBL_FIXTURES_PATH, {"feed_source_id": 171, "request_uuid": "no", "requested": "no"})

    call = kibl_http.calls[0]
    assert call["url"] == "https://api.kibl.io/sports/get/info/fixtures/"
    assert call["headers"]["Authorization"] == "Bearer token-1"
    assert call["headers"]["Content-Type"] == "application/json"
    assert "request_uuid" not in call["json"]
    assert "requested" not in call["json"]


def test_baseline_ticket_omits_since_last_updated(config):
    auth = KiblAuthClient(config, http_session=FakeSession([]))
    client = KiblApiClient(config, auth, http_session=FakeSession([]))

    ticket = client.build_ticket(KIBL_PREMATCH_BETTING_TYPE_ID)

    assert ticket["feed_source_id"] == 171
    assert ticket["betting_type_id"] == KIBL_PREMATCH_BETTING_TYPE_ID
    assert ticket["league_id"] == "20,643"
    assert ticket["from_cache"] is False
    assert "since_last_updated" not in ticket


def test_diff_ticket_includes_since_last_updated(config):
    auth = KiblAuthClient(config, http_session=FakeSession([]))
    client = KiblApiClient(config, auth, http_session=FakeSession([]))

    ticket = client.build_ticket(KIBL_LIVE_BETTING_TYPE_ID, since_last_updated="2026-06-02 14:30:00")

    assert ticket["betting_type_id"] == KIBL_LIVE_BETTING_TYPE_ID
    assert ticket["since_last_updated"] == "2026-06-02 14:30:00"


def test_401_refreshes_token_and_retries_once(config):
    auth_http = FakeSession([
        FakeResponse(payload={"AuthenticationResult": {"AccessToken": "old-token", "ExpiresIn": 3600}}),
        FakeResponse(payload={"AuthenticationResult": {"AccessToken": "new-token", "ExpiresIn": 3600}}),
    ])
    kibl_http = FakeSession([
        FakeResponse(status_code=401, payload={}, text="unauthorized"),
        FakeResponse(payload={"data": [{"id": 1}]}),
    ])
    client = KiblApiClient(config, KiblAuthClient(config, auth_http), http_session=kibl_http)

    rows = client.fixtures(KIBL_PREMATCH_BETTING_TYPE_ID)

    assert rows == [{"id": 1}]
    assert len(kibl_http.calls) == 2
    assert kibl_http.calls[0]["headers"]["Authorization"] == "Bearer old-token"
    assert kibl_http.calls[1]["headers"]["Authorization"] == "Bearer new-token"


def test_empty_diff_response_does_not_crash_or_advance_watermark(config, db_session):
    client = StubClient(config, fixture_rows=[])

    result = sync_kibl_endpoint(
        db_session,
        client,
        KIBL_FIXTURES_PATH,
        KIBL_PREMATCH_BETTING_TYPE_ID,
        league_id="20,643",
        baseline=False,
    )

    assert result["rows_received"] == 0
    assert result["new_watermark"] is None
    assert client.fixture_calls[0] == (KIBL_PREMATCH_BETTING_TYPE_ID, "20,643", None)
    assert db_session.query(KiblSyncWatermark).count() == 0


def test_watermark_updates_to_newest_timestamp(config, db_session):
    rows = [
        {"id": "a", "last_updated": "2026-06-02 14:30:00"},
        {"id": "b", "inserted_on": "2026-06-02 14:35:00"},
    ]
    client = StubClient(config, fixture_rows=rows)

    result = sync_kibl_endpoint(
        db_session,
        client,
        KIBL_FIXTURES_PATH,
        KIBL_PREMATCH_BETTING_TYPE_ID,
        league_id="20,643",
        baseline=True,
    )

    assert result["new_watermark"] == "2026-06-02 14:35:00"
    assert get_watermark(db_session, KIBL_FIXTURES_PATH, 171, KIBL_PREMATCH_BETTING_TYPE_ID, "20,643") == "2026-06-02 14:35:00"


def test_fixture_upsert_is_idempotent(db_session):
    rows = [{"fixture_id": "fx-1", "home_team": "Cubs", "last_updated": "2026-06-02 14:30:00"}]

    assert upsert_fixtures(db_session, rows, 171, KIBL_PREMATCH_BETTING_TYPE_ID, "20,643") == (1, 0)
    assert upsert_fixtures(db_session, rows, 171, KIBL_PREMATCH_BETTING_TYPE_ID, "20,643") == (0, 1)
    db_session.commit()

    assert db_session.query(KiblFixture).count() == 1


def test_market_upsert_is_idempotent(db_session):
    rows = [{"market_id": "m-1", "fixture_id": "fx-1", "selection_id": "s-1", "price": -115}]

    assert upsert_markets(db_session, rows, 171, KIBL_PREMATCH_BETTING_TYPE_ID, "20,643") == (1, 0)
    assert upsert_markets(db_session, rows, 171, KIBL_PREMATCH_BETTING_TYPE_ID, "20,643") == (0, 1)
    db_session.commit()

    assert db_session.query(KiblMarket).count() == 1


def test_secret_redaction():
    payload = {
        "Authorization": "Bearer abc",
        "password": "hidden",
        "nested": {"access_token": "token"},
        "safe": "visible",
    }

    assert redact_secrets(payload) == {
        "Authorization": "***REDACTED***",
        "password": "***REDACTED***",
        "nested": {"access_token": "***REDACTED***"},
        "safe": "visible",
    }


def test_extract_rows_supports_wrapped_and_plain_payloads():
    assert extract_rows({"data": [{"id": 1}]}) == [{"id": 1}]
    assert extract_rows({"results": [{"id": 2}]}) == [{"id": 2}]
    assert extract_rows([{"id": 3}]) == [{"id": 3}]


def test_newest_kibl_timestamp_prefers_latest_last_updated_or_inserted_on():
    assert newest_kibl_timestamp([
        {"last_updated": "2026-06-02 14:30:00"},
        {"inserted_on": "2026-06-02 15:30:00"},
    ]) == "2026-06-02 15:30:00"
