"""Commit graph writes and a replay receipt in the same Neo4j transaction."""
import json
from app.neo4j_client import neo4j_session


def initialize():
    from app.services.pdf_pipeline import _setup_constraints
    from app.services.youtube_pipeline import _setup_constraint_materi
    with neo4j_session() as session:
        session.run("CREATE CONSTRAINT draft_confirmation_id IF NOT EXISTS FOR (r:DraftConfirmation) REQUIRE r.id IS UNIQUE").consume()
        session.execute_write(_setup_constraints)
        session.execute_write(_setup_constraint_materi)
        # Materi nodes are published only after confirmation. Pending previews
        # live in job_drafts, so legacy graph 'draft' labels are stale metadata.
        session.run("""
            MATCH (m:Materi {tipe:'youtube'})
            WHERE m.status_validasi IS NULL OR m.status_validasi = 'draft'
            SET m.status_validasi = 'valid'
        """).consume()


def read_receipt(job_id):
    with neo4j_session() as session:
        row = session.execute_read(lambda tx: tx.run("MATCH (r:DraftConfirmation {id:$id}) RETURN r.response AS response", id=job_id).single())
        return json.loads(row["response"]) if row else None


def apply_once(job_id, write):
    def transaction(tx):
        row = tx.run("MERGE (r:DraftConfirmation {id:$id}) SET r.locked=true RETURN r.response AS response", id=job_id).single()
        if row["response"] is not None:
            return json.loads(row["response"])
        response = write(tx)
        tx.run("MATCH (r:DraftConfirmation {id:$id}) SET r.response=$response REMOVE r.locked", id=job_id, response=json.dumps(response)).consume()
        return response
    with neo4j_session() as session:
        return session.execute_write(transaction)
