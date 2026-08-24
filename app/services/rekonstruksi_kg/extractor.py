import logging
import json
from typing import Callable, Optional

from google import genai

from app.services.rekonstruksi_kg.schemas import (
    ExtractionUnit,
    ExtractionResult,
    ExtractionError,
    Concept,
    ConsolidationResult,
)
from app.services.rekonstruksi_kg.prompts import EXTRACTION_PROMPT, CONSOLIDATION_PROMPT
from app.services.rekonstruksi_kg.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)


def _chunk_text(text: str, max_chars: int) -> list[str]:
    """Split text into pieces up to max_chars, breaking at paragraph/line/word boundaries."""
    if len(text) <= max_chars:
        return [text]

    chunks = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + max_chars, n)
        if end < n:
            split_at = text.rfind("\n\n", start, end)
            if split_at <= start:
                split_at = text.rfind("\n", start, end)
            if split_at <= start:
                split_at = text.rfind(" ", start, end)
            if split_at <= start:
                split_at = end
            else:
                split_at += 1
        else:
            split_at = end
        chunks.append(text[start:split_at])
        start = split_at
    return chunks


class ConceptExtractor:
    def __init__(self, client: genai.Client, model: str, rate_limiter: RateLimiter, max_unit_tokens: int):
        self.client = client
        self.model = model
        self.rate_limiter = rate_limiter
        self.max_unit_tokens = max_unit_tokens

    def extract_sequential(
        self,
        units: list[ExtractionUnit],
        on_progress: Optional[Callable[[int, int, str], None]] = None,
    ) -> tuple[list[ExtractionResult], list[ExtractionError]]:
        results = []
        errors = []
        report = on_progress or (lambda current, total, title: None)

        total = len(units)
        for i, unit in enumerate(units, 1):
            logger.info(f"[{i}/{total}] Processing: {unit.title}")
            report(i, total, unit.title)

            max_chars = self.max_unit_tokens * 4  # approx token count
            chunks = _chunk_text(unit.raw_text, max_chars)
            if len(chunks) > 1:
                logger.info(f"[{i}/{total}] Unit text is large ({len(unit.raw_text)} chars), split into {len(chunks)} chunks")

            merged_konsep = {}
            unit_failed = False

            for ci, chunk in enumerate(chunks, 1):
                label = f"{i}/{total}" if len(chunks) == 1 else f"{i}/{total} chunk {ci}/{len(chunks)}"
                prompt = EXTRACTION_PROMPT.format(
                    unit_id=unit.unit_id,
                    title=unit.title,
                    summary=unit.summary,
                    parent=unit.parent_id or "None",
                    raw_text=chunk
                )

                success = False
                for attempt in range(1, self.rate_limiter.max_retries + 1):
                    try:
                        logger.info(f"[{label}] Extraction started (Attempt {attempt})")
                        response = self.client.models.generate_content(
                            model=self.model,
                            contents=prompt,
                            config={
                                "response_mime_type": "application/json",
                                "response_schema": ExtractionResult,
                            }
                        )

                        data = json.loads(response.text)
                        chunk_result = ExtractionResult(**data)
                        for k in chunk_result.konsep:
                            merged_konsep[k.nama.strip().lower()] = k
                        logger.info(f"[{label}] Extraction success")
                        success = True
                        self.rate_limiter.wait()
                        break
                    except Exception as e:
                        logger.error(f"[EXTRACTION] unit_{unit.unit_id} chunk {ci} failed on attempt {attempt}: {e}")
                        self.rate_limiter.backoff(attempt)

                if not success:
                    logger.error(f"[EXTRACTION] unit_{unit.unit_id} chunk {ci} failed permanently")
                    unit_failed = True
                    break

            if unit_failed:
                errors.append(ExtractionError(
                    unit_id=unit.unit_id,
                    stage="concept_extraction",
                    error="Failed after maximum retries"
                ))
            else:
                results.append(ExtractionResult(
                    unit_id=unit.unit_id,
                    konsep=list(merged_konsep.values())
                ))

            logger.info(f"[EXTRACTION] continuing queue")

        return results, errors

    def consolidate(self, extractions: list[ExtractionResult], units: list[ExtractionUnit]) -> list[ExtractionResult]:
        logger.info("Starting consolidation...")

        unit_titles = {u.unit_id: u.title for u in units}
        valid_unit_ids = set(unit_titles.keys())

        flat_concepts = [
            {
                "unit_id": ext.unit_id,
                "unit_title": unit_titles.get(ext.unit_id, ""),
                "nama": k.nama,
                "deskripsi": k.deskripsi,
            }
            for ext in extractions
            for k in ext.konsep
        ]

        if not flat_concepts:
            logger.info("No concepts to consolidate.")
            return extractions

        # Since consolidation might be large, we might need to batch it in a real-world scenario.
        # Here we do a simple single call.
        prompt = CONSOLIDATION_PROMPT.replace(
            "{units_json}", json.dumps([{"unit_id": u, "title": t} for u, t in unit_titles.items()], ensure_ascii=False)
        ).replace(
            "{concepts_json}", json.dumps(flat_concepts, ensure_ascii=False)
        )

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config={
                    "response_mime_type": "application/json",
                    "response_schema": ConsolidationResult,
                }
            )

            data = json.loads(response.text)
            result = ConsolidationResult(**data)

            by_unit = {u: [] for u in valid_unit_ids}
            for c in result.konsep:
                if c.unit_id not in valid_unit_ids:
                    logger.warning(f"Consolidation returned unknown unit_id '{c.unit_id}' for concept '{c.nama}', skipping")
                    continue
                by_unit[c.unit_id].append(Concept(nama=c.nama, deskripsi=c.deskripsi))

            logger.info("Consolidation finished.")
            return [
                ExtractionResult(unit_id=ext.unit_id, konsep=by_unit.get(ext.unit_id, []))
                for ext in extractions
            ]
        except Exception as e:
            logger.error(f"Consolidation failed: {e}")
            return extractions
