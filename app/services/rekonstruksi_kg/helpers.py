import re
import uuid


def clean_text(text: str) -> str:
    """Bersihkan teks dari baris baru berulang dan spasi berlebih."""
    text = re.sub(r"\n+", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def generate_unit_id(prefix: str = "unit") -> str:
    """Buat id unik untuk sebuah unit struktur."""
    unique_id = uuid.uuid4().hex[:8]
    return f"{prefix}_{unique_id}"
