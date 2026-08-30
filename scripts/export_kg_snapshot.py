"""Ekspor knowledge graph Neo4j ke satu file JSON portabel."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from neo4j import GraphDatabase
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[1]
NODE_SPECS = (("Modul", "id"), ("Bab", "id"), ("SubBab", "id"), ("Konsep", "nama"), ("Materi", "id"))
RELATIONSHIP_TYPES = ("HAS_BAB", "HAS_SUBBAB", "HAS_KONSEP", "MEMBAHAS_KONSEP", "PRASYARAT", "RELATED_TO")


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")
    neo4j_uri: str = "bolt://127.0.0.1:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str
    neo4j_database: str = "neo4j"


class DockerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env.docker", extra="ignore")
    neo4j_password: str
    neo4j_bolt_port: int = 7687


def endpoint_expression(alias: str) -> str:
    cases = [
        f"WHEN '{label}' IN labels({alias}) AND {alias}.{key} IS NOT NULL "
        f"THEN {{label:'{label}', key_name:'{key}', key_value:{alias}.{key}}}"
        for label, key in NODE_SPECS
    ]
    return "CASE " + " ".join(cases) + " END"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker", action="store_true", help="Baca target dari .env.docker di folder backend")
    parser.add_argument("--uri")
    parser.add_argument("--database")
    parser.add_argument("--output", default="kg_snapshot.json")
    args = parser.parse_args()

    if args.docker:
        cfg = DockerSettings()
        uri = args.uri or f"bolt://127.0.0.1:{cfg.neo4j_bolt_port}"
        user, password, database = "neo4j", cfg.neo4j_password, args.database or "neo4j"
    else:
        cfg = AppSettings()
        uri = args.uri or cfg.neo4j_uri
        user, password, database = cfg.neo4j_user, cfg.neo4j_password, args.database or cfg.neo4j_database

    nodes: list[dict] = []
    relationships: list[dict] = []
    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        driver.verify_connectivity()
        with driver.session(database=database) as session:
            for label, key in NODE_SPECS:
                rows = session.run(
                    f"MATCH (n:{label}) WHERE n.{key} IS NOT NULL "
                    f"RETURN n.{key} AS node_key, properties(n) AS props"
                )
                nodes.extend({"label": label, "key_name": key, "key_value": row["node_key"], "properties": dict(row["props"])} for row in rows)

            start_expr, end_expr = endpoint_expression("a"), endpoint_expression("b")
            for rel_type in RELATIONSHIP_TYPES:
                rows = session.run(
                    f"MATCH (a)-[r:{rel_type}]->(b) WITH {start_expr} AS start, "
                    f"{end_expr} AS finish, properties(r) AS props "
                    "WHERE start IS NOT NULL AND finish IS NOT NULL RETURN start, finish, props"
                )
                relationships.extend({"type": rel_type, "start": dict(row["start"]), "end": dict(row["finish"]), "properties": dict(row["props"])} for row in rows)
    finally:
        driver.close()

    output = Path(args.output).resolve()
    snapshot = {"format": "matrikulasi-kg", "version": 1, "nodes": nodes, "relationships": relationships}
    output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"Snapshot dibuat: {output}")
    print(f"Node: {len(nodes)}, relasi: {len(relationships)}")


if __name__ == "__main__":
    main()
