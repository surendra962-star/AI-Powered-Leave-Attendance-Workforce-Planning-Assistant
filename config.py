"""Environment configuration shared by the Flask and Streamlit entrypoints."""
from __future__ import annotations

import os
from pathlib import Path


ROOT = Path(__file__).resolve().parent
FLASK_API_URL = os.getenv("FLASK_API_URL", "http://127.0.0.1:5001").rstrip("/")
FLASK_HOST = os.getenv("FLASK_HOST", "127.0.0.1")
FLASK_PORT = int(os.getenv("FLASK_PORT", "5001"))
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
