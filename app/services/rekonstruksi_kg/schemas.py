"""Skema data untuk engine rekonstruksi-KG (parsing PDF -> struktur -> ekstraksi konsep).

Diadaptasi dari proyek standalone `rekonstruksi-kg/app/schemas/{document,extraction}.py`.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# --- Representasi dokumen (dari pdf_parser.py) ---

class Block(BaseModel):
    text: str
    bbox: tuple[float, float, float, float]
    font_size: float
    flags: int


class HeadingCandidate(BaseModel):
    text: str
    level: int
    font_size: float
    is_bold: bool


class DocumentPage(BaseModel):
    page_number: int
    text: str
    blocks: list[Block]
    headings: list[HeadingCandidate]


class DocumentRepresentation(BaseModel):
    metadata: dict[str, Any]
    toc: list[tuple[int, str, int]]  # level, title, page
    pages: list[DocumentPage]


# --- Struktur dokumen (dari structure.py) ---

class StructureUnit(BaseModel):
    id: str
    level: Literal["BAB", "SUBBAB"]
    title: str
    parent_id: Optional[str]
    start_page: int
    end_page: int
    summary: str
    has_children: bool


class RawStructureUnit(BaseModel):
    id: str
    level: str
    title: str
    parent_id: Optional[str]
    start_page: int
    end_page: int
    summary: str
    has_children: bool


class StructureResponse(BaseModel):
    units: list[RawStructureUnit]


# --- Ekstraksi konsep (dari extraction.py) ---

class ExtractionUnit(BaseModel):
    unit_id: str
    level: str
    title: str
    parent_id: Optional[str]
    summary: str
    start_page: int
    end_page: int
    raw_text: str


class Concept(BaseModel):
    nama: str
    deskripsi: str


class ExtractionResult(BaseModel):
    unit_id: str
    konsep: list[Concept] = Field(default_factory=list)


class ConsolidatedConcept(BaseModel):
    unit_id: str
    nama: str
    deskripsi: str


class ConsolidationResult(BaseModel):
    konsep: list[ConsolidatedConcept] = Field(default_factory=list)


class ExtractionError(BaseModel):
    unit_id: str
    stage: str
    error: str
