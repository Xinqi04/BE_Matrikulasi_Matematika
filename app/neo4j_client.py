from contextlib import contextmanager
from functools import lru_cache

from neo4j import Driver, GraphDatabase

from app.config import get_settings


@lru_cache
def get_driver() -> Driver:
    settings = get_settings()
    return GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password))


@contextmanager
def neo4j_session():
    settings = get_settings()
    driver = get_driver()
    session = driver.session(database=settings.neo4j_database)
    try:
        yield session
    finally:
        session.close()


def close_driver() -> None:
    if get_driver.cache_info().currsize:
        get_driver().close()
        get_driver.cache_clear()
