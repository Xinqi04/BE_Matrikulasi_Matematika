from fastapi import APIRouter

from app.neo4j_client import neo4j_session
from app.schemas import KonsepOut, ModulOut, VideoOut
from app.services import kg_queries

router = APIRouter(prefix="/kg", tags=["knowledge-graph"])


@router.get("/konsep", response_model=list[KonsepOut])
def get_konsep():
    with neo4j_session() as session:
        return kg_queries.list_konsep(session)


@router.get("/modul", response_model=list[ModulOut])
def get_modul():
    with neo4j_session() as session:
        return kg_queries.list_modul(session)


@router.get("/video", response_model=list[VideoOut])
def get_video():
    with neo4j_session() as session:
        return kg_queries.list_video(session)
