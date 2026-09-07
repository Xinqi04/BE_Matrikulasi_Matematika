from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from app.config import get_settings


@contextmanager
def postgres_connection():
    settings = get_settings()
    connection = psycopg.connect(
        dbname=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password,
        host=settings.postgres_host,
        port=settings.postgres_port,
        row_factory=dict_row,
        connect_timeout=5,
    )
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
