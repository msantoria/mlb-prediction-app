from copy import deepcopy
from datetime import date, datetime, timedelta
from types import SimpleNamespace
import pytest
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mlb_app.database import Base, SharedReportArtifact
from mlb_app.final_game_snapshots import FinalGameSnapshot
from mlb_app.predicts_models import PredictsGame, PredictsPlayer, PredictsOutcome
from mlb_app import predicts_routes, predicts_service
from mlb_app.predicts_snapshots import promote, grade, lock_due
from mlb_app.predicts_sources import collect
from mlb_app.predicts_backtest import evaluate, training_records
from mlb_app.predicts_features import feature, exposure, workload, expected_arsenal, location_compatibility, process_windows, pa_view, environment
from mlb_app.predicts_probability import empirical
from mlb_app.predicts_residuals import fit, adjust, vector, FEATURES
from mlb_app.predicts_validation import asof, validate_player
from mlb_app.predicts_decisions import enrich
from mlb_app.shared_artifacts import model_projection_date_key
from mlb_app.simulation.projections.aggregator import summarize_values

DAY=date(2026,9,18)
NOW=datetime(2026,9,18,18)
START=NOW+timedelta(hours=2)


def row(pid=1,role="batter"):
    baseline={"hits":1.2,"total_bases":1.7,"home_runs":.2} if role=="batter" else {"strikeouts":5.2}
    return {"player_id":pid,"player_name":"Test Player","player_type":role,"game_pk":777,
        "date":DAY.isoformat(),"game_time":START.isoformat()+"Z","team_side":"away",
        "team_id":100,"opposing_starter_id":20,"batting_order":1 if role=="batter" else None,
        "baseline":baseline,"projection_generated_at":(NOW-timedelta(minutes=10)).isoformat()+"Z",
        "baseline_model_version":"canonical-test","provenance":"true_point_in_time_snapshot",
        "features":{name:feature(4.4 if name=="opportunity" else .3) for name in FEATURES[1:]},
        "predictions":{metric:{"adjusted":None,"probability_over_baseline":None} for metric in baseline}}


@pytest.fixture
def session():
    engine=create_engine("sqlite://",poolclass=StaticPool,connect_args={"check_same_thread":False})
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        yield session
    engine.dispose()


def final(session,game_pk=777):
    snapshot=FinalGameSnapshot(game_pk=game_pk,official_date=DAY,payload_json={
        "game_datetime":START.isoformat()+"Z","boxscore":{"away":{
            "batters":[{"id":1,"hits":2,"doubles":1,"triples":0,"home_runs":1}],
            "pitchers":[{"id":10,"strikeouts":7}]} }},finalized_at=START+timedelta(hours=3))
    session.add(snapshot); session.flush()
    return snapshot


def artifact_payload():
    players=[]
    for pid,side,team in [(1,"away",100),(10,"away",100),(20,"home",200)]:
        role="batter" if pid==1 else "pitcher"
        metrics={"plate_appearances":{"mean":4.4},"singles":{"mean":.7},"doubles":{"mean":.2},
            "triples":{"mean":.05},"home_runs":{"mean":.25}} if role=="batter" else {"strikeouts":{"mean":5.2},"batters_faced":{"mean":23}}
        players.append({"mlb_player_id":pid,"player_id":str(pid),"player_type":role,"team_side":side,
            "full_name":f"Player {pid}","team_id":team,"simulation_count":1000,"metrics":metrics})
    return {"date":DAY.isoformat(),"predicts_source_generated_at":(NOW-timedelta(minutes=5)).isoformat()+"Z",
        "workspace_contract":"model_projection_workspace_v7","games":[{"game_pk":777,"game_date":DAY.isoformat(),
        "game_time":START.isoformat()+"Z","status":"Preview","lineup_status":"confirmed",
        "away_team":{"id":100,"name":"Away"},"home_team":{"id":200,"name":"Home"},
        "away_pitcher":{"id":10,"name":"Away Starter"},"home_pitcher":{"id":20,"name":"Home Starter"},
        "sharedSimulation":{"diagnostics":{"canonical_shadow":{"player_projections":{
            "model_version":"canonical-test","simulation_count":1000,"players":players}}}}}]}


def test_capture_revision_and_duplicate_idempotency(session):
    assert promote(session,[row()],NOW)=="captured"
    assert promote(session,[row()],NOW+timedelta(minutes=1))=="unchanged"
    changed=row(); changed["baseline"]["hits"]=1.5
    assert promote(session,[changed],NOW+timedelta(minutes=2))=="captured"
    assert session.query(PredictsPlayer).count()==2
    assert session.get(PredictsGame,777).revision==2
    assert session.query(PredictsPlayer).order_by(PredictsPlayer.id).first().payload["baseline"]["hits"]==1.2


def test_two_stage_decision_board_separates_baseline_and_confirmed_lineup():
    baseline = row(1)
    baseline.update(lineup_status="projected", batting_order=1)
    confirmed = row(2)
    confirmed.update(lineup_status="confirmed", batting_order=2)
    confirmed["baseline"]["total_bases"] = 2.4
    confirmed["features"]["trend"] = feature(.9)
    confirmed["features"]["arsenal"] = feature(.8)
    enrich([baseline, confirmed], force=True)
    assert baseline["prediction_stage"] == "model_projection_baseline"
    assert confirmed["prediction_stage"] == "confirmed_lineup"
    board = confirmed["decision_board"]["total_bases"]
    assert board["mlbgpt_line"] == 2.4
    assert board["line_authority"] == "model_projections_baseline"
    assert board["convergence_score"] > baseline["decision_board"]["total_bases"]["convergence_score"]


def test_lock_and_immutable_history_in_orm_and_bulk_sql(session):
    promote(session,[row()],NOW); session.commit()
    lock_due(session,START); session.commit()
    candidate=row(); candidate["game_time"]=(START+timedelta(hours=5)).isoformat()+"Z"
    assert promote(session,[candidate],START+timedelta(minutes=1))=="locked"
    snap=session.query(PredictsPlayer).first()
    snap.payload={"changed":True}
    with pytest.raises(ValueError,match="append-only"):
        session.flush()
    session.rollback()
    with pytest.raises(Exception,match="append-only"):
        session.execute(update(PredictsPlayer).values(payload={"changed":True}))
    session.rollback()


@pytest.mark.parametrize("source,captured,starts",[(NOW+timedelta(minutes=1),NOW,START),(NOW,START,START),(NOW,START+timedelta(minutes=1),START)])
def test_future_leakage_rejected(source,captured,starts):
    with pytest.raises(ValueError): asof(source,captured,starts)


def test_final_join_preserves_baseline_and_grades_once(session):
    promote(session,[row(),row(10,"pitcher")],NOW)
    final(session)
    assert grade(session,START+timedelta(hours=4))==2
    assert grade(session,START+timedelta(hours=4))==0
    records=predicts_service.slate(session,DAY)["records"]
    assert records[0]["baseline"]["total_bases"]==1.7
    assert records[0]["outcome"]["metrics"]["total_bases"]["actual"]==6
    assert records[0]["outcome"]["metrics"]["total_bases"]["residual"]==pytest.approx(4.3)
    assert records[1]["outcome"]["metrics"]["strikeouts"]["residual"]==pytest.approx(1.8)
    result=evaluate(session,DAY,DAY)
    assert next(g for g in result["groups"] if g["metric"]=="hits")["mae"]==pytest.approx(.8)
    assert training_records(session,DAY,NOW)=={}
    assert training_records(session,DAY+timedelta(days=1),START+timedelta(hours=5))


def test_no_baseline_backfill_from_finals(session):
    final(session)
    assert grade(session,START+timedelta(hours=4))==0
    assert session.query(PredictsPlayer).count()==0


def test_final_before_candidate_blocks_grading(session):
    promote(session,[row()],NOW)
    result=final(session)
    result.payload_json={**result.payload_json,"game_datetime":(NOW-timedelta(minutes=1)).isoformat()+"Z"}
    session.flush()
    assert grade(session,START+timedelta(hours=4))==0


def test_adapter_reuses_baseline_and_preserves_missing_sources(session):
    payload=artifact_payload()
    original=deepcopy(payload)
    rows,rejected=collect(session,payload,DAY,NOW)
    assert not rejected
    assert rows[777][0]["player_id"]==1
    assert rows[777][0]["baseline"]["hits"]==pytest.approx(1.2)
    assert rows[777][0]["baseline"]["total_bases"]==pytest.approx(2.25)
    assert rows[777][0]["features"]["process"]["value"] is None
    assert rows[777][0]["features"]["opportunity"]["value"]==4.4
    assert payload==original


@pytest.mark.parametrize("corruption",["duplicate","wrong_team","bad_pa","future_source","post_start"])
def test_source_rejection(session,corruption):
    payload=artifact_payload()
    game=payload["games"][0]
    players=game["sharedSimulation"]["diagnostics"]["canonical_shadow"]["player_projections"]["players"]
    if corruption=="duplicate": players.append(deepcopy(players[0]))
    if corruption=="wrong_team": players[0]["team_id"]=999
    if corruption=="bad_pa": players[0]["metrics"]["plate_appearances"]["mean"]=50000
    if corruption=="future_source": payload["predicts_source_generated_at"]=(NOW+timedelta(hours=1)).isoformat()+"Z"
    if corruption=="post_start": game["status"]="Live"
    rows,rejected=collect(session,payload,DAY,NOW)
    assert not rows and rejected


def test_refresh_and_read_only_routes(session):
    payload=artifact_payload()
    session.add(SharedReportArtifact(artifact_key=model_projection_date_key(DAY.isoformat()),
        artifact_type="model_projection_date",target_date=DAY,payload_json=payload,
        generated_at=NOW-timedelta(minutes=5)))
    session.commit()
    assert predicts_service.refresh(session,DAY,NOW)["games"]=={"captured":1}
    assert predicts_service.refresh(session,DAY,NOW)["games"]=={"unchanged":1}
    app=FastAPI(); app.include_router(predicts_routes.router)
    app.dependency_overrides[predicts_routes.get_session]=lambda:session
    with TestClient(app) as client:
        for path in [f"/predicts?date={DAY}",f"/predicts/player/1?date={DAY}",f"/predicts/player/10?date={DAY}","/predicts/game/777","/predicts/history","/predicts/backtest","/predicts/model-health"]:
            assert client.get(path).status_code==200,path
        assert client.get(f"/predicts?date={DAY}").json()["record_count"]==3
        assert client.get('/predicts?date=invalid').status_code==422
        assert client.get('/predicts/backtest?start=2020-01-01&end=2026-09-18').status_code==422
        assert client.get('/predicts/backtest?min_expected_pa=-1').status_code==422
    assert session.query(PredictsPlayer).count()==3


def test_opportunity_exposure_workload_missingness():
    assert exposure(4.5,24,40)["expected_pa_vs_bullpen"]==pytest.approx(1.8)
    assert exposure(4.5,None,40)["value"] is None
    result=workload([{"pitches":80,"batters_faced":21},{"pitches":100,"batters_faced":27}])
    assert result["value"]==90 and result["pitch_distribution"]["p90_plus"]==.5
    assert workload([{"pitches":50000}])["value"] is None


def test_arsenal_normalization_and_shrinkage():
    pitches=[{"pitch_type":"FF","stand":"R"}]*80+[{"pitch_type":"SL","stand":"R"}]*20
    rows=[SimpleNamespace(pitch_type="FF",xwoba=.8,batted_ball_count=1),SimpleNamespace(pitch_type="SL",xwoba=.3,batted_ball_count=100)]
    result=expected_arsenal(pitches,rows,"R")
    assert sum(result["expected_distribution"].values())==pytest.approx(1)
    assert result["value"]<result["raw"]
    assert expected_arsenal(pitches,rows,"L")["value"] is None


def test_location_pa_windows_and_real_change():
    pitches=[{"game_pk":100,"at_bat_number":i,"pitch_number":1,"events":"single",
        "pitch_type":"FF","plate_x":0,"plate_z":2.5,"stand":"R","estimated_woba_using_speedangle":(.5 if i<25 else .2)+(i%2)*.1} for i in range(150)]
    windows,trend=process_windows(pitches,"batter")
    assert windows["25"]["sample_size"]==25
    assert trend["value"]>0 and trend["baseline_sample_size"]==100
    assert len(pa_view(pitches+pitches))==150
    result=location_compatibility(pitches,pitches,"R")
    assert result["coverage"]==1 and result["value"] is not None


def test_distributions_and_weather_are_not_fabricated():
    result=empirical([0,1,1,2],1)
    assert result["probability_over_baseline"]==.25
    assert result["probability_under_baseline"]==.25
    assert result["probability_equal_baseline"]==.5
    assert result["p0"]==.25
    summary=summarize_values([0,1,1,2])
    assert summary.p0==.25 and summary.p1_plus==.75
    assert environment({"weather":{"temperature_f":80}})["air_density_kg_m3"] is None
    assert 1<environment({"weather":{"temperature_f":80,"humidity_pct":60,"pressure_hpa":1013}})["air_density_kg_m3"]<1.3


def test_temporal_fit_cold_start_and_true_attribution():
    assert fit([]) is None
    records=[{"snapshot_id":i,"date":(DAY-timedelta(days=30-i//10)).isoformat(),
              "x":[1.2,4.4,.3,None,None,None,None,None,None],"residual":1.0+(i%3)*.1} for i in range(200)]
    model=fit(records)
    assert model["training_count"]==150 and model["holdout_count"]==50
    assert model["status"]=="ready"
    sample=row()
    result=adjust(sample,"hits",model,records)
    assert result["adjusted"]>sample["baseline"]["hits"]
    assert sum(v["value"] for v in result["attributions"])==pytest.approx(result["expected_residual"])
    assert sum(result[k] for k in ("probability_over_baseline","probability_under_baseline","probability_equal_baseline"))==pytest.approx(1)
    assert adjust(sample,"hits",None,[])["adjusted"] is None


def test_routes_registered_without_replacing_existing_surfaces():
    from mlb_app.app import create_app
    paths=set(create_app().openapi()["paths"])
    for route in ('/health','/matchups','/matchup/{game_pk}','/models/projections','/my-dashboard/reports/query',
        '/my-dashboard/reports/export.csv','/live/scoreboard','/final','/predicts','/predicts/backtest'):
        assert route in paths


def test_opponent_quality_adjustment_and_sample_gate():
    from mlb_app.predicts_features import opponent_adjusted
    pool={1:SimpleNamespace(player_type="pitcher",xwoba=.5,plate_appearances=100,updated_at=NOW),
          2:SimpleNamespace(player_type="pitcher",xwoba=.2,plate_appearances=100,updated_at=NOW)}
    pitches=[{"game_pk":10,"at_bat_number":i,"pitcher_id":1,"events":"single",
              "estimated_woba_using_speedangle":.6} for i in range(50)]
    result=opponent_adjusted(pitches,"batter",pool,NOW)
    assert result["value"]<result["raw_recent"]
    assert result["opponent_quality"]==.5
    assert opponent_adjusted(pitches[:5],"batter",pool,NOW)["value"] is None


def test_stale_projection_refresh_still_commits_final_grades(session):
    promote(session,[row()],NOW); final(session); session.commit()
    payload=artifact_payload()
    session.add(SharedReportArtifact(artifact_key=model_projection_date_key(DAY.isoformat()),
        artifact_type="model_projection_date",target_date=DAY,payload_json=payload,
        generated_at=NOW-timedelta(days=1))); session.commit()
    with pytest.raises(ValueError,match="stale"):
        predicts_service.refresh(session,DAY,START+timedelta(hours=4))
    session.rollback()
    assert session.query(PredictsOutcome).count()==1


def test_full_app_read_regressions_with_local_canonical_sources(session,monkeypatch):
    from contextlib import nullcontext
    from mlb_app import app as application, model_projection_routes
    monkeypatch.setattr(application,"_get_session",lambda:lambda:nullcontext(session))
    monkeypatch.setattr(application,"generate_matchups_for_date",lambda s,d:[{"game_pk":777,"date":d}])
    monkeypatch.setattr(application,"_live_cache_get",lambda key:{"date":DAY.isoformat(),"games":[]})
    monkeypatch.setattr(model_projection_routes,"get_model_projection_payload",lambda d:artifact_payload())
    app=application.create_app()
    with TestClient(app) as client:
        for route in ('/health',f'/matchups?date={DAY}',f'/models/projections?date={DAY}',
                      f'/live/scoreboard?date={DAY}',f'/final?date={DAY}&hydrate=false'):
            assert client.get(route).status_code==200,route


def test_locked_game_pointer_cannot_be_changed_by_bulk_sql(session):
    promote(session,[row()],NOW); session.commit()
    lock_due(session,START); session.commit()
    with pytest.raises(Exception,match="locked"):
        session.execute(update(PredictsGame).values(revision=900))
    session.rollback()


def test_projection_refresh_schedules_predicts_after_success(monkeypatch):
    from fastapi import BackgroundTasks
    from mlb_app import model_projection_routes
    tasks=BackgroundTasks()
    monkeypatch.setattr(model_projection_routes,"warm_model_projection_payload",lambda date:{"warmed":True})
    assert model_projection_routes.snapshot_model_projections(DAY.isoformat(),tasks)=={"warmed":True}
    assert len(tasks.tasks)==1
    assert tasks.tasks[0].args==(DAY.isoformat(),)


def test_slow_older_refresh_cannot_replace_newer_candidate(session):
    promote(session,[row()],NOW)
    changed=row(); changed["baseline"]["hits"]=2
    promote(session,[changed],NOW+timedelta(minutes=2))
    assert promote(session,[row()],NOW+timedelta(minutes=1))=="superseded"
    assert predicts_service.slate(session,DAY)["records"][0]["baseline"]["hits"]==2


def test_postgres_additive_schema_compiles_with_history_guards():
    from sqlalchemy import create_mock_engine
    from mlb_app.predicts_models import PredictsModelRun
    statements=[]
    engine=create_mock_engine('postgresql://',lambda sql,*a,**kw: statements.append(str(sql.compile(dialect=engine.dialect))))
    Base.metadata.create_all(engine,tables=[PredictsGame.__table__,PredictsPlayer.__table__,PredictsOutcome.__table__,PredictsModelRun.__table__],checkfirst=False)
    text='\n'.join(statements)
    assert 'CREATE TABLE predicts_player_snapshots' in text
    assert 'CREATE TRIGGER predicts_player_snapshots_immutable' in text
    assert 'CREATE TRIGGER predicts_locked_game' in text
    assert 'DROP TABLE' not in text and 'ALTER TABLE' not in text


def test_matchup_detail_dashboard_query_and_csv_http_contracts(session,monkeypatch):
    from contextlib import nullcontext
    from inspect import signature
    from mlb_app import app as application, my_dashboard_routes, dashboard_projection_report_query
    monkeypatch.setattr(application,'_get_session',lambda:lambda:nullcontext(session))
    monkeypatch.setattr(my_dashboard_routes,'session_factory',lambda:lambda:nullcontext(session))
    monkeypatch.setattr(dashboard_projection_report_query,'get_model_projection_payload',lambda date:artifact_payload())
    monkeypatch.setattr(application,'_game_from_schedule',lambda *a,**k:{
        'gameDate':START.isoformat()+'Z','teams':{'away':{'team':{'name':'Away'}},'home':{'team':{'name':'Home'}}},
        'status':{'detailedState':'Scheduled'}})
    monkeypatch.setattr(application,'_extract_lineups_for_game',lambda **kw:([],[],'missing','missing'))
    for name in ('build_projected_lineup_offense_profile','compute_environment_profile','compute_pitcher_profile',
                 'build_matchup_analysis','build_lineup_pa_outcome_model','simulate_half_innings','build_bullpen_profile',
                 'build_bullpen_pa_outcome_model','build_game_simulation','build_bullpen_adjusted_game_simulation','build_shared_game_simulation'):
        monkeypatch.setattr(application,name,lambda *a,**kw:{})
    app=application.create_app()
    auth=signature(my_dashboard_routes.my_dashboard_report_export).parameters['_principal'].default.dependency
    app.dependency_overrides[auth]=lambda:object()
    request={'report_type':'model_projection_players','as_of_date':DAY.isoformat(),'selected_fields':['full_name','mlb_player_id']}
    with TestClient(app) as client:
        assert client.get('/matchup/777').status_code==200
        response=client.post('/my-dashboard/reports/query',json=request)
        assert response.status_code==200,response.text
        assert len(response.json()['records'])==3
        exported=client.post('/my-dashboard/reports/export.csv',json=request)
        assert exported.status_code==200,exported.text
        assert 'Player 1' in exported.text and 'Player 20' in exported.text

def test_archive_backfill_imports_only_saved_pregame_projection(session):
    from mlb_app.predicts_backfill import backfill_day
    past=DAY-timedelta(days=1)
    payload=artifact_payload(); payload['date']=past.isoformat()
    payload['games'][0]['game_date']=past.isoformat()
    payload['games'][0]['game_time']=(NOW-timedelta(days=1)+timedelta(hours=2)).isoformat()+'Z'
    captured=NOW-timedelta(days=1)
    payload.pop('predicts_source_generated_at')
    session.add(SharedReportArtifact(artifact_key='old-projection',artifact_type='model_projection_date',
        target_date=past,payload_json=payload,generated_at=captured,updated_at=captured))
    session.commit()
    report=backfill_day(session,past,now=NOW)
    assert report['imported_games']==1 and report['imported_players']==3
    saved=session.query(PredictsPlayer).first().payload
    assert saved['provenance']=='archived_pregame_projection'
    assert saved['features']['process']['value'] is None
    assert saved['predictions'][next(iter(saved['predictions']))]['status']=='archived_baseline'
    assert backfill_day(session,past,now=NOW)['imported_games']==0


def test_probable_starter_without_directory_team_is_accepted(session):
    payload=artifact_payload()
    players=payload['games'][0]['sharedSimulation']['diagnostics']['canonical_shadow']['player_projections']['players']
    next(p for p in players if p['player_id']=='10')['team_id']=None
    rows,rejected=collect(session,payload,DAY,NOW)
    assert 777 in rows
    assert not rejected


@pytest.mark.parametrize('status', ['unconfirmed', 'not confirmed', 'projected', '', None])
def test_only_explicit_confirmation_promotes(status):
    candidate = row(); candidate['lineup_status'] = status
    candidate['predictions']['hits'] = {'status': 'ready', 'adjusted': 2.0}
    enrich([candidate])
    assert candidate['prediction_stage'] == 'model_projection_baseline'
    assert candidate['decision_board']['hits']['mlbgpt_line'] == 1.2


def test_pitcher_lower_allowed_xwoba_ranks_higher():
    good, poor = row(10, 'pitcher'), row(20, 'pitcher')
    for candidate in (good, poor):
        candidate['lineup_status'] = 'confirmed'
    good['features']['process'] = feature(.2)
    poor['features']['process'] = feature(.4)
    good['features']['trend'] = feature(-.5)
    poor['features']['trend'] = feature(.5)
    enrich([good, poor])
    assert good['decision_board']['strikeouts']['convergence_score'] > poor['decision_board']['strikeouts']['convergence_score']


def test_market_identity_cutoff_and_repeat_reads():
    from mlb_app.predicts_decisions import attach_markets
    candidate = row(); candidate['as_of'] = NOW.isoformat()+'Z'
    enrich([candidate])
    def market(**changes):
        values = dict(player_id=1, player_name='Test Player', game_pk=777,
            captured_at=NOW-timedelta(minutes=2), market_key='player_hits',
            market_name='Player Hits', book='Bet105', provider='bet105',
            selection_label='Over', line=1.5, price=-110, implied_probability=.52)
        return SimpleNamespace(**{**values, **changes})
    prices = [market(), market(game_pk=778), market(captured_at=NOW+timedelta(minutes=1)),
              market(player_id=None), market(market_key='hits_runs_rbis', market_name='Hits Runs RBIs')]
    attach_markets([candidate], prices)
    attach_markets([candidate], prices)
    assert len(candidate['decision_board']['hits']['book_markets']) == 1
    assert candidate['decision_board']['hits']['book_markets'][0]['captured_at'] == (NOW-timedelta(minutes=2)).isoformat()+'Z'


def test_backtest_never_invents_historical_shortlists(session):
    candidate = row(); candidate['lineup_status'] = 'confirmed'
    promote(session, [candidate], NOW)
    final(session); grade(session, START+timedelta(hours=4))
    result = evaluate(session, DAY, DAY)
    assert result['groups']
    assert result['decision_performance'] == []


def test_results_report_equal_separately(session):
    candidate = row(); candidate['lineup_status'] = 'confirmed'; candidate['baseline']['hits'] = 2
    enrich([candidate]); promote(session, [candidate], NOW)
    final(session); grade(session, START+timedelta(hours=4))
    result = evaluate(session, DAY, DAY)
    hits = next(r for r in result['decision_performance'] if r['metric'] == 'hits')
    assert (hits['above'], hits['below'], hits['equal']) == (0, 0, 1)


def test_tracker_retirement_preserves_dashboard_routes():
    from mlb_app.model_tracker_routes import router
    paths = {route.path for route in router.routes}
    assert not any(path.startswith('/model-tracker') for path in paths)
    assert '/my-dashboard/auth/login' in paths
    assert '/my-dashboard/workspace' in paths
    assert '/my-dashboard/folders/{folder_id}' in paths
