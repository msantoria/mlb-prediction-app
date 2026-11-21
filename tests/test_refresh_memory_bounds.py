from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import sys

import pytest

from mlb_app import shared_payload_cache as cache
from scripts import warm_game_day, run_refresh_job


@pytest.fixture(autouse=True)
def reset_cache(monkeypatch):
    cache.clear_shared_payload_cache()
    from collections import deque
    from mlb_app import performance
    monkeypatch.setattr(performance, '_SPANS', deque(maxlen=5000))
    monkeypatch.setattr(performance, '_SAMPLES', deque(maxlen=1000))
    monkeypatch.setattr(cache, '_CACHE_MAX_ENTRIES', 3)
    monkeypatch.setattr(cache, '_CACHE_MAX_BYTES', 100000)
    yield
    cache.clear_shared_payload_cache()


def test_lru_and_mutation_isolation():
    source = {'rows': [1]}
    returned = cache.set_cache('a', source)
    source['rows'].append(2)
    returned['rows'].append(3)
    cache.set_cache('b', {})
    cache.set_cache('c', {})
    assert cache.get_cache('a', 60) == {'rows': [1]}
    cache.set_cache('d', {})
    assert cache.get_cache('b', 60) is None
    assert cache.get_cache('a', 60) == {'rows': [1]}
    assert cache.cache_diagnostics()['entries'] == 3


def test_byte_budget_and_oversized_bypass(monkeypatch):
    value = {'rows': list(range(100))}
    size = cache._resident_bytes(value)
    monkeypatch.setattr(cache, '_CACHE_MAX_BYTES', size + 10)
    cache.set_cache('a', value)
    cache.set_cache('b', value)
    assert cache.get_cache('a', 60) is None
    assert cache.cache_diagnostics()['estimated_resident_bytes'] <= size + 10
    huge = {'rows': list(range(1000))}
    assert cache.set_cache('huge', huge) == huge
    assert cache.get_cache('huge', 60) is None
    assert cache.get_cache('b', 60) == value


def test_expiration_without_revisiting_old_key(monkeypatch):
    clock = [0]
    monkeypatch.setattr(cache, '_now', lambda: clock[0])
    monkeypatch.setattr(cache, '_CACHE_MAX_AGE_SECONDS', 10)
    cache.set_cache('old', {})
    clock[0] = 11
    cache.set_cache('new', {})
    assert list(cache._CACHE) == ['new']


def test_cache_hits_do_not_serialize_payload(monkeypatch):
    cache.set_cache('a', {'rows': [1]})
    monkeypatch.setattr(cache, 'estimate_payload_bytes', lambda _: pytest.fail('serialized on hit'))
    assert cache.get_cache('a', 60) == {'rows': [1]}


def test_concurrent_cache_operations_remain_bounded():
    def access(i):
        cache.set_cache(str(i), {'rows': [i]})
        cache.get_cache(str(i), 60)
        if i % 5 == 0:
            cache.clear_shared_payload_cache(str(i))
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(access, range(100)))
    assert cache.cache_diagnostics()['entries'] <= 3
    assert set(cache._CACHE) == set(cache._CACHE_SIZES)


def test_warmer_skips_past_dates_and_reports_failure(monkeypatch):
    requests = []
    def request(method, url, timeout):
        requests.append(url)
        return {'error': 'TimeoutError'} if '/models/projections/snapshot/' in url else {}
    monkeypatch.setattr(warm_game_day, '_request', request)
    result = warm_game_day.warm('https://example.test')
    assert result['status'] == 'failed'
    assert not any(result['dates']['yesterday'] in url for url in requests)
    assert sum('/models/projections/snapshot/' in url for url in requests) == 1
    assert any(row['result'].get('error') == 'deferred' for row in result['results'])
    monkeypatch.setattr(sys, 'argv', ['warm_game_day'])
    assert warm_game_day.main() == 1


def test_warmer_success_exit(monkeypatch):
    monkeypatch.setattr(warm_game_day, '_request', lambda *args: {})
    monkeypatch.setattr(sys, 'argv', ['warm_game_day'])
    assert warm_game_day.main() == 0


def test_scheduled_backfill_is_bounded_and_month_opt_in(monkeypatch):
    from contextlib import nullcontext
    from mlb_app import predicts_backfill, predicts_service
    calls = []
    def backfill(session, start, end, **kwargs):
        calls.append((start, end))
        return {'days': [], 'imported_players': 0, 'graded_now': 0}
    monkeypatch.setattr(predicts_service, 'session_factory', lambda: lambda: nullcontext(object()))
    monkeypatch.setattr(predicts_backfill, 'backfill_range', backfill)
    monkeypatch.delenv('RUN_PREDICTS_MONTH_BACKFILL', raising=False)
    run_refresh_job._run_predicts_backfill(dt.date(2026, 9, 22))
    assert calls[-1] == (dt.date(2026, 9, 21), dt.date(2026, 9, 21))
    run_refresh_job._run_predicts_backfill(dt.date(2026, 10, 1))
    assert calls[-1] == (dt.date(2026, 9, 30), dt.date(2026, 9, 30))
    monkeypatch.setenv('RUN_PREDICTS_MONTH_BACKFILL', '1')
    run_refresh_job._run_predicts_backfill(dt.date(2026, 9, 22))
    assert calls[-1] == (dt.date(2026, 9, 1), dt.date(2026, 9, 21))
