from fastapi import APIRouter
from fastapi.responses import JSONResponse
from neo4j import Query
from app.postgres_client import postgres_connection
from app.neo4j_client import neo4j_session

router = APIRouter()


@router.get("/ready", include_in_schema=False)
def ready():
    checks = {}
    try:
        with postgres_connection() as conn:
            conn.execute("SET LOCAL statement_timeout='3s'")
            conn.execute("SELECT 1").fetchone()
        checks["postgres"] = "ok"
    except Exception:
        checks["postgres"] = "unavailable"
    try:
        with neo4j_session() as session:
            session.run(Query("RETURN 1", timeout=3)).consume()
        checks["neo4j"] = "ok"
    except Exception:
        checks["neo4j"] = "unavailable"
    healthy = all(value == "ok" for value in checks.values())
    return JSONResponse({"status": "ok" if healthy else "unavailable", "checks": checks}, status_code=200 if healthy else 503)
