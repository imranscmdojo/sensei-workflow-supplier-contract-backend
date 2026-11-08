"""
Base RAG Agent for all AI agents in the Supplier Contract Review workflow.

Follows SENSEI pattern:
- Vertex AI RAG integration (available but unused in v1 — the Skill is embedded)
- Structured JSON output
- Immune JSON parsing
- Consistent error handling
"""

import os
import json
import json5
import dirtyjson
import regex as re
from typing import Dict, Any, Optional
from vertexai.preview import rag
from vertexai.generative_models import GenerativeModel, Tool, GenerationConfig
import vertexai


class LLMParseError(Exception):
    """Raised when JSON parsing fails after all attempts"""
    pass


class BaseRAGAgent:
    """
    Base class for all RAG-enabled AI agents.

    Usage:
        class SupplierContractReviewAgent(BaseRAGAgent):
            def __init__(self):
                super().__init__(model_name="gemini-2.5-pro")

            async def generate(self, ...):
                return await self.generate_with_rag(
                    prompt=prompt,
                    system_instruction=system_instruction,
                    response_schema=schema,
                    use_rag=False,
                )
    """

    def __init__(self, model_name: str = "gemini-2.5-flash"):
        """
        Initialize base agent.

        Args:
            model_name: "gemini-2.5-flash" (fast, cheap) or "gemini-2.5-pro" (powerful)
        """
        self.model_name = model_name
        self.project_id = os.environ.get("PROJECT_ID", "test-rag-corpus-project")
        self.location = os.environ.get("LOCATION", "us-west1")
        self.rag_corpus = os.environ.get(
            "RAG_CORPUS",
            "projects/test-rag-corpus-project/locations/us-west1/ragCorpora/137359788634800128"
        )

        # Initialize Vertex AI once
        vertexai.init(project=self.project_id, location=self.location)

    def get_rag_tool(self, similarity_top_k: int = 15) -> Tool:
        """
        Create RAG retrieval tool.

        Args:
            similarity_top_k: Number of similar documents to retrieve (default: 15)

        Returns:
            Vertex AI Tool configured for RAG retrieval
        """
        return Tool.from_retrieval(
            retrieval=rag.Retrieval(
                source=rag.VertexRagStore(
                    rag_resources=[rag.RagResource(rag_corpus=self.rag_corpus)],
                    similarity_top_k=similarity_top_k,
                )
            )
        )

    def get_model(self, system_instruction: str, use_rag: bool = True) -> GenerativeModel:
        """
        Create Gemini model with optional RAG.

        Args:
            system_instruction: System prompt for the model
            use_rag: Whether to enable RAG retrieval (default: True)

        Returns:
            Configured GenerativeModel instance
        """
        tools = [self.get_rag_tool()] if use_rag else []

        return GenerativeModel(
            model_name=self.model_name,
            tools=tools,
            system_instruction=system_instruction
        )

    def fix_json_with_llm(self, broken_json: str) -> str:
        """
        Use LLM to fix malformed JSON.

        Args:
            broken_json: Malformed JSON string

        Returns:
            Fixed JSON string
        """
        fix_model = GenerativeModel(model_name="gemini-2.5-pro")
        prompt = f"Fix this JSON syntax and return only valid JSON:\n\n{broken_json}"
        response = fix_model.generate_content(prompt)
        fixed_text = response.text.strip()
        fixed_text = fixed_text.replace('```json', '').replace('```', '')
        return fixed_text.strip()

    def strip_markdown_fences(self, text: str) -> str:
        """Remove markdown code fences from text"""
        return re.sub(
            r"```(?:json|markdown)?\s*([\s\S]*?)```",
            r"\1",
            text,
            flags=re.IGNORECASE,
        )

    def extract_json_candidate(self, text: str) -> str:
        """Extract largest JSON object from text"""
        matches = re.findall(
            r"""
            \{
                (?:
                    [^{}]++
                    |
                    (?R)
                )*
            \}
            """,
            text,
            flags=re.VERBOSE,
        )
        return max(matches, key=len) if matches else text

    def normalize_llm_json(self, text: str) -> str:
        """Normalize JSON by removing trailing commas and comments"""
        t = text.strip()
        t = re.sub(r",(\s*[}\]])", r"\1", t)  # Remove trailing commas
        t = re.sub(r"//.*?$", "", t, flags=re.MULTILINE)  # Remove // comments
        t = re.sub(r"/\*[\s\S]*?\*/", "", t)  # Remove /* */ comments
        return t

    def safe_parse_llm_json(self, text: str) -> Dict[str, Any]:
        """
        Parse JSON with multiple fallback strategies.

        Attempts:
        1. Standard json.loads
        2. json5.loads (allows trailing commas, comments)
        3. dirtyjson.loads (very permissive)
        4. LLM-based fix

        Args:
            text: JSON string (possibly malformed)

        Returns:
            Parsed dictionary

        Raises:
            LLMParseError: If all parsing attempts fail
        """
        cleaned = self.strip_markdown_fences(text)
        extracted = self.extract_json_candidate(cleaned)
        normalized = self.normalize_llm_json(extracted)

        # Try standard parsers
        for parser in (json.loads, json5.loads, dirtyjson.loads):
            try:
                parsed = parser(normalized)
                # Never treat plain prose/strings as structured output
                if isinstance(parsed, (dict, list)):
                    return parsed
            except Exception:
                continue

        # Final attempt: LLM fix
        try:
            fixed_json = self.fix_json_with_llm(text)
            parsed = json.loads(fixed_json)
            if isinstance(parsed, (dict, list)):
                return parsed
        except Exception:
            pass

        raise LLMParseError("Failed to recover JSON from model output")

    def _conforms_to_schema(self, data: Any, schema: Dict[str, Any]) -> bool:
        """Recursively validate data against a JSON schema (subset used by the
        review schemas: type / enum / required / items / properties /
        additionalProperties). Extra keys are rejected where
        additionalProperties is false, so prose or junk fields never pass."""
        if not isinstance(schema, dict):
            return True

        # enum
        enum = schema.get("enum")
        if enum is not None and data not in enum:
            return False

        base = schema.get("type")
        if base == "array":
            items = schema.get("items")
            if not isinstance(data, list):
                return False
            if items is not None:
                return all(self._conforms_to_schema(item, items) for item in data)
            return True
        if base == "object":
            if not isinstance(data, dict):
                return False
            props = schema.get("properties", {})
            required = schema.get("required", [])
            if any(k not in data for k in required):
                return False
            if schema.get("additionalProperties") is False:
                if any(k not in props for k in data):
                    return False
            return all(
                k in props and self._conforms_to_schema(v, props[k])
                for k, v in data.items()
            )
        if base == "string":
            return isinstance(data, str)
        if base == "integer":
            return isinstance(data, bool) is False and isinstance(data, int)
        if base == "number":
            return isinstance(data, bool) is False and isinstance(data, (int, float))
        if base == "boolean":
            return isinstance(data, bool)
        if base == "null":
            return data is None
        if schema.get("anyOf"):
            return any(self._conforms_to_schema(data, opt) for opt in schema["anyOf"])
        return True

    @staticmethod
    def _strip_additional_properties(schema: Any) -> Any:
        """Vertex's protobuf Schema has no `additionalProperties` field and
        raises ParseError if it is present. Key-whitelisting is enforced by the
        local `_conforms_to_schema` validator instead."""
        if isinstance(schema, list):
            return [BaseRAGAgent._strip_additional_properties(s) for s in schema]
        if isinstance(schema, dict):
            return {
                k: BaseRAGAgent._strip_additional_properties(v)
                for k, v in schema.items()
                if k != "additionalProperties"
            }
        return schema

    # The return type is kept as Dict for the normal path; validation ensures it.
    async def generate_with_rag(
        self,
        prompt: str,
        system_instruction: str,
        response_schema: Dict[str, Any],
        use_rag: bool = True
    ) -> Dict[str, Any]:
        """
        Generate structured output with optional RAG retrieval.

        Passes `response_schema` as a strict JSON schema constraint through
        GenerationConfig (response_mime_type="application/json",
        response_schema=...) so Gemini 2.5 Pro is bound to output-schema.md's
        shape. Parsed output is validated against that schema and regenerated
        once if it drifts (e.g. prose instead of JSON); only schema-conforming
        dicts are ever returned to the caller so the frontend always receives
        raw structured JSON, never markdown or a document echo.

        Raises:
            LLMParseError: If output cannot be parsed or does not conform.
        """
        # Create model
        model = self.get_model(system_instruction, use_rag=use_rag)

        # Configure structured output (strict schema from output-schema.md)
        generation_config = GenerationConfig(
            response_mime_type="application/json",
            # Vertex rejects additionalProperties; whitelisting is enforced by
            # _conforms_to_schema below.
            response_schema=self._strip_additional_properties(response_schema),
        )

        retry_note = (
            "\n\nYour previous output did not conform to the required JSON "
            "schema. Respond with ONLY a single JSON object exactly matching "
            "the schema — no prose, no markdown fences, no duplicated document "
            "text."
        )

        result = None
        for attempt in (1, 2):
            # Generate content
            response = model.generate_content(prompt, generation_config=generation_config)

            # Usage tracking — best-effort, never breaks generation
            try:
                self._log_usage(response, "generate_with_rag")
            except Exception:
                pass

            # Parse with fallback
            try:
                result = json.loads(response.text)
            except json.JSONDecodeError:
                try:
                    result = self.safe_parse_llm_json(response.text)
                except LLMParseError:
                    result = None

            if isinstance(result, dict) and self._conforms_to_schema(result, response_schema):
                return result

            # Non-conforming (prose, truncated, junk): retry once, then fail loudly
            if attempt == 1:
                prompt = prompt + retry_note
                continue

        raise LLMParseError(
            "Model output did not conform to the required JSON schema after retry"
        )

    def _log_usage(self, response, step: str) -> None:
        try:
            from admin_logger import log_token_usage
            usage = self.get_token_usage(response)
            if not usage or not usage.get("total_tokens"):
                return
            log_token_usage(
                "workflow_contract_review_agent_call",
                "workflow_anonymous",
                usage,
                {
                    "provider": "vertex",
                    "model": self.model_name,
                    "agent": self.__class__.__name__,
                    "feature": "contract_review",
                    "step": step,
                },
            )
        except Exception:
            pass

    def get_token_usage(self, response) -> Dict[str, int]:
        """
        Extract token usage from response.

        Args:
            response: Model response object

        Returns:
            Dictionary with input_tokens, output_tokens, total_tokens
        """
        if hasattr(response, 'usage_metadata'):
            return {
                "input_tokens": response.usage_metadata.prompt_token_count,
                "output_tokens": response.usage_metadata.candidates_token_count,
                "total_tokens": response.usage_metadata.total_token_count,
            }
        return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
