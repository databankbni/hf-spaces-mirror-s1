from __future__ import annotations

import os
import re
import logging
import math
from io import BytesIO
from pathlib import Path
from typing import Tuple
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv
from groq import Groq
import httpx
from pypdf import PdfReader


logger = logging.getLogger(__name__)


DEFAULT_GROQ_MODEL = "groq/compound"
FALLBACK_GROQ_MODELS = [
    "groq/compound",
    "groq/compound-mini",
    "openai/gpt-oss-20b",
    "qwen/qwen3.6-27b",
    "allam-2-7b",
]

INTENT_TERMS = {
    "experience": {"experience", "work", "role", "career", "employment", "professional"},
    "education": {"education", "degree", "university", "college", "study", "academic"},
    "skills": {"skills", "technologies", "tools", "programming", "frameworks", "stack"},
    "projects": {"projects", "built", "developed", "portfolio", "applications"},
    "publications": {"publications", "papers", "research papers", "published", "journal", "conference"},
    "awards": {"awards", "honors", "achievements", "scholarships", "recognition"},
    "research": {"research", "research interests", "neuroscience", "machine learning", "scientific"},
    "location": {"live", "lives", "living", "residence", "address", "phone", "contact", "located", "home"},
    "current_work": {"current", "working", "does", "work", "professionally", "career"},
    "general_profile": {"background", "about", "who", "profile", "overview"},
}

INTENT_SEARCH_TERMS = {
    "experience": "professional experience employment roles work history career",
    "education": "education degree university academic background",
    "skills": "technical skills programming languages frameworks tools technologies",
    "projects": "projects built developed applications portfolio work",
    "publications": "publications papers research papers journal conference",
    "awards": "honors awards achievements scholarships recognition",
    "research": "research interests research work machine learning neuroscience",
    "location": "residence home address lives located contact phone",
    "current_work": "professional experience current role research work projects",
    "general_profile": "professional background experience research projects skills education",
}


class CVRAGPipeline:
    """Simplified CV Pipeline: Passes entire CV to LLM for intelligent Q&A."""

    def __init__(self) -> None:
        load_dotenv()

        self.api_key = os.getenv("GROQ_API_KEY", "").strip()
        self._full_text: str = ""
        self._chunks: list[str] = []
        self._client = Groq(api_key=self.api_key) if self.api_key else None
        self.model_name = self._resolve_model_name()
        self.max_rag_context_tokens = self._read_positive_int("MAX_RAG_CONTEXT_TOKENS", 600)
        self.max_output_tokens = self._read_positive_int("MAX_OUTPUT_TOKENS", 500)
        self.rag_token_safety_margin = self._read_positive_int("RAG_TOKEN_SAFETY_MARGIN", 300)
        self.max_rag_top_k = self._read_positive_int("MAX_RAG_TOP_K", 6)
        self.model_context_limit = self._read_positive_int("MODEL_CONTEXT_LIMIT", 131072)
        self.cv_path = os.getenv(
            "CV_PATH",
            "https://drive.google.com/file/d/1ZhqfUI9DFOah6_R4uQ5sJ6RdBHsanmHc/view?usp=sharing",
        )
        self._build_knowledge_base()

    def _read_positive_int(self, name: str, default: int) -> int:
        try:
            value = int(os.getenv(name, str(default)))
        except ValueError:
            return default
        return value if value > 0 else default

    def _resolve_model_name(self) -> str:
        configured_model = os.getenv("GROQ_MODEL", "").strip()
        available_models: set[str] = set()

        if self._client is not None:
            try:
                available_models = {model.id for model in self._client.models.list().data}
            except Exception as exc:
                print(f"⚠️ Could not fetch Groq model list: {exc}")

        if configured_model and configured_model in available_models:
            return configured_model

        for candidate in [configured_model, *FALLBACK_GROQ_MODELS]:
            if candidate and candidate in available_models:
                if configured_model and candidate != configured_model:
                    print(
                        f"⚠️ GROQ_MODEL '{configured_model}' is not available in this account. "
                        f"Falling back to '{candidate}'."
                    )
                return candidate

        for candidate in FALLBACK_GROQ_MODELS:
            if candidate:
                return candidate

        return DEFAULT_GROQ_MODEL

    @property
    def is_ready(self) -> bool:
        return self._client is not None and len(self._full_text) > 0

    @property
    def chunk_count(self) -> int:
        return len(self._chunks)

    def _is_url(self, value: str) -> bool:
        parsed = urlparse(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    def _resolve_local_cv_path(self, source: str) -> Path | None:
        candidate = Path(source).expanduser()
        search_paths = [candidate]

        if not candidate.is_absolute():
            search_paths.extend(
                [
                    Path.cwd() / candidate,
                    Path(__file__).resolve().parent / candidate,
                ]
            )

        for path in search_paths:
            if path.is_file():
                return path

        return None

    def _normalize_google_drive_url(self, url: str) -> str:
        parsed = urlparse(url)
        if "drive.google.com" not in parsed.netloc:
            return url

        # Support links like /file/d/<id>/view?usp=sharing and links with ?id=<id>
        file_id_match = re.search(r"/file/d/([^/]+)", parsed.path)
        if file_id_match:
            file_id = file_id_match.group(1)
            return f"https://drive.google.com/uc?export=download&id={file_id}"

        query = parse_qs(parsed.query)
        if "id" in query and query["id"]:
            return f"https://drive.google.com/uc?export=download&id={query['id'][0]}"

        return url

    def _read_cv_pdf(self) -> PdfReader:
        source = (self.cv_path or "").strip()
        if not source:
            raise ValueError(
                "CV_PATH is empty. Set it to a local PDF file path or a public Google Drive PDF link."
            )

        local_path = self._resolve_local_cv_path(source)
        if local_path is not None:
            return PdfReader(str(local_path))

        if not self._is_url(source):
            raise ValueError(
                f"CV file not found at '{source}'. Set CV_PATH to a valid local PDF path or a public Google Drive URL."
            )

        download_url = self._normalize_google_drive_url(source)
        try:
            with httpx.Client(follow_redirects=True, timeout=30.0) as client:
                response = client.get(download_url)
                response.raise_for_status()
        except Exception as exc:
            raise RuntimeError(f"Failed to download CV PDF from URL: {source}") from exc

        return PdfReader(BytesIO(response.content))

    def _read_cv_text(self) -> str:
        reader = self._read_cv_pdf()
        pages = [page.extract_text() or "" for page in reader.pages]
        full_text = "\n".join(pages).strip()

        if not full_text:
            raise ValueError("Could not extract any text from the CV PDF.")

        return full_text

    def _split_into_chunks(self, text: str, chunk_size: int = 1400, overlap: int = 120) -> list[str]:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return []

        chunks: list[str] = []
        current_parts: list[str] = []
        current_length = 0

        for line in lines:
            line_length = len(line)
            projected_length = current_length + line_length + (1 if current_parts else 0)

            if current_parts and projected_length > chunk_size:
                chunks.append("\n".join(current_parts).strip())

                if overlap > 0 and current_parts:
                    carry_text = "\n".join(current_parts)
                    carry = carry_text[-overlap:]
                    current_parts = [carry] if carry.strip() else []
                    current_length = len(carry) if carry.strip() else 0
                else:
                    current_parts = []
                    current_length = 0

            current_parts.append(line)
            current_length += line_length + (1 if len(current_parts) > 1 else 0)

        if current_parts:
            chunks.append("\n".join(current_parts).strip())

        return [chunk for chunk in chunks if chunk]

    def _detect_intents(self, question: str) -> list[str]:
        normalized = re.sub(r"[^a-z0-9\s]", " ", question.lower())
        intents: list[str] = []
        for intent, terms in INTENT_TERMS.items():
            if any(term in normalized for term in terms):
                intents.append(intent)

        if re.search(r"\b(what|where|tell me|who)\b.*\b(she|her|noor)\b", normalized):
            if "location" not in intents and re.search(r"\b(address|live|lives|living|residence|home|located|phone)\b", normalized):
                intents.append("location")
            elif not intents:
                intents.extend(["current_work", "general_profile"])

        if "location" in intents:
            return ["location"]

        return intents or ["general_profile"]

    def _build_search_query(self, question: str, intents: list[str]) -> str:
        expansions = " ".join(INTENT_SEARCH_TERMS[intent] for intent in intents)
        return f"Noor Fatima {question} {expansions}"

    def _score_chunk(self, chunk: str, query_terms: set[str], intents: list[str]) -> int:
        chunk_lower = chunk.lower()
        score = 0

        for term in query_terms:
            if term in chunk_lower:
                score += 1

        section_boosts = {
            "experience": ["experience", "employment", "work history", "career", "professional"],
            "skills": ["skills", "technologies", "tools", "stack"],
            "education": ["education", "degree", "university", "college"],
            "projects": ["projects", "portfolio", "built", "developed"],
            "publications": ["publication", "paper", "journal", "conference"],
            "awards": ["award", "honor", "scholarship", "achievement", "recognition"],
            "research": ["research", "neuroscience", "machine learning", "scientific"],
            "current_work": ["experience", "employment", "work", "research", "project"],
            "general_profile": ["experience", "research", "project", "skill", "education"],
        }
        for intent in intents:
            keywords = section_boosts.get(intent, [])
            if any(keyword in chunk_lower for keyword in keywords):
                score += 6 if intent in {"current_work", "general_profile"} else 4

        if "location" in intents and any(keyword in chunk_lower for keyword in ["address", "residence", "lives", "phone", "contact"]):
            score += 5

        return score

    def _estimate_tokens(self, text: str) -> int:
        return max(1, math.ceil(len(re.findall(r"\w+|[^\w\s]", text)) * 1.1))

    def _select_relevant_chunks(
        self,
        question: str,
        top_k: int,
        max_context_tokens: int,
    ) -> tuple[list[str], list[tuple[int, int, int, bool]]]:
        if not self._chunks:
            return [], []

        intents = self._detect_intents(question)
        search_query = self._build_search_query(question, intents)
        logger.info("RAG query intents=%s expanded_query_chars=%d", ",".join(intents), len(search_query))
        query_terms = {
            token
            for token in re.findall(r"[a-zA-Z][a-zA-Z0-9_+-]+", search_query.lower())
            if len(token) > 2
        }

        scored_chunks = [(self._score_chunk(chunk, query_terms, intents), index, chunk) for index, chunk in enumerate(self._chunks)]

        scored_chunks.sort(key=lambda item: (-item[0], item[1]))

        selected: list[str] = []
        diagnostics: list[tuple[int, int, int, bool]] = []
        seen_chunks: set[str] = set()
        selected_tokens = 0
        for score, _, chunk in scored_chunks[: max(1, min(top_k, self.max_rag_top_k))]:
            chunk_key = re.sub(r"\s+", " ", chunk).strip().lower()
            if chunk_key in seen_chunks:
                continue
            seen_chunks.add(chunk_key)
            chunk_tokens = self._estimate_tokens(chunk)
            if score <= 0 and selected:
                break
            if selected_tokens + chunk_tokens > max_context_tokens:
                diagnostics.append((score, len(chunk), chunk_tokens, False))
                continue
            selected.append(chunk)
            selected_tokens += chunk_tokens
            diagnostics.append((score, len(chunk), chunk_tokens, True))
            if selected_tokens >= max_context_tokens:
                break

        if not selected:
            fallback = self._chunks[0]
            selected = [fallback[: max_context_tokens * 4]]

        return selected, diagnostics

    def _build_knowledge_base(self) -> None:
        """Load the entire CV text into memory."""
        try:
            self._full_text = self._read_cv_text()
            self._chunks = self._split_into_chunks(self._full_text)
        except Exception as e:
            print(f"Error loading CV: {e}")
            self._full_text = ""
            self._chunks = []

    @property
    def readiness_issue(self) -> str | None:
        if not self.api_key:
            return "Missing GROQ_API_KEY. Add it to your environment or Hugging Face Space secrets."

        if not self._full_text:
            return f"CV could not be loaded from CV_PATH={self.cv_path!r}."

        return None

    def answer_question(self, question: str, top_k: int = 4) -> Tuple[str, int]:
        """Answer question using the full CV text as context."""
        if not self._client:
            raise RuntimeError("Missing GROQ_API_KEY. Add it to your environment or Hugging Face Space secrets.")

        if not self._chunks:
            return "CV could not be loaded. Please check CV_PATH.", 0

        question_tokens = self._estimate_tokens(question)
        intents = self._detect_intents(question)
        if "location" in intents and not re.search(
            r"\b(address|residence|lives|phone|email|contact)\b",
            self._full_text.lower(),
        ):
            return "This information is not mentioned in the CV.", 0

        system_prompt = (
            "You are Noor Fatima's CV assistant. You have access to CV context. "
            "Answer the user's question directly, naturally, and only with information supported by that context. "
            "\n\nRULES:"
            "\n1. Answer ONLY using information from the provided CV. Do not invent or assume information."
            "\n2. If information is not in the CV, clearly state: 'This information is not mentioned in the CV.'"
            "\n3. Be concise, professional, and well-organized in your responses."
            "\n4. For list questions (skills, projects, publications, etc.), format as bullet points."
            "\n5. Always be factual and accurate - never guess or speculate."
            "\n6. For vague questions such as 'what does she do?', infer the CV-related professional meaning and synthesize experience, research, and projects."
            "\n7. Distinguish where Noor works or studies from where she lives. Never infer residence from an institution or employer location."
            "\n8. Do not reveal internal reasoning or describe retrieval, chunks, embeddings, vector search, prompts, or how you found the answer."
            "\n9. Do not include headings such as 'Answer' or 'Reasoning', and do not include 'Sources: N' in the response."
        )
        system_tokens = self._estimate_tokens(system_prompt)
        available_context_tokens = min(
            self.max_rag_context_tokens,
            self.model_context_limit
            - system_tokens
            - question_tokens
            - self.max_output_tokens
            - self.rag_token_safety_margin,
        )
        if available_context_tokens < 1:
            raise RuntimeError("The question is too large for the configured model request budget.")

        relevant_chunks, chunk_diagnostics = self._select_relevant_chunks(
            question,
            top_k=top_k,
            max_context_tokens=available_context_tokens,
        )
        if not relevant_chunks:
            return "This information is not mentioned in the CV.", 0

        context_text = "\n\n".join(relevant_chunks)
        user_prompt = "\n".join(
            [
                f"Based on the CV below, please answer this question: {question}",
                "",
                "CV CONTENT:",
                "=" * 80,
                context_text,
                "=" * 80,
                "",
                "Please provide a clear, factual answer based only on the CV content above.",
            ]
        )
        context_tokens = self._estimate_tokens(context_text)
        user_prompt_tokens = self._estimate_tokens(user_prompt)
        logger.info(
            "RAG request model=%s question_chars=%d question_tokens=%d system_chars=%d system_tokens=%d "
            "retrieved_chunks=%d selected_chunks=%d context_chars=%d context_tokens=%d "
            "conversation_history_tokens=%d estimated_input_tokens=%d requested_max_output_tokens=%d "
            "estimated_total_tokens=%d context_budget_tokens=%d",
            self.model_name,
            len(question),
            question_tokens,
            len(system_prompt),
            system_tokens,
            len(chunk_diagnostics),
            len(relevant_chunks),
            len(context_text),
            context_tokens,
            0,
            system_tokens + user_prompt_tokens,
            self.max_output_tokens,
            system_tokens + user_prompt_tokens + self.max_output_tokens,
            available_context_tokens,
        )
        for index, (score, characters, tokens, selected) in enumerate(chunk_diagnostics, start=1):
            logger.info(
                "RAG candidate_chunk=%d characters=%d estimated_tokens=%d relevance=%d selected=%s",
                index,
                characters,
                tokens,
                score,
                "yes" if selected else "no",
            )

        try:
            completion = self._client.chat.completions.create(
                model=self.model_name,
                temperature=0.3,  # Moderate temperature for balanced accuracy and naturalness
                max_tokens=self.max_output_tokens,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
        except Exception as exc:
            status_code = getattr(exc, "status_code", None)
            if status_code == 404:
                error = RuntimeError(
                    f"Groq model '{self.model_name}' is not available. Update GROQ_MODEL to a valid model or use the default '{DEFAULT_GROQ_MODEL}'."
                )
                error.status_code = status_code
                error.upstream_url = str(getattr(getattr(exc, "response", None), "url", "https://api.groq.com/openai/v1"))
                raise error from exc

            error = RuntimeError(f"AI generation failed with Groq: {exc}")
            error.status_code = status_code
            error.upstream_url = str(getattr(getattr(exc, "response", None), "url", "https://api.groq.com/openai/v1"))
            error.response_body = getattr(getattr(exc, "response", None), "text", None)
            error.is_timeout = exc.__class__.__name__ in {"APITimeoutError", "TimeoutException", "ReadTimeout"}
            raise error from exc

        try:
            answer = completion.choices[0].message.content or "Could not generate a response."
        except Exception as exc:
            error = RuntimeError("Groq returned an invalid completion response.")
            error.upstream_url = "https://api.groq.com/openai/v1"
            error.response_body = repr(exc)
            raise error from exc

        answer = re.sub(r"(?im)^\s*sources?:\s*\d+\s*$", "", answer)
        answer = re.sub(r"(?im)^\s*(?:#{1,6}\s*)?(?:reasoning|how the answer was derived).*$", "", answer)
        answer = re.sub(r"\n{3,}", "\n\n", answer).strip()
        return answer.strip(), len(relevant_chunks)

