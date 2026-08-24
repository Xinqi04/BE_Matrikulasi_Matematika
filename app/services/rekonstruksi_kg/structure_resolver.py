import logging
import json

from google import genai

from app.services.rekonstruksi_kg.schemas import DocumentRepresentation, StructureUnit, StructureResponse
from app.services.rekonstruksi_kg.prompts import STRUCTURE_RESOLVER_PROMPT
from app.services.rekonstruksi_kg.helpers import generate_unit_id

logger = logging.getLogger(__name__)


class StructureResolver:
    def __init__(self, doc_rep: DocumentRepresentation, client: genai.Client, model: str):
        self.doc_rep = doc_rep
        self.client = client
        self.model = model

    def resolve(self) -> list[StructureUnit]:
        logger.info("[STRUCTURE] Starting structure resolution")

        # Level 1: TOC check
        if self.doc_rep.toc and len(self.doc_rep.toc) > 0:
            logger.info("[STRUCTURE] TOC found, attempting to use TOC")
            units = self._parse_toc()
            if units:
                return units

        # Level 2 & 3: If TOC is missing or insufficient, use Gemini
        logger.info("[STRUCTURE] TOC unavailable or insufficient. Calling Gemini structure model")
        return self._resolve_with_gemini()

    def _parse_toc(self) -> list[StructureUnit]:
        # A simple heuristic to parse TOC. If it fails or is flat, we might fallback.
        units = []
        current_bab = None
        total_pages = len(self.doc_rep.pages)

        # This basic TOC parser assumes level 1 is BAB and level 2 is SUBBAB.
        # Need to assign end_pages based on the next item's start_page.
        for i, (level, title, page) in enumerate(self.doc_rep.toc):
            if page < 1 or page > total_pages:
                logger.warning(f"[STRUCTURE] Skipping TOC entry with broken page number ({page}): {title}")
                continue
            unit_id = generate_unit_id()
            if level == 1:
                current_bab = unit_id
                units.append(StructureUnit(
                    id=unit_id,
                    level="BAB",
                    title=title,
                    parent_id=None,
                    start_page=page,
                    end_page=page,  # Will be updated
                    summary=f"Bab ini membahas tentang {title}.",
                    has_children=False
                ))
            elif level == 2 and current_bab:
                # Update parent has_children
                for u in units:
                    if u.id == current_bab:
                        u.has_children = True

                units.append(StructureUnit(
                    id=unit_id,
                    level="SUBBAB",
                    title=title,
                    parent_id=current_bab,
                    start_page=page,
                    end_page=page,
                    summary=f"Subbab ini membahas materi spesifik mengenai {title}.",
                    has_children=False
                ))

        # Update end_pages
        for i in range(len(units)):
            if i < len(units) - 1:
                units[i].end_page = units[i + 1].start_page
            else:
                units[i].end_page = total_pages

        if not units:
            return []

        # Sanity check: a TOC that stops far short of the document's last page
        # (e.g. bookmarks only added for part of the document) is unreliable -
        # fall back to heading detection instead of silently dropping the rest.
        last_start_page = units[-1].start_page
        coverage = last_start_page / total_pages
        if coverage < 0.8:
            logger.warning(
                f"[STRUCTURE] TOC only covers up to page {last_start_page} of {total_pages} "
                f"({coverage:.0%}). Treating TOC as insufficient, falling back to heading detection."
            )
            return []

        return units

    def _resolve_with_gemini(self) -> list[StructureUnit]:
        candidates = []
        for page in self.doc_rep.pages:
            for hc in page.headings:
                candidates.append(f"Page {page.page_number} - Level {hc.level}: {hc.text}")

        # Bound the prompt size for pathologically large documents, but don't
        # silently drop most of a normal-sized document like a flat 200 cap did.
        max_candidates = 5000
        if len(candidates) > max_candidates:
            logger.warning(
                f"[STRUCTURE] {len(candidates)} heading candidates found, "
                f"truncating to first {max_candidates} to bound prompt size."
            )
        candidates_text = "\n".join(candidates[:max_candidates])
        prompt = STRUCTURE_RESOLVER_PROMPT + "\n\nCandidates:\n" + candidates_text

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config={
                    "response_mime_type": "application/json",
                    "response_schema": StructureResponse,
                }
            )

            data = json.loads(response.text)
            units = []
            for item in data.get("units", []):
                units.append(StructureUnit(**item))
            logger.info("[STRUCTURE] Structure resolved via Gemini")
            return units
        except Exception as e:
            logger.error(f"[STRUCTURE] Failed to resolve structure with Gemini: {e}")
            return []
