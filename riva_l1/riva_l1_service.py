# riva_l1_service.py

import os, json
from typing import Optional
from openai import OpenAI
from .riva_l1_prompt import RIVA_L1_PROMPT
from .riva_l1_models import RivaL1Result


class RivaL1Service:

    def __init__(self):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    def evaluate(
        self,
        resume_text: str,
        jd_text: str,
        transcript_text: str,
        feedback_text: str = "",
        memory_context: Optional[str] = None,
    ) -> RivaL1Result:
        prompt = (
            f"{RIVA_L1_PROMPT}\n\n"
            "### JOB DESCRIPTION\n"
            f"{jd_text}\n\n"
            "### RESUME\n"
            f"{resume_text}\n\n"
            "### L1 INTERVIEW TRANSCRIPT\n"
            f"{transcript_text}\n\n"
            "### HUMAN L1 FEEDBACK\n"
            f"{feedback_text}\n"
        )

        if memory_context:
            prompt += "\n### TALENT MEMORY CONTEXT\n"
            prompt += f"{memory_context}\n"

        response = self.client.chat.completions.create(
            model="gpt-5.1",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1
        )

        raw = response.choices[0].message.content.strip()

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            raise ValueError(f"Invalid JSON from GPT: {raw}")

        return RivaL1Result(**data)
