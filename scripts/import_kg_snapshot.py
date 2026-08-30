"""Impor snapshot JSON knowledge graph ke Neo4j Docker."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from neo4j import GraphDatabase
from pydantic_settings import BaseSettings, SettingsConfigDict

from export_kg_snapshot import NODE_SPECS, RELATIONSHIP_TYPES


BACKEND_DIR = Path(__file__).resolve().parents[1]
ALLOWED_NODES = set(NODE_SPECS)


class DockerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env.docker", extra="ignore")
    neo4j_password: str
    neo4j_bolt_port: int = 7687


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uri")
    parser.add_argument("--database", default="neo4j")
    parser.add_argument("--input", default="kg_snapshot.json")
    args = parser.parse_args()
    cfg = DockerSettings()
    uri = args.uri or f"bolt://127.0.0.1:{cfg.neo4j_bolt_port}"
    snapshot = json.loads(Path(args.input).resolve().read_text(encoding="utf-8"))

    if snapshot.get("format") != "matrikulasi-kg" or snapshot.get("version") != 1:
        raise SystemExit("Format snapshot tidak didukung.")
    for node in snapshot.get("nodes", []):
        if (node.get("label"), node.get("key_name")) not in ALLOWED_NODES:
            raise SystemExit(f"Node tidak diizinkan: {node.get('label')}")
    for rel in snapshot.get("relationships", []):
        if rel.get("type") not in RELATIONSHIP_TYPES:
            raise SystemExit(f"Relasi tidak diizinkan: {rel.get('type')}")

    driver = GraphDatabase.driver(uri, auth=("neo4j", cfg.neo4j_password))
    try:
        driver.verify_connectivity()
        with driver.session(database=args.database) as session:
            for node in snapshot["nodes"]:
                session.run(
                    f"MERGE (n:{node['label']} {{{node['key_name']}:$key}}) SET n += $props",
                    key=node["key_value"], props=node["properties"],
                ).consume()
            for rel in snapshot["relationships"]:
                start, end = rel["start"], rel["end"]
                if (start.get("label"), start.get("key_name")) not in ALLOWED_NODES or (end.get("label"), end.get("key_name")) not in ALLOWED_NODES:
                    raise SystemExit("Endpoint relasi tidak diizinkan.")
                session.run(
                    f"MATCH (a:{start['label']} {{{start['key_name']}:$a}}) "
                    f"MATCH (b:{end['label']} {{{end['key_name']}:$b}}) "
                    f"MERGE (a)-[r:{rel['type']}]->(b) SET r += $props",
                    a=start["key_value"], b=end["key_value"], props=rel["properties"],
                ).consume()
    finally:
        driver.close()
    print(f"Node: {len(snapshot['nodes'])}, relasi: {len(snapshot['relationships'])} berhasil diimpor.")


if __name__ == "__main__":
    main()
