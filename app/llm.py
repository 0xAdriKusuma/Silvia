from openai import AsyncOpenAI
from app.config import (
    LLM_API_KEY,
    LLM_BASE_URL,
    CHARACTER_NAME,
    PERSONA_PATH,
)


def load_system_prompt() -> str:
    """Muat persona karakter dari file prompts/persona.txt."""
    if PERSONA_PATH.exists():
        text = PERSONA_PATH.read_text(encoding="utf-8")
        return text.format(CHARACTER_NAME=CHARACTER_NAME)
    
    # Fallback default prompt
    return (
        f"Kamu adalah {CHARACTER_NAME}, karakter anime perempuan yang ceria, manja, dan agak posesif terhadap pengguna.\n"
        "Pengguna berbicara bahasa Indonesia, tetapi kamu SELALU membalas dalam bahasa Jepang lisan yang santai.\n"
        "Format tiap baris: [emosi] kalimat Jepang|||terjemahan Indonesia\n"
        "Emosi yang boleh dipakai: happy, neutral, sad, angry, shy"
    )


def get_llm_client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
