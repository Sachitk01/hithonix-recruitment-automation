import io
from docx import Document

def extract_docx_text(file_bytes: bytes) -> str:
    """
    Extracts plain text from a DOCX file byte buffer.
    """
    try:
        doc = Document(io.BytesIO(file_bytes))
        paragraphs = [p.text for p in doc.paragraphs]
        text = "\n".join(paragraphs).strip()
        return text

    except Exception as e:
        print(f"DOCX extraction error: {e}")
        return ""
