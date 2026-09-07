"""Import the bundled KG snapshot only into a graph with no application data."""
import argparse
import subprocess
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.neo4j_client import neo4j_session
from app.config import get_settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    args = parser.parse_args()
    with neo4j_session() as session:
        count = session.run("MATCH (n) RETURN count(n) AS count").single()["count"]
    if count:
        raise SystemExit("Graph sudah berisi data; bootstrap tidak mengubah graph yang sudah digunakan")
    settings = get_settings()
    subprocess.run([sys.executable, str(Path(__file__).with_name("import_kg_snapshot.py")), "--uri", settings.neo4j_uri, "--database", settings.neo4j_database, "--input", args.input], check=True)


if __name__ == "__main__":
    main()
