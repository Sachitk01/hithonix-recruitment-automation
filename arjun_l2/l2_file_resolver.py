# arjun_l2/l2_file_resolver.py

from typing import Any, Dict, Optional, Sequence


def find_l2_transcript_file(files: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Return the first file that looks like an L2 transcript.
    
    A valid L2 transcript is ANY file whose name (case-insensitive):
    - contains 'l2' and 'transcript' anywhere, in any order
    - allows underscores / dashes / spaces (e.g. 'L2_Transcript.txt', 'L2 Transcript.docx')
    - supports extensions .txt, .docx, .pdf, .md
    
    Args:
        files: Sequence of file dictionaries with at least a 'name' key
        
    Returns:
        The matched file dict or None if no L2 transcript found
    """
    preferred_ext_order = [".txt", ".docx", ".pdf", ".md"]
    
    candidates: list[Dict[str, Any]] = []
    for f in files:
        name = f.get("name", "").lower()
        if "l2" in name and "transcript" in name:
            candidates.append(f)
    
    if not candidates:
        return None
    
    # Prefer by extension, fall back to first candidate
    for ext in preferred_ext_order:
        for f in candidates:
            if f.get("name", "").lower().endswith(ext):
                return f
    
    return candidates[0]
