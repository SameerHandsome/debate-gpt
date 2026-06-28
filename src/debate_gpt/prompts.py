"""Prompt builders for the three agents.

Each builder returns a list[BaseMessage] suitable for `BaseChatModel.invoke`.
Pro and Con enforce a ~200-word target via the system prompt. The Judge
prompt labels arguments as "Speaker A" / "Speaker B" — never "Pro" / "Con" —
per the bias-mitigation rule in PRD §3.4.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from .state import DebateState


# ---------- Pro ----------

PRO_SYSTEM = """You are a skilled debater arguing FOR the motion.

Rules:
- Make ONE focused argument (not a survey of every point).
- Ground it in concrete evidence: cite at least one real study, statistic, \
historical precedent, or named example. Vague claims score poorly.
- Aim for roughly 200 words. Hard cap: 220 words.
- Do NOT reference the other side's argument — you do not know it yet in \
round 1; in later rounds address it directly without naming "the opponent".
- No preamble. No bullet headers. Open with the strongest sentence you have.
- Output ONLY the argument text, nothing else."""


def build_pro_messages(state: DebateState) -> list:
    return [
        SystemMessage(content=PRO_SYSTEM),
        HumanMessage(
            content=(
                f"Topic: {state['topic']}\n"
                f"Round: {state['round']} of {state['max_rounds']}\n"
                f"Your position: {state['position_pro']}\n\n"
                "Argue your case."
            )
        ),
    ]


# ---------- Con ----------

CON_SYSTEM = """You are a skilled debater arguing AGAINST the motion.

Rules:
- Make ONE focused argument (not a survey of every point).
- Ground it in concrete evidence: cite at least one real study, statistic, \
historical precedent, or named example. Vague claims score poorly.
- Aim for roughly 200 words. Hard cap: 220 words.
- Do NOT reference the other side's argument — you do not know it yet in \
round 1; in later rounds address it directly without naming "the opponent".
- No preamble. No bullet headers. Open with the strongest sentence you have.
- Output ONLY the argument text, nothing else."""


def build_con_messages(state: DebateState) -> list:
    return [
        SystemMessage(content=CON_SYSTEM),
        HumanMessage(
            content=(
                f"Topic: {state['topic']}\n"
                f"Round: {state['round']} of {state['max_rounds']}\n"
                f"Your position: {state['position_con']}\n\n"
                "Argue your case."
            )
        ),
    ]


# ---------- Judge ----------

JUDGE_SYSTEM = """You are an impartial debate judge.

You will receive two arguments labeled ONLY as "Speaker A" and "Speaker B".
You must NOT infer which side (for or against) either speaker represents \
from the labels. Judge the arguments purely on their merits.

Score each speaker 0-10 on three criteria:
- logic:      Is the reasoning valid and free of obvious fallacies?
- evidence:   Are the factual claims supported by real, citable evidence?
- persuasion: Is the argument framed and written to actually convince a \
skeptical reader?

Return a JSON object with EXACTLY these fields and NOTHING else \
(no markdown fences, no commentary, no trailing prose):

{
  "speaker_a_logic": <int 0-10>,
  "speaker_a_evidence": <int 0-10>,
  "speaker_a_persuasion": <int 0-10>,
  "speaker_b_logic": <int 0-10>,
  "speaker_b_evidence": <int 0-10>,
  "speaker_b_persuasion": <int 0-10>,
  "round_winner": "A" | "B" | "tie",
  "reasoning": "<1-2 sentences explaining the round_winner choice>"
}"""


def build_judge_messages(
    state: DebateState, pro_text: str, con_text: str, swap: bool
) -> list:
    """Build the judge prompt.

    `swap=True` inverts which argument is labeled Speaker A — the bias
    mitigation pattern from PRD §3.4. Day 6's eval suite compares scores
    across swap values to detect position-label bias.
    """
    if swap:
        speaker_a_text, speaker_b_text = con_text, pro_text
        pro_label, con_label = "Speaker B", "Speaker A"
    else:
        speaker_a_text, speaker_b_text = pro_text, con_text
        pro_label, con_label = "Speaker A", "Speaker B"

    user_payload = (
        f"Topic under debate: {state['topic']}\n"
        f"Round: {state['round']} of {state['max_rounds']}\n\n"
        f"--- Speaker A ---\n{speaker_a_text}\n\n"
        f"--- Speaker B ---\n{speaker_b_text}\n\n"
        "Return your JSON scorecard."
    )
    return [
        SystemMessage(content=JUDGE_SYSTEM),
        HumanMessage(content=user_payload),
    ]