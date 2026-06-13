import os
import json
import logging
from groq import Groq

logger = logging.getLogger(__name__)

class GroqClient:
    def __init__(self):
        self.api_key = os.getenv("GROQ_API_KEY")
        if not self.api_key:
            raise ValueError("GROQ_API_KEY is not set in the environment variables.")
        self.client = Groq(api_key=self.api_key)
        self.model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

    def chat(self, messages: list, system: str = None, max_tokens: int = 1000) -> str:
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        
        # Format messages properly for the SDK
        for msg in messages:
            msgs.append({
                "role": msg.get("role", "user"),
                "content": msg.get("content", "")
            })
        
        attempts = 2
        for attempt in range(attempts):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=msgs,
                    max_tokens=max_tokens,
                )
                return response.choices[0].message.content
            except Exception as e:
                logger.error(f"Groq API error (attempt {attempt + 1}/{attempts}): {e}")
                if attempt == attempts - 1:
                    raise e

    def chat_json(self, messages: list, system: str = None) -> dict:
        system_suffix = "Respond in valid JSON only."
        full_system = f"{system}\n{system_suffix}" if system else system_suffix
        
        response_text = self.chat(messages, system=full_system)
        
        cleaned = response_text.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
        
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {cleaned}")
            # Try parsing any JSON sub-string in case there's surrounding text
            try:
                start_idx = cleaned.find("{")
                end_idx = cleaned.rfind("}")
                if start_idx != -1 and end_idx != -1:
                    return json.loads(cleaned[start_idx:end_idx+1])
            except Exception:
                pass
            raise e

_client_instance = None

def get_groq_client() -> GroqClient:
    global _client_instance
    if _client_instance is None:
        _client_instance = GroqClient()
    return _client_instance
