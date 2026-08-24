import fitz
import re
from app.services.rekonstruksi_kg.schemas import DocumentRepresentation, DocumentPage, Block, HeadingCandidate
from app.services.rekonstruksi_kg.helpers import clean_text

# Font size alone is an unreliable signal for BAB vs SUBBAB - many documents
# use the same font size (just bold) for both. These text patterns are common
# enough in Indonesian academic modules to override the font-size heuristic.
BAB_PATTERN = re.compile(r'^BAB\b', re.IGNORECASE)
LETTER_SUBHEADING_PATTERN = re.compile(r'^[A-Z]\s{0,3}\.\s+\S')


class PDFParser:
    def __init__(self, filepath: str):
        self.filepath = filepath
        self.doc = fitz.open(filepath)

    def extract_document(self) -> DocumentRepresentation:
        metadata = self.doc.metadata
        toc = self.doc.get_toc()

        pages = []
        for page_num in range(len(self.doc)):
            page = self.doc.load_page(page_num)
            text = clean_text(page.get_text("text"))
            dict_data = page.get_text("dict")

            blocks = []
            heading_candidates = []

            for block in dict_data.get("blocks", []):
                if "lines" in block:
                    block_text = ""
                    max_font_size = 0.0
                    is_bold = False

                    for line in block["lines"]:
                        for span in line["spans"]:
                            block_text += span["text"] + " "
                            if span["size"] > max_font_size:
                                max_font_size = span["size"]
                            if "bold" in span["font"].lower() or span["flags"] & 2 ** 4:
                                is_bold = True

                    block_text = clean_text(block_text)
                    if block_text:
                        blocks.append(Block(
                            text=block_text,
                            bbox=block["bbox"],
                            font_size=max_font_size,
                            flags=is_bold
                        ))

                        # Basic heuristic for heading candidates
                        stripped = block_text.strip()
                        is_bab_pattern = bool(BAB_PATTERN.match(stripped)) and len(stripped) < 100
                        is_letter_subheading = (
                            bool(LETTER_SUBHEADING_PATTERN.match(stripped))
                            and is_bold
                            and len(stripped) < 100
                        )

                        if is_bab_pattern:
                            heading_candidates.append(HeadingCandidate(
                                text=block_text, level=1, font_size=max_font_size, is_bold=is_bold
                            ))
                        elif is_letter_subheading:
                            heading_candidates.append(HeadingCandidate(
                                text=block_text, level=2, font_size=max_font_size, is_bold=is_bold
                            ))
                        elif max_font_size > 11.0 or (is_bold and len(block_text) < 100):
                            level = 1 if max_font_size > 14.0 else 2
                            heading_candidates.append(HeadingCandidate(
                                text=block_text,
                                level=level,
                                font_size=max_font_size,
                                is_bold=is_bold
                            ))

            pages.append(DocumentPage(
                page_number=page_num + 1,
                text=text,
                blocks=blocks,
                headings=heading_candidates
            ))

        return DocumentRepresentation(
            metadata=metadata,
            toc=toc,
            pages=pages
        )

    def close(self):
        self.doc.close()
