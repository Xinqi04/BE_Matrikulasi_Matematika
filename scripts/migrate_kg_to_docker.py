"""Salin hanya knowledge graph dari Neo4j lama ke instance Neo4j Docker.

Password dibaca dari SOURCE_NEO4J_PASSWORD dan TARGET_NEO4J_PASSWORD agar tidak tampil di history
terminal. Script tidak menyalin User, Soal, UjianModul, JawabanUjian, atau relasi transaksional.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from typing import Any

from neo4j import GraphDatabase


@dataclass(frozen=True)
class NodeSpec:
    label: str
    key: str


NODE_SPECS = (
    NodeSpec("Modul", "id"),
    NodeSpec("Bab", "id"),
    NodeSpec("SubBab", "id"),
    NodeSpec("Konsep", "nama"),
    NodeSpec("Materi", "id"),
)

RELATIONSHIP_TYPES = (
    "HAS_BAB",
    "HAS_SUBBAB",
    "HAS_KONSEP",
    "MEMBAHAS_KONSEP",
    "PRASYARAT",
    "RELATED_TO",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-uri", default="bolt://localhost:7687")
    parser.add_argument("--source-user", default="neo4j")
    parser.add_argument("--source-database", default="matrikulasi")
    parser.add_argument("--target-uri", default="bolt://localhost:7688")
    parser.add_argument("--target-user", default="neo4j")
    parser.add_argument("--target-database", default="neo4j")
    return parser.parse_args()


def required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"Environment variable {name} wajib diisi.")
    return value


def copy_nodes(source_session, target_session) -> dict[str, int]:
    counts: dict[str, int] = {}
    for spec in NODE_SPECS:
        rows = list(source_session.run(
            f"MATCH (n:{spec.label}) WHERE n.{spec.key} IS NOT NULL "
            f"RETURN n.{spec.key} AS node_key, properties(n) AS props"
        ))
        if rows:
            target_session.run(
                f"UNWIND $rows AS row "
                f"MERGE (n:{spec.label} {{{spec.key}: row.node_key}}) "
                "SET n += row.props",
                rows=[{"node_key": row["node_key"], "props": dict(row["props"])} for row in rows],
            ).consume()
        counts[spec.label] = len(rows)
    return counts


def endpoint_expression(alias: str) -> str:
    cases = []
    for spec in NODE_SPECS:
        cases.append(
            f"WHEN '{spec.label}' IN labels({alias}) AND {alias}.{spec.key} IS NOT NULL "
            f"THEN {{label: '{spec.label}', key_name: '{spec.key}', key_value: {alias}.{spec.key}}}"
        )
    return "CASE " + " ".join(cases) + " END"


def copy_relationships(source_session, target_session) -> dict[str, int]:
    result: dict[str, int] = {}
    start_expr = endpoint_expression("a")
    end_expr = endpoint_expression("b")

    for rel_type in RELATIONSHIP_TYPES:
        rows = list(source_session.run(
            f"MATCH (a)-[r:{rel_type}]->(b) "
            f"WITH {start_expr} AS start, {end_expr} AS finish, properties(r) AS props "
            "WHERE start IS NOT NULL AND finish IS NOT NULL "
            "RETURN start, finish, props"
        ))
        for row in rows:
            start: dict[str, Any] = row["start"]
            finish: dict[str, Any] = row["finish"]
            # Semua identifier dinamis berasal dari whitelist statis di atas.
            target_session.run(
                f"MATCH (a:{start['label']} {{{start['key_name']}: $start_key}}) "
                f"MATCH (b:{finish['label']} {{{finish['key_name']}: $finish_key}}) "
                f"MERGE (a)-[r:{rel_type}]->(b) SET r += $props",
                start_key=start["key_value"],
                finish_key=finish["key_value"],
                props=dict(row["props"]),
            ).consume()
        result[rel_type] = len(rows)
    return result


def main() -> None:
    args = parse_args()
    source_driver = GraphDatabase.driver(
        args.source_uri, auth=(args.source_user, required_env("SOURCE_NEO4J_PASSWORD"))
    )
    target_driver = GraphDatabase.driver(
        args.target_uri, auth=(args.target_user, required_env("TARGET_NEO4J_PASSWORD"))
    )
    try:
        source_driver.verify_connectivity()
        target_driver.verify_connectivity()
        with source_driver.session(database=args.source_database) as source_session:
            with target_driver.session(database=args.target_database) as target_session:
                node_counts = copy_nodes(source_session, target_session)
                relationship_counts = copy_relationships(source_session, target_session)
    finally:
        source_driver.close()
        target_driver.close()

    print("Node tersalin:")
    for label, count in node_counts.items():
        print(f"  {label}: {count}")
    print("Relasi tersalin:")
    for rel_type, count in relationship_counts.items():
        print(f"  {rel_type}: {count}")
    print("Migrasi knowledge graph selesai.")


if __name__ == "__main__":
    main()
