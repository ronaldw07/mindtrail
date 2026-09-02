"""Central configuration. Values are read once at import."""

import os

from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# Verified available on the free tier as of 2026-08-31. The Llama line was
# removed from Groq's catalog, so do not reintroduce llama-3.3-* here.
SYNTHESIS_MODEL = "openai/gpt-oss-120b"
FALLBACK_MODEL = "openai/gpt-oss-20b"
# No vision model exists on this account, but Whisper does, so dictation
# is server-side rather than depending on browser speech APIs.
TRANSCRIPTION_MODEL = "whisper-large-v3-turbo"

# Free tier is roughly 30 RPM / 12K TPM, so retries are mandatory rather
# than optional. See README for the measured limits.
MAX_RETRIES = 5
INITIAL_BACKOFF_SECONDS = 2.0

DEFAULT_TEMPERATURE = 0.3
# Evaluation pins temperature to 0. Sampling at the default made repeat
# runs of the same eval differ by a full session (4/6 then 3/6), which
# makes any single reported number meaningless.
EVAL_TEMPERATURE = 0.0

CHROMA_DIR = os.getenv("MINDTRAIL_CHROMA_DIR", "chroma_data")
COLLECTION_NAME = "research"

SEARCH_RESULTS_PER_QUERY = 6
# Four sources rather than three: synthesis quality is limited more by
# how much material it has than by the prompt. Each page is truncated, so
# this stays inside the free tier's per-minute token budget.
PAGES_FETCHED_PER_QUERY = 4
RELATED_MEMORIES_TO_INJECT = 3
