
from typing import List, Dict, Any, Optional

def decide_l1_outcome(evaluation: Dict[str, Any]) -> str:
    """
    Decides the L1 outcome based on the evaluation result.
    
    This function accepts the raw RivaL1Result dictionary (or similar) and maps it 
    to the normalized decision inputs internally.
    
    Policy:
    - If risk_flags or reason_codes contain "data_incomplete" or "missing_non_critical_info", return "HOLD_DATA_INCOMPLETE".
    - If risk_flags contain any hard block (e.g. "hard_block", "mandatory_criteria_failed"), return "REJECT_AT_L1".
    - If overall_score >= 0.7 AND jd_alignment_score >= 0.7, return "MOVE_TO_L2" even if communication_score is borderline.
    - If overall_score <= 0.4 OR jd_alignment_score <= 0.4, return "REJECT_AT_L1".
    - Otherwise, return "HOLD_MANUAL_REVIEW".
    """
    
    # --- 1. Normalize Inputs ---
    
    # Extract scores
    # fit_score is 0-100. Normalize to 0.0-1.0
    fit_score = evaluation.get("fit_score", 0)
    overall_score = float(fit_score) / 100.0
    
    # JD Alignment: We don't have a separate score in the old payload, so we use fit_score as a proxy
    # unless we find specific signals in strengths/concerns.
    # For now, proxying with overall_score is the safest baseline.
    jd_alignment_score = overall_score
    
    # Extract flags
    red_flags = evaluation.get("red_flags", []) or []
    concerns = evaluation.get("concerns", []) or []
    
    # Combine into risk_flags
    # We also check for specific keywords in concerns to promote them to risk flags if needed
    risk_flags = list(red_flags)
    reason_codes = []
    
    # Helper to check keywords
    def has_keyword(text: str, keywords: List[str]) -> bool:
        text_lower = text.lower()
        return any(k in text_lower for k in keywords)

    # Scan concerns/flags for specific signals to populate risk_flags/reason_codes
    all_notes = red_flags + concerns
    for note in all_notes:
        if has_keyword(note, ["hard block", "mandatory", "not eligible", "ineligible"]):
            risk_flags.append("hard_block")
        if has_keyword(note, ["missing transcript", "no transcript"]):
            reason_codes.append("missing_non_critical_info") # Or data_incomplete depending on severity
        if has_keyword(note, ["data incomplete", "missing resume", "missing jd"]):
            reason_codes.append("data_incomplete")

    # Normalize to lower case for comparison
    risk_flags_lower = [f.lower() for f in risk_flags]
    reason_codes_lower = [c.lower() for c in reason_codes]
    
    combined_flags = set(risk_flags_lower + reason_codes_lower)
    
    # --- 2. Apply Decision Logic ---
    
    # 1. Data Incomplete Checks
    if "data_incomplete" in combined_flags or "missing_non_critical_info" in combined_flags:
        return "HOLD_DATA_INCOMPLETE"
        
    # 2. Hard Block Checks
    hard_block_keywords = {"hard_block", "mandatory_criteria_failed"}
    if any(k in combined_flags for k in hard_block_keywords):
        return "REJECT_AT_L1"
        
    # 3. Move to L2
    if overall_score >= 0.7 and jd_alignment_score >= 0.7:
        return "MOVE_TO_L2"
        
    # 4. Reject at L1
    if overall_score <= 0.4 or jd_alignment_score <= 0.4:
        return "REJECT_AT_L1"
        
    # 5. Default Hold
    return "HOLD_MANUAL_REVIEW"
