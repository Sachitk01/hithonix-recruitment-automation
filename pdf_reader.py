import io

# TODO: Migrate from PyPDF2 to pypdf to resolve deprecation warnings when convenient.
import PyPDF2  # type: ignore[import-not-found]

def extract_pdf_text(file_bytes: bytes) -> str:
    """
    Returns cleaned text from a PDF byte stream.
    """
    try:
        pdf_reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
        text = ""

        for page in pdf_reader.pages:
            extracted = page.extract_text() or ""
            text += extracted + "\n"

        # Clean formatting
        text = text.replace("\t", " ").strip()
        return text

    except Exception as e:
        print(f"PDF extraction error: {e}")
        return ""
