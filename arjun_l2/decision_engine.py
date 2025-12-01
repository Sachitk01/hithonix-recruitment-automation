
from typing import Dict, Any, List, Optional

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
    
    normalized_risk_flags = []
    reason_codes = []
    
    def has_keyword(text: str, keywords: List[str]) -> bool:
        text_lower = text.lower()
        return any(k in text_lower for k in keywords)

    all_notes = risk_flags + concerns
    for note in all_notes:
        if has_keyword(note, ["hard block", "integrity", "ethics", "cheating", "fake"]):
            normalized_risk_flags.append("hard_block")
        if has_keyword(note, ["data incomplete", "missing info", "missing transcript"]):
            reason_codes.append("data_incomplete")
            
    # Raw Recommendation
    raw_rec = evaluation.get("final_recommendation", "").lower()
    
    # --- 2. Apply Strict Decision Logic ---
    
    # 1. Data Incomplete
    if "data_incomplete" in reason_codes:
        return "HOLD_DATA_INCOMPLETE"
        
    # 2. Hard Blocks
    if "hard_block" in normalized_risk_flags:
        return "REJECT_AT_L2"
        
    # 3. Strict Advance
    # If leadership score is present, it must be >= 0.75
    leadership_pass = True
    if leadership_readiness_score is not None:
        leadership_pass = leadership_readiness_score >= 0.75
        
    if (overall_score >= 0.8 and 
        role_fit_score >= 0.8 and 
        communication_score >= 0.7 and 
        leadership_pass and
        raw_rec in ["hire", "strong_yes", "yes"]):
        return "ADVANCE_TO_FINAL"
        
    # 4. Aggressive Reject
    if (overall_score <= 0.5 or 
        role_fit_score <= 0.5 or 
        communication_score <= 0.5 or
        raw_rec in ["reject", "no", "strong_no"]):
        return "REJECT_AT_L2"
        
    # 5. Tiny Exec Hold Band
    # Mid-band: 0.65 - 0.8
    if (0.65 <= overall_score < 0.8 and 
        communication_score >= 0.6):
        return "HOLD_EXEC_REVIEW"
        
    # Default to Reject if not clearly in Hold band
    return "REJECT_AT_L2"
