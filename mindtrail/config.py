"""Central configuration. Values are read once at import."""

import os

from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# From a user's own Google Cloud project (see README's Google Calendar
# setup section) - read from the environment or .env, never hardcoded or
# committed. Empty means the calendar feature has never been configured;
# `mindtrail calendar connect` checks for that before opening a browser.
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")

# Verified available on the free tier as of 2026-08-31. The Llama line was
# removed from Groq's catalog, so do not reintroduce llama-3.3-* here.
SYNTHESIS_MODEL = "openai/gpt-oss-120b"
FALLBACK_MODEL = "openai/gpt-oss-20b"

# Backups for when Groq's free daily allowance runs out (see llm.py). Each
# is used only if its key is set, in this order. Both speak the OpenAI
# chat format. Model names can be overridden in .env if a provider renames.
CEREBRAS_API_KEY = os.getenv("CEREBRAS_API_KEY", "")
CEREBRAS_MODEL = os.getenv("CEREBRAS_MODEL", "gpt-oss-120b")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
# 3.5-flash: the newer Flash models were turning requests away as
# overloaded when this was set up (2026-11-10); 3.5 answered every time.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
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
# Recall related notes with query expansion and a model re-rank (two extra
# model calls, run while the web search is already under way). Off with
# MINDTRAIL_DEEP_RECALL=0. See README's "Retrieval recall" section.
DEEP_RECALL = os.getenv("MINDTRAIL_DEEP_RECALL", "1") != "0"
