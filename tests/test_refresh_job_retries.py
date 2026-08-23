import io
import socket
import urllib.error

import pytest

from scripts import run_refresh_job


class FakeResponse:
    def __init__(self, body=b"{}"):
        self.body = body
        self.status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.body


def configure_retries(monkeypatch, *, attempts=3, backoff=1.0):
    monkeypatch.setattr(
        run_refresh_job,
        "REQUEST_MAX_ATTEMPTS",
        attempts,
    )
    monkeypatch.setattr(
        run_refresh_job,
        "REQUEST_RETRY_BACKOFF_SECONDS",
        backoff,
    )
    monkeypatch.setattr(
        run_refresh_job,
        "REQUEST_TIMEOUT_SECONDS",
        60,
    )
    monkeypatch.setattr(
        run_refresh_job,
        "_log",
        lambda _message: None,
    )


def test_request_retries_timeout_then_recovers(monkeypatch):
    configure_retries(monkeypatch)
    calls = []
    sleeps = []

    def urlopen(_request, *, timeout):
        calls.append(timeout)
        if len(calls) == 1:
            raise socket.timeout("read operation timed out")
        return FakeResponse(b'{"status": "ok"}')

    monkeypatch.setattr(
        run_refresh_job.urllib.request,
        "urlopen",
        urlopen,
    )
    monkeypatch.setattr(
        run_refresh_job.time,
        "sleep",
        sleeps.append,
    )

    result = run_refresh_job._request_json(
        "https://example.test/matchups",
        label="production",
    )

    assert result == {"status": "ok"}
    assert calls == [60, 60]
    assert sleeps == [1.0]


def test_request_retries_http_503_then_recovers(monkeypatch):
    configure_retries(monkeypatch)
    calls = []
    sleeps = []

    def urlopen(request, *, timeout):
        calls.append((request.full_url, timeout))
        if len(calls) == 1:
            raise urllib.error.HTTPError(
                request.full_url,
                503,
                "Service Unavailable",
                {},
                io.BytesIO(b"temporarily unavailable"),
            )
        return FakeResponse(b"[]")

    monkeypatch.setattr(
        run_refresh_job.urllib.request,
        "urlopen",
        urlopen,
    )
    monkeypatch.setattr(
        run_refresh_job.time,
        "sleep",
        sleeps.append,
    )

    assert run_refresh_job._request_json(
        "https://example.test/matchups",
        label="production",
    ) == []
    assert len(calls) == 2
    assert sleeps == [1.0]


def test_request_does_not_retry_nontransient_http_error(monkeypatch):
    configure_retries(monkeypatch)
    calls = []
    sleeps = []

    def urlopen(request, *, timeout):
        calls.append((request.full_url, timeout))
        raise urllib.error.HTTPError(
            request.full_url,
            500,
            "Internal Server Error",
            {},
            io.BytesIO(b"persistent failure"),
        )

    monkeypatch.setattr(
        run_refresh_job.urllib.request,
        "urlopen",
        urlopen,
    )
    monkeypatch.setattr(
        run_refresh_job.time,
        "sleep",
        sleeps.append,
    )

    with pytest.raises(urllib.error.HTTPError) as raised:
        run_refresh_job._request_json(
            "https://example.test/matchups",
            label="production",
        )

    assert raised.value.code == 500
    assert len(calls) == 1
    assert sleeps == []


def test_request_raises_after_transient_retries_exhausted(
    monkeypatch,
):
    configure_retries(monkeypatch, attempts=3, backoff=0.5)
    calls = []
    sleeps = []

    def urlopen(_request, *, timeout):
        calls.append(timeout)
        raise TimeoutError("read operation timed out")

    monkeypatch.setattr(
        run_refresh_job.urllib.request,
        "urlopen",
        urlopen,
    )
    monkeypatch.setattr(
        run_refresh_job.time,
        "sleep",
        sleeps.append,
    )

    with pytest.raises(TimeoutError):
        run_refresh_job._request_json(
            "https://example.test/matchups",
            label="production",
        )

    assert calls == [60, 60, 60]
    assert sleeps == [0.5, 1.0]


def test_target_checks_readiness_before_expensive_refresh(
    monkeypatch,
):
    calls = []
    monkeypatch.setattr(
        run_refresh_job,
        "REFRESH_MATCHUPS_FIRST",
        True,
    )
    monkeypatch.setattr(
        run_refresh_job,
        "WARM_SNAPSHOTS",
        False,
    )
    monkeypatch.setattr(
        run_refresh_job,
        "CLEAR_AI_CACHE_AFTER_REFRESH",
        False,
    )
    monkeypatch.setattr(
        run_refresh_job,
        "_check_readiness",
        lambda label, base_url: calls.append(
            ("readiness", label, base_url)
        ),
    )
    monkeypatch.setattr(
        run_refresh_job,
        "_refresh_matchups_for_date",
        lambda label, base_url, target_date: calls.append(
            ("matchups", label, base_url, target_date)
        ),
    )

    run_refresh_job._run_target(
        "production",
        "https://example.test",
    )

    assert calls[0] == (
        "readiness",
        "production",
        "https://example.test",
    )
    assert [row[0] for row in calls] == [
        "readiness",
        "matchups",
        "matchups",
    ]


def test_fast_refresh_defaults_snapshot_warming_off():
    assert (
        run_refresh_job.DEFAULT_WARM_MATCHUP_SNAPSHOTS
        == "0"
    )


def test_target_warms_snapshots_when_explicitly_enabled(
    monkeypatch,
):
    calls = []

    monkeypatch.setattr(
        run_refresh_job,
        "REFRESH_MATCHUPS_FIRST",
        False,
    )
    monkeypatch.setattr(
        run_refresh_job,
        "WARM_SNAPSHOTS",
        True,
    )
    monkeypatch.setattr(
        run_refresh_job,
        "CLEAR_AI_CACHE_AFTER_REFRESH",
        False,
    )
    monkeypatch.setattr(
        run_refresh_job,
        "_check_readiness",
        lambda label, base_url: calls.append(
            ("readiness", label, base_url)
        ),
    )
    monkeypatch.setattr(
        run_refresh_job,
        "_warm_snapshot_for_date",
        lambda label, base_url, target_date: calls.append(
            ("snapshot", label, base_url, target_date)
        ),
    )

    run_refresh_job._run_target(
        "production",
        "https://example.test",
    )

    assert [row[0] for row in calls] == [
        "readiness",
        "snapshot",
        "snapshot",
    ]


def test_target_isolation_is_preserved_after_exhausted_failure(
    monkeypatch,
):
    calls = []
    monkeypatch.setattr(
        run_refresh_job,
        "RUN_FAST_MATCHUP_REFRESH",
        True,
    )
    monkeypatch.setattr(
        run_refresh_job,
        "_run_hitting_matchups_refresh",
        lambda: None,
    )
    monkeypatch.setattr(
        run_refresh_job,
        "_load_targets",
        lambda: [
            ("production", "https://production.test"),
            ("sandbox", "https://sandbox.test"),
        ],
    )
    monkeypatch.setattr(
        run_refresh_job,
        "_log",
        lambda _message: None,
    )

    def run_target(label, _base_url):
        calls.append(label)
        if label == "production":
            raise TimeoutError("read operation timed out")

    monkeypatch.setattr(
        run_refresh_job,
        "_run_target",
        run_target,
    )

    with pytest.raises(
        RuntimeError,
        match="One or more refresh targets failed",
    ):
        run_refresh_job._run_fast_matchup_refresh()

    assert calls == ["production", "sandbox"]
