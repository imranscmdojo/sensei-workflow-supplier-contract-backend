import os
import json
from agents.base_rag_agent import BaseRAGAgent
from vertexai.generative_models import GenerationConfig, GenerativeModel


# ── Complete skill checklist ─────────────────────────────────────────────────
# The reviewer must iterate over every item in Clause Set A and ALL 21 items in
# Clause Set B for every contract. clause_id in the output schemas below is
# restricted (enum) to these canonical kebab-case slugs so the review always
# returns valid, referenceable clause identifiers (output-schema.md field notes).
CLAUSE_SET_A = [
    ("limitation-of-liability", "Limitation of Liability"),
    ("indemnification", "Indemnification"),
    ("ip-ownership", "IP Ownership"),
    ("data-protection", "Data Protection & Cybersecurity"),
    ("confidentiality", "Confidentiality"),
    ("reps-and-warranties", "Representations & Warranties"),
    ("term-and-termination", "Term & Termination"),
    ("governing-law", "Governing Law & Dispute Resolution"),
    ("insurance", "Insurance"),
    ("assignment", "Assignment"),
    ("force-majeure-general", "Force Majeure (general commercial)"),
    ("payment-terms", "Payment Terms"),
]

CLAUSE_SET_B = [
    ("moq-volume", "MOQ & Volume Commitments"),
    ("incoterms-title-transfer", "Incoterms & Title Transfer"),
    ("lead-time-delivery-sla", "Lead Time & Delivery SLA"),
    ("price-escalation", "Price Escalation / De-escalation"),
    ("quality-defect-liability", "Quality, Defect Liability & Acceptance"),
    ("force-majeure", "Supply Continuity & Force Majeure"),
    ("capacity-reservation", "Capacity Reservation & Allocation Rights"),
    ("tooling-ownership", "Tooling, Equipment & Mold Ownership"),
    ("sub-supplier-flow-down", "Sub-Supplier Rights & Flow-Down"),
    ("inventory-ownership-vmi", "Inventory Ownership (VMI / Consignment)"),
    ("packaging-labeling", "Packaging, Labeling & Anti-Counterfeiting"),
    ("traceability-documentation", "Traceability & Documentation"),
    ("sustainability-esg", "Sustainability & ESG"),
    ("audit-rights", "Audit Rights & Supplier Transparency"),
    ("exclusivity-non-compete", "Exclusivity & Non-Compete"),
    ("change-management-ecn", "Change Management (ECN)"),
    ("fx-risk-currency", "FX Risk & Currency Management"),
    ("customs-trade-compliance", "Customs, Trade Compliance & Tariffs"),
    ("supplier-scorecards-kpis", "Supplier Performance Scorecards & KPIs"),
    ("mfc-pricing", "Most Favored Customer (MFC) Pricing"),
    ("insolvency-financial-viability", "Insolvency & Financial Viability"),
]

CLAUSE_ID_SLUGS = [slug for slug, _ in CLAUSE_SET_A + CLAUSE_SET_B]


def _skill_checklist_block() -> str:
    """Render the full checklist (Set A + all 21 Set B items) into the prompt."""
    lines = ["Clause Set A (general commercial / legal):"]
    lines += [f"  - {slug} — {name}" for slug, name in CLAUSE_SET_A]
    lines += ["Clause Set B (supply chain / procurement):"]
    lines += [f"  - {slug} — {name}" for slug, name in CLAUSE_SET_B]
    return "\n".join(lines)


# ── Output schemas ────────────────────────────────────────────────────────────
# JSON schema handed to Gemini structured output. Strict mirror of
# output-schema.md: every object level disallows extra properties, redline is
# optional (omitted for GREEN clauses — see output-schema.md field notes), and
# clause_id is pinned to the canonical slug list (Pass 1 + Pass 2 rule).
# `redline` is optional so GREEN cards keep schema compliance while the prompt
# still demands a full redline for every YELLOW/RED clause.
REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "document_name": {"type": "string"},
        "parties": {"type": "string"},
        "contract_type": {"type": "string"},
        "user_side": {"type": "string", "enum": ["buyer", "supplier"]},
        "deadline": {"type": "string"},
        "review_basis": {
            "type": "string",
            "enum": ["client_playbook", "standard_positions"],
        },
        "review_basis_note": {"type": "string"},
        "overall_risk": {"type": "string", "enum": ["high", "medium", "low"]},
        "key_findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "severity": {"type": "string", "enum": ["red", "yellow", "green"]},
                    "clause_id": {
                        "type": "string",
                        "enum": CLAUSE_ID_SLUGS,
                        "description": "Canonical kebab-case clause slug from the complete skill checklist.",
                    },
                    "summary": {"type": "string"},
                },
                "required": ["severity", "clause_id", "summary"],
                "additionalProperties": False,
            },
        },
        "clauses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "clause_id": {
                        "type": "string",
                        "enum": CLAUSE_ID_SLUGS,
                        "description": "Canonical kebab-case clause slug from the complete skill checklist.",
                    },
                    "clause_name": {"type": "string"},
                    "severity": {"type": "string", "enum": ["red", "yellow", "green"]},
                    "contract_says": {"type": "string"},
                    "standard_position": {"type": "string"},
                    "business_impact": {"type": "string"},
                    "redline": {
                        "type": "object",
                        "properties": {
                            "current_language": {"type": "string"},
                            "proposed_language": {"type": "string"},
                            "rationale": {"type": "string"},
                            "priority": {
                                "type": "string",
                                "enum": ["must-have", "should-have", "nice-to-have"],
                            },
                            "fallback": {"type": "string"},
                        },
                        "required": [
                            "current_language",
                            "proposed_language",
                            "rationale",
                            "priority",
                            "fallback",
                        ],
                        "additionalProperties": False,
                    },
                },
                "required": [
                    "clause_id",
                    "clause_name",
                    "severity",
                    "contract_says",
                    "standard_position",
                    "business_impact",
                ],
                "additionalProperties": False,
            },
        },
        "negotiation_strategy": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "priority": {
                                "type": "string",
                                "enum": ["must-have", "should-have", "nice-to-have"],
                            },
                            "issue": {"type": "string"},
                            "goal": {"type": "string"},
                            "fallback": {"type": "string"},
                        },
                        "required": ["priority", "issue", "goal", "fallback"],
                        "additionalProperties": False,
                    },
                },
                "sequencing_note": {"type": "string"},
            },
            "required": ["items", "sequencing_note"],
            "additionalProperties": False,
        },
        "next_steps": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "document_name",
        "parties",
        "contract_type",
        "user_side",
        "deadline",
        "review_basis",
        "review_basis_note",
        "overall_risk",
        "key_findings",
        "clauses",
        "negotiation_strategy",
        "next_steps",
    ],
    "additionalProperties": False,
}


FOLLOWUP_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "revised_redlines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "clause_id": {
                        "type": "string",
                        "enum": CLAUSE_ID_SLUGS,
                        "description": "Must match a clause_id present in the completed review.",
                    },
                    "proposed_language": {"type": "string"},
                    "change_summary": {"type": "string"},
                },
                "required": ["clause_id", "proposed_language"],
            },
        },
    },
    "required": ["answer"],
}


class SupplierContractReviewAgent(BaseRAGAgent):
    """Review a supplier/vendor contract against supply chain standard positions."""

    def __init__(self):
        super().__init__(model_name="gemini-2.5-pro")

        prompt_path = os.path.join(os.path.dirname(__file__), "system-prompt.md")
        with open(prompt_path, "r") as f:
            self.system_instruction = f.read()

    async def generate_review(
        self,
        contract_text: str,
        contract_type: str = "Supply Agreement",
        user_side: str = "buyer",
        focus_areas: str = "",
        constraints: str = "",
        must_not_lose: str = "",
        client_id: str = "",
        client_name: str = "",
        deadline: str = "",
        deal_context: str = "",
    ) -> dict:
        """Run the full clause-by-clause review and return output-schema JSON.

        RAG retrieval is enabled during generation: the model pulls client
        playbook context from the configured corpus through the retrieval tool.
        When retrieval returns a relevant playbook position it is applied and
        review_basis is "client_playbook"; otherwise the review falls back to
        the supply chain standard positions embedded in the system prompt
        (review_basis "standard_positions", stated in review_basis_note).
        """
        checklist = _skill_checklist_block()
        prompt = f"""Review the supplier contract below and return the structured review JSON.

## What you must output
Return ONLY a single JSON object that conforms exactly to the review schema you
were given (response_schema). No markdown fences, no prose around it, no
duplicated document text — just the JSON object.

## Review context
- Contract type: {contract_type}
- User side: {user_side}
- Deadline: {deadline or "not provided"}
- Client id: {client_id or "none supplied"}
- Client name: {client_name or "not provided"}
- Deal context: {deal_context or "not provided"}

## What matters most to the user
{focus_areas or "not specified"}

## Constraints
{constraints or "none stated"}

## Must not lose
{must_not_lose or "nothing specific stated"}

## Review basis
Retrieval (RAG) is enabled: you have a retrieval tool connected to the client's
playbook corpus, so pull relevant standard positions from it while you review.
- If the retrieved context yields a relevant client playbook position for a
  clause, apply it and set review_basis to "client_playbook", summarizing what
  was retrieved in review_basis_note.
- If retrieval returns nothing relevant for this client, fall back to the
  supply chain standard positions in your instructions, set review_basis to
  "standard_positions", and say so in review_basis_note.
- Never fabricate a client-specific position that retrieval does not return.

## Contract text
\"\"\"
{contract_text}
\"\"\"

## Review procedure — two passes

### Pass 1 — Sections present in the source text (review these FIRST)
Read the contract and enumerate every section, heading or titled article that
actually appears in it (e.g. numbered sections such as "Cargo/Defect Liability
(Sec 4.1.M)", "Independent Contractors", "BioPointe Tracking Software",
"Driver Vetting"). Emit one `clauses` entry for EACH of those sections — a
dedicated review card that is never skipped, merged or collapsed — before
considering any general clause above them.

For each present section's card:
- clause_name: the section's title as it appears in the source, plus its
  location, e.g. "Cargo/Defect Liability (Sec 4.1.M)".
- clause_id: the best-matching canonical slug from the checklist below. If the
  section is operational (driver vetting/screening, tracking software,
  root-cause analysis / RCA protocols, etc.), map it to the closest
  supply-chain slug — driver vetting → audit-rights or quality-defect-liability;
  tracking/tracing systems such as BioPointe → traceability-documentation;
  RCA / defect investigation and liability → quality-defect-liability;
  performance / SLA measures → supplier-scorecards-kpis.
- contract_says: quote the section's operative language exactly as it appears
  in the contract. Do not paraphrase away the detail; surface every distinct
  obligation the section creates (vetting standards, software requirements,
  investigation / RCA timelines, loss limits).
- Severity: classify GREEN / YELLOW / RED per the tier anchors. Positive or
  favorable obligations that align with the user's side are GREEN — still quote
  the actual language so they are reflected, never dropped.

### Pass 2 — Checklist items still missing from Pass 1
After the Pass 1 section cards, go through the COMPLETE checklist below and emit
an entry for every item NOT already covered by a Pass 1 card. If an item is not
addressed in the contract at all, still emit it with contract_says set to
"Not addressed in this contract" and classify it per the tier anchors — a
missing clause is itself a finding (often YELLOW or RED).

### Uniqueness rule
Use each canonical clause_id at most once across the whole `clauses` array. If
several present sections map to the same slug, give the first its exact slug and
map the others to their closest still-unused slug, so every card stays distinct.

Complete skill checklist — canonical clause_id values:
{checklist}

## Severity rules (apply on top of the checklist tier anchors)
- RED if the supplier can reject purchase orders that fall within a binding
  forecast band (moq-volume) or a binding delivery SLA / lead-time band
  (lead-time-delivery-sla): a "binding" commitment is one-sided unless the
  supplier is equally bound to fulfill orders placed within it.
- YELLOW/RED if the buyer bears destination-market compliance liability while
  the supplier is the manufacturer or Importer of Record
  (quality-defect-liability / reps-and-warranties): when the supplier makes the
  goods or clears them as Importer of Record, it must own regulatory, customs
  and destination-market compliance exposure — flag YELLOW when partially
  mitigated, RED when the buyer bears it with no indemnity or recourse.

## Negotiation strategy (negotiation_strategy.items)
Build the negotiation battle plan as a flat list of rows, one per issue, covering
every RED and YELLOW item first and a few strategic GREEN holds. Aim for 8-10
rows. For each row:
- `priority`: "must-have" | "should-have" | "nice-to-have" — use must-have for
  RED must-win items, should-have for important improvements, nice-to-have for
  tradeable asks.
- `issue`: the clause or section being negotiated, with its section location as
  it appears in the source text where available, e.g. "Cargo liability (Section
  9.C)" or "Indemnification (Section 7)".
- `goal`: the concrete negotiation objective, e.g. "Mutual, proportional",
  "Increase to 80%+ of value", "Reduce to Net 15".
- `fallback`: the concession you can accept instead, e.g. "Cap at insurance
  limits only", "Index to inflation". A specific, defensible compromise — not a
  vague "negotiate".
Order rows MUST (highest severity first), then SHOULD, then NICE.

## Rate & cost structure evaluation
When assessing rate, pricing or payment clauses (and any benchmark in
contract_says / business_impact / standard_position), never evaluate base
per-mile or per-unit fees in isolation, and never compare them against generic
freight or standard courier averages. Assess pricing strictly against the
contract's specific industry niche — factoring in specialized handling,
regulatory requirements, and high-risk material classifications — and compare
against that specific market segment. Before providing any cost analysis or
benchmark, calculate true effective costs across varying route distances by
incorporating all applicable minimum route fee floors, stackable surcharges
(such as fuel and wait time), and conditional service charges found in the
contract.

Date audit:
Verify the header date, effective date, term/commencement dates, signature
blocks, and expiry/termination dates are present and consistent with each
other. If they align, reflect that under `term-and-termination` as GREEN. If
they are missing or inconsistent, flag it as a finding there — quote what is
present and say what is missing. Never assume or invent dates.

Keep key_findings to the 3-5 highest-severity items, highest first. Provide a
full redline for every YELLOW or RED clause. Remember: this is a risk review,
not legal advice."""

        return await self.generate_with_rag(
            prompt=prompt,
            system_instruction=self.system_instruction,
            response_schema=REVIEW_SCHEMA,
            use_rag=True,
        )

    async def follow_up(self, review: dict, question: str) -> dict:
        """Answer a follow-up question about a completed review.

        Clause-specific facts are grounded in the review JSON in context. When
        the question is not covered by the review (market benchmarks, typical
        rates, out-of-the-box questions), the agent still answers using general
        market knowledge, clearly labeled as an estimate. When the user asks to
        soften, strengthen or reword a redline, it returns the revised language
        keyed by clause_id in `revised_redlines` so the UI can offer to apply
        it; otherwise that array is empty.
        """
        prompt = f"""Answer a follow-up question about a completed supplier contract review.

You are continuing a conversation with the same user who requested this review.

## The completed review JSON (your ONLY source of truth)
```json
{json.dumps(review, indent=2)}
```

## User side
{review.get("user_side", "buyer")}

## The user's question
{question}

Answer the question and follow these rules:
- Clause-specific facts must be grounded in the review JSON above. Never
  attribute contract language or figures to the review that are not present in
  it.
- For rate/cost questions, never assess base per-mile (or per-unit) fees in
  isolation and never compare them against generic freight or standard courier
  averages. Assess pricing strictly against the contract's specific industry
  niche (specialized handling, regulatory requirements, high-risk material
  classifications) and that market segment, building the comparison on TRUE
  effective costs across varying route distances — incorporating minimum route
  fee floors, stackable surcharges (fuel, wait time) and conditional service
  charges from the review data, and stating any input you had to assume as an
  estimate.
- If the question is NOT covered by the review — market benchmarks, typical
  rates, industry norms, or any out-of-the-box question — STILL answer. Use
  general market knowledge and clearly label that material as a general market
  estimate/benchmark (not from this review), give a range, and note it varies by
  market and region. Never leave the question unanswered.
- Never mention internal system mechanics, data schemas, or JSON files in your
  answer. If the review data lacks a market benchmark, state your estimate
  seamlessly from general industry knowledge — e.g. "Based on industry
  benchmarks for Class 7 radioactive medical transport..." — never "The review
  JSON does not provide...".
- If the question references a clause, tier or redline that is not in the
  review, acknowledge it in plain business terms (still without technical
  internals) and then answer with general guidance.
- If the user asks to soften, strengthen, reword or otherwise change a redline,
  return the revised proposed language in `revised_redlines` with the matching
  `clause_id`, keep it consistent with that clause's standard_position and the
  review's overall negotiation strategy, and keep `change_summary` to one line.
  For any other kind of question return an empty `revised_redlines` array.
- Own the revised tone in the answer (mirror the example: what changed, what
  stayed the same) and keep it to 2-5 sentences unless the user asks for detail.
- Use ** bold ** ONLY for headings, subheadings and the title of each item
  (e.g. "**Cargo Liability (Section 9):** ..."); keep the body of every point
  plain. Never bold words or phrases inside the body text; never use _, * or
  markdown headers.
- This is a risk review continuation, not legal advice."""

        model = GenerativeModel(
            model_name="gemini-2.5-flash",
            system_instruction=self.system_instruction,
        )
        gen_config = GenerationConfig(response_mime_type="application/json", response_schema=FOLLOWUP_SCHEMA)
        response = await model.generate_content_async(prompt, generation_config=gen_config)
        return json.loads(response.text)

    async def follow_up_stream(self, review: dict, question: str):
        """Stream a follow-up answer token-by-token.

        Unlike `follow_up`, this uses plain-text generation so chunks can be
        streamed to the UI as they arrive. If the user asks to change a
        redline, the model appends a trailing `<<<REDLINE_START>>>{...}
        <<<REDLINE_END>>>` block which main.py extracts and hands to the UI as
        an "apply" proposal.

        Uses gemini-2.5-flash: fast first token and small, frequent chunks so
        the UI visibly streams. Each streamed chunk may carry reasoning parts
        alongside text parts, so text is read part-by-part (never via the
        high-level `.text` accessor, which fails on multi-part chunks).
        """
        model = GenerativeModel(
            model_name="gemini-2.5-flash",
            system_instruction=(
                "You are sensei.'s supplier contract review assistant. You answer "
                "follow-up questions about a completed contract review. Ground "
                "clause-specific facts in the review JSON provided in the prompt. "
                "For rate/cost questions, never assess base per-mile (or per-unit) "
                "fees in isolation or compare against generic freight/courier "
                "averages — assess against the contract's specific industry niche "
                "(specialized handling, regulatory requirements, high-risk material "
                "classifications) and compute true effective costs across route "
                "distances using minimum fee floors, stackable surcharges (fuel, "
                "wait time) and conditional charges from the review, labeling any "
                "assumed input as an estimate. When a question is not covered by the "
                "review, still answer using general market knowledge, clearly "
                "labeled as an estimate/benchmark, never as contract fact. Never "
                "mention the underlying JSON, schemas, or internal mechanics in "
                "your output; when the available data lacks a benchmark, state "
                "your estimate smoothly from general industry knowledge (e.g. "
                "'Based on industry benchmarks for Class 7 radioactive medical "
                "transport...') without referencing technical constraints. Format "
                "with ** bold ** ONLY for headings, subheadings and item titles "
                "(e.g. '**Cargo Liability (Section 9):** ...'); keep the body of "
                "every point plain. Never bold words inside body text and never "
                "use _, * or markdown headers. Propose "
                "revised redline language when asked using the prescribed trailing "
                "block. This is a risk review continuation, not legal advice."
            ),
        )
        gen_config = GenerationConfig(max_output_tokens=4096, temperature=0.3)

        prompt = f"""Answer a follow-up question about a completed supplier contract review.

You are continuing a conversation with the same user who requested this review.

## The completed review JSON (your ONLY source of truth)
```json
{json.dumps(review, indent=2)}
```

## User side
{review.get("user_side", "buyer")}

## The user's question
{question}

Answer the question. Rules:
- Clause-specific facts must be grounded in the review JSON above. Never present
  language or figures as coming from the review unless they are in it.
- If the question is NOT covered by the review — market benchmarks, typical
  rates, industry norms, or any out-of-the-box question — STILL answer. Use
  general market knowledge, clearly label that material as a general market
  estimate/benchmark (not from this review), give a range, and note it varies by
  market and region. Do not leave the question unanswered.
- Never mention internal system mechanics, data schemas, or JSON files in your
  answer. If the available data lacks a market benchmark, state your estimate
  seamlessly from general industry knowledge — e.g. "Based on industry
  benchmarks for Class 7 radioactive medical transport..." — never "The review
  JSON does not provide...".
- If the question references a clause, tier or redline not in the review,
  acknowledge it in plain business terms (still without technical internals)
  and then answer with general guidance.
- Answer as plain text, 2-5 sentences unless the user asks for detail.
- Use ** bold ** ONLY for headings, subheadings and the title of each item so
  the answer reads like a polished email — e.g. "**Cargo Liability (Section
  9):** The current liability limit..." — then keep the body of every point
  plain. Never bold words or phrases inside the body text; never use _, * or
  markdown headers.
- If the user asks to soften, strengthen, reword or otherwise change a redline,
  finish your answer by adding EXACTLY this block as the very last thing in the
  response, with a valid single JSON object on one line, and nothing after it:

<<<REDLINE_START>>>
{{"clause_id": "<id of the clause>", "proposed_language": "<revised proposed language>", "change_summary": "<one-line summary of what changed and what stayed the same>"}}
<<<REDLINE_END>>>

  Keep the revised language consistent with that clause's standard_position in
  the review. For any other kind of question, do not emit the block.
- This is a risk review continuation, not legal advice."""

        stream = await model.generate_content_async(
            prompt,
            generation_config=gen_config,
            stream=True,
        )
        async for chunk in stream:
            for candidate in getattr(chunk, "candidates", None) or []:
                content = getattr(candidate, "content", None)
                if content is None:
                    continue
                for part in content.parts:
                    try:
                        piece = part.text
                    except Exception:  # noqa: BLE001 - reasoning/other non-text part
                        continue
                    if piece:
                        yield piece
