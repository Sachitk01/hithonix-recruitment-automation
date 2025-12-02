from typing import Any, Dict, List

from arjun_l2.decision_policy import (
    ADVANCE_MIN_COMMUNICATION,
    ADVANCE_MIN_LEADERSHIP,
    ADVANCE_MIN_SCORE,
    DATA_INCOMPLETE_RISK_CODES,
    EXEC_HOLD_MAX_SCORE,
    EXEC_HOLD_MIN_COMMUNICATION,
    EXEC_HOLD_MIN_SCORE,
    HARD_BLOCK_FLAGS,
    REJECT_MAX_COMMUNICATION,
    REJECT_MAX_SCORE,
)

def decide_l2_outcome(evaluation: Dict[str, Any]) -> str:
    """
    Decides the L2 outcome based on the evaluation result with STRICT rules.
    
    Policy:
    - ADVANCE_TO_FINAL: Strong scores across the board.
    - REJECT_AT_L2: Weak scores or hard blocks.
    - HOLD_EXEC_REVIEW: Narrow mid-band with ambiguous signals.
    - HOLD_DATA_INCOMPLETE: Missing critical info.
    """
    
    # --- 1. Normalize Inputs ---
    
    # Extract base score
    final_score = evaluation.get("final_score", 0)
    overall_score = float(final_score) / 100.0
    
    # Proxies and Heuristics
    role_fit_score = overall_score # Proxy
    
    # Communication Score Heuristic
    comm_depth = evaluation.get("communication_depth", "").lower()
    communication_score = overall_score # Default fallback
    if any(k in comm_depth for k in ["excellent", "strong", "exceptional", "very good", "high"]):
        communication_score = max(overall_score, 0.9)
    elif any(k in comm_depth for k in ["good", "clear", "effective"]):
        communication_score = max(overall_score, 0.7)
    elif any(k in comm_depth for k in ["poor", "weak", "unclear", "limited"]):
        communication_score = min(overall_score, 0.4)
        
    # Leadership Score Heuristic
    leadership_text = evaluation.get("leadership_assessment", "").lower()
    leadership_readiness_score = None
    if leadership_text and leadership_text != "n/a":
        if any(k in leadership_text for k in ["high", "strong", "excellent", "proven"]):
            leadership_readiness_score = 0.9
        elif any(k in leadership_text for k in ["medium", "moderate", "developing"]):
            leadership_readiness_score = 0.7
        elif any(k in leadership_text for k in ["low", "weak", "none"]):
            leadership_readiness_score = 0.4
            
    # Risk Flags & Reason Codes
    risk_flags = evaluation.get("risk_flags", []) or []
    concerns = evaluation.get("concerns", []) or []
    
    derived_risk_flags: List[str] = []
    derived_reason_codes: List[str] = []
    
    def has_keyword(text: str, keywords: List[str]) -> bool:
        text_lower = text.lower()
        return any(k in text_lower for k in keywords)

    all_notes = (risk_flags or []) + concerns
    for note in all_notes:
        if has_keyword(note, ["hard block", "integrity", "ethics", "cheating", "fake", "mandatory"]):
            derived_risk_flags.append("hard_block")
        if has_keyword(note, ["missing transcript", "no transcript"]):
            derived_reason_codes.append("missing_l2_transcript")
        if has_keyword(note, ["data incomplete", "missing info", "missing_noncritical"]):
            derived_reason_codes.append("data_incomplete")
            
    combined_risk_flags = [flag.lower() for flag in (risk_flags + derived_risk_flags)]
    combined_reason_codes = [code.lower() for code in (derived_reason_codes + risk_flags)]

    # Raw Recommendation
    raw_rec = evaluation.get("final_recommendation", "").lower()
    
    # --- 2. Apply Strict Decision Logic ---
    
    # 1. Data Incomplete
    if any(code in DATA_INCOMPLETE_RISK_CODES for code in combined_reason_codes):
        return "HOLD_DATA_INCOMPLETE"
        
    # 2. Hard Blocks
    if any(flag in HARD_BLOCK_FLAGS for flag in combined_risk_flags):
        return "REJECT_AT_L2"
        
    # 3. Honor explicit model holds
    if raw_rec == "hold":
        return "HOLD_EXEC_REVIEW"

    # 4. Strict Advance
    # If leadership score is present, it must be >= 0.75
    leadership_pass = True
    if leadership_readiness_score is not None:
        leadership_pass = leadership_readiness_score >= ADVANCE_MIN_LEADERSHIP

    if (
        overall_score >= ADVANCE_MIN_SCORE
        and role_fit_score >= ADVANCE_MIN_SCORE
        and communication_score >= ADVANCE_MIN_COMMUNICATION
        and leadership_pass
        and raw_rec in ["hire", "strong_yes", "yes"]
    ):
        return "ADVANCE_TO_FINAL"
        
    # 5. Aggressive Reject
    if (
        overall_score <= REJECT_MAX_SCORE
        or role_fit_score <= REJECT_MAX_SCORE
        or communication_score <= REJECT_MAX_COMMUNICATION
        or raw_rec in ["reject", "no", "strong_no"]
    ):
        return "REJECT_AT_L2"
        
    # 6. Tiny Exec Hold Band
    # Mid-band: 0.65 - 0.8
    if (
        EXEC_HOLD_MIN_SCORE <= overall_score < EXEC_HOLD_MAX_SCORE
        and communication_score >= EXEC_HOLD_MIN_COMMUNICATION
    ):
        return "HOLD_EXEC_REVIEW"
        
    # Default to Reject if not clearly in Hold band
    return "REJECT_AT_L2"
