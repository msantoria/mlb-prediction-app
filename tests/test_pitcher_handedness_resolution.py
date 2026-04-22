from mlb_app.analysis_pipeline import _determine_hand


class DummyResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_determine_hand_returns_pitch_hand_code(monkeypatch):
    monkeypatch.setattr(
        "mlb_app.analysis_pipeline.requests.get",
        lambda url, timeout=10: DummyResponse(
            {"people": [{"pitchHand": {"code": "R"}}]}
        ),
    )

    assert _determine_hand(12345) == "R"


def test_determine_hand_returns_none_on_request_failure(monkeypatch):
    class DummyException(Exception):
        pass

    def raise_error(url, timeout=10):
        raise DummyException("network error")

    monkeypatch.setattr("mlb_app.analysis_pipeline.requests.get", raise_error)

    assert _determine_hand(12345) is None
