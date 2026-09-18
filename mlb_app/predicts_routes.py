"""Read-only MLBGPT Predicts namespace, following existing public research access."""
from datetime import date as Date, timedelta
from typing import Optional, Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from .my_dashboard_dataset_runtime import mlb_business_date
from . import predicts_service as service
from .predicts_backtest import evaluate, history_query

router = APIRouter(prefix="/predicts", tags=["mlbgpt-predicts"])


def get_session():
    with service.session_factory()() as session:
        yield session


def _range(start, end):
    end = end or mlb_business_date()
    start = start or end-timedelta(days=30)
    if start>end or (end-start).days>366:
        raise HTTPException(422, "Date range must be ordered and at most 366 days")
    return start,end


@router.get("")
def predictions(date: Optional[Date]=None, session=Depends(get_session)):
    return service.slate(session,date or mlb_business_date())


@router.get("/game/{game_pk}")
def game_predictions(game_pk:int,session=Depends(get_session)):
    if game_pk<=0:
        raise HTTPException(422,"Invalid game ID")
    return service.slate(session,game_pk=game_pk)


@router.get("/player/{player_id}")
def player_predictions(player_id:int,date:Optional[Date]=None,session=Depends(get_session)):
    if player_id<=0:
        raise HTTPException(422,"Invalid player ID")
    return service.slate(session,date or mlb_business_date(),player_id=player_id)


@router.get("/history")
def history(start:Optional[Date]=None,end:Optional[Date]=None,
            player_id:Optional[int]=Query(None,gt=0),offset:int=Query(0,ge=0),
            limit:int=Query(100,ge=1,le=200),session=Depends(get_session)):
    start,end=_range(start,end)
    query=history_query(start,end)
    if player_id:
        from .predicts_models import PredictsPlayer
        query=query.where(PredictsPlayer.player_id==player_id)
    from .predicts_models import PredictsPlayer
    results=session.execute(query.order_by(PredictsPlayer.id.desc()).offset(offset).limit(limit+1)).all()
    return {"records":[{**p.payload,"snapshot_id":p.id,"outcome":o.payload,"graded_at":o.graded_at.isoformat()+"Z"}
                       for p,o,g in results[:limit]],"offset":offset,"limit":limit,"has_more":len(results)>limit}


@router.get("/backtest")
def backtest(start:Optional[Date]=None,end:Optional[Date]=None,
    player_type:Optional[Literal["batter","pitcher"]]=None,
    metric:Optional[Literal["hits","total_bases","home_runs","strikeouts"]]=None,
    model_version:Optional[str]=None,lineup_position:Optional[int]=Query(None,ge=1,le=9),
    min_expected_pa:Optional[float]=Query(None,ge=0,le=10),min_arsenal:Optional[float]=Query(None,ge=0,le=2),
    session=Depends(get_session)):
    start,end=_range(start,end)
    return evaluate(session,start,end,player_type=player_type,metric=metric,model_version=model_version,
                    lineup_position=lineup_position,min_expected_pa=min_expected_pa,min_arsenal=min_arsenal)


@router.get("/model-health")
def model_health(session=Depends(get_session)):
    return service.health(session,mlb_business_date())
