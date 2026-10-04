from abc import ABC, abstractmethod
import os
import requests
from typing import Any, Dict, List, Optional

from .database import get_db_connection

ZEN_BASE_URL = "https://opencode.ai/zen/v1"
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"

# Catálogo de proveedores IA (spec 003 §2).
# Nota: los modelos Free de OpenCode Zen distintos de "space-bunny-free"
# devuelven 403 FreeTierError ("free tier can only be used from within
# OpenCode") cuando se invocan con API key desde fuera de la app
# (verificado 2026-10-02 contra el gateway real). Por eso el grupo
# "free" solo incluye Space Bunny.
AI_PROVIDER_CATALOG: List[Dict[str, Any]] = [
    {"id": "space-bunny-free", "label": "Space Bunny Free", "group": "free", "model": "space-bunny-free", "endpoint": "chat", "requires": "zen"},
    {"id": "anomalia_ollama", "label": "anomalia_ollama (Local)", "group": "local", "model": None, "endpoint": None, "requires": None},
    {"id": "gemini", "label": "Gemini (Google)", "group": "apikey", "model": None, "endpoint": None, "requires": "gemini"},
]

DEFAULT_AI_PROVIDER = "anomalia_ollama"
DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"

GEMINI_MODEL_FALLBACK: List[str] = [
    "gemini-3.5-flash-lite",
    "gemini-3.5-flash",
    "gemini-3.1-pro",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
]

AI_TIMEOUT_SECONDS = 45


class AIProviderError(Exception):
    """Error de comunicación o configuración del proveedor de IA."""


def build_alert_prompt(alert_data: Dict[str, Any]) -> str:
    labels = alert_data.get("labels", {}) or {}
    annotations = alert_data.get("annotations", {}) or {}
    labels_formatted = "\n".join([f"  - {k}: {v}" for k, v in labels.items()])
    annotations_formatted = "\n".join([f"  - {k}: {v}" for k, v in annotations.items()])
    return (
        "Actúa como un SRE y experto en DevOps senior. Analiza la siguiente alerta de infraestructura.\n"
        "Usa las etiquetas y anotaciones de forma interna para ubicar el problema (clúster, nodo, servicio, entorno), "
        "pero **no enumeres las etiquetas**. \n"
        "Escribe un diagnóstico ultra conciso de una sola oración y un listado de máximo 3 pasos cortos para resolverlo.\n\n"
        f"Etiquetas (Labels):\n{labels_formatted}\n\n"
        f"Anotaciones (Annotations):\n{annotations_formatted}"
    )


class BaseAIProvider(ABC):
    @abstractmethod
    def generate(self, prompt: str) -> str:
        pass

    def analyze_alert(self, alert_data: Dict[str, Any]) -> str:
        try:
            return self.generate(build_alert_prompt(alert_data))
        except AIProviderError as e:
            return str(e)


class OllamaProvider(BaseAIProvider):
    def __init__(self, host: Optional[str] = None, model: Optional[str] = None) -> None:
        self.host = host or os.getenv("OLLAMA_HOST", "http://anomalia_ollama:11434")
        self.model = model or os.getenv("OLLAMA_MODEL", "llama3.2:1b")

    def generate(self, prompt: str) -> str:
        try:
            response = requests.post(
                f"{self.host}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.2},
                },
                timeout=AI_TIMEOUT_SECONDS,
            )
            if response.status_code == 200:
                return response.json().get("response", "No se obtuvo respuesta de la IA.")
            raise AIProviderError(f"Error en Ollama: Código {response.status_code}")
        except AIProviderError:
            raise
        except Exception as e:
            raise AIProviderError(f"No se pudo conectar con Ollama local: {str(e)}")


class ZenProvider(BaseAIProvider):
    """Cliente OpenAI-compatible del gateway OpenCode Zen (modelos Free)."""

    def __init__(self, api_key: str, model: str, endpoint: str = "chat") -> None:
        self.api_key = api_key
        self.model = model
        self.endpoint = endpoint

    def generate(self, prompt: str) -> str:
        if not self.api_key:
            raise AIProviderError("API Key Zen no configurada. Ingrésala en Proveedor IA.")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            if self.endpoint == "responses":
                response = requests.post(
                    f"{ZEN_BASE_URL}/responses",
                    headers=headers,
                    json={"model": self.model, "input": prompt, "temperature": 0.2},
                    timeout=AI_TIMEOUT_SECONDS,
                )
                if response.status_code == 200:
                    return self._parse_responses(response.json())
                raise AIProviderError(
                    f"Error en OpenCode Zen: Código {response.status_code} - {self._error_detail(response)}"
                )
            response = requests.post(
                f"{ZEN_BASE_URL}/chat/completions",
                headers=headers,
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                },
                timeout=AI_TIMEOUT_SECONDS,
            )
            if response.status_code == 200:
                data = response.json()
                return data.get("choices", [{}])[0].get("message", {}).get("content", "No se obtuvo respuesta de la IA.")
            raise AIProviderError(
                f"Error en OpenCode Zen: Código {response.status_code} - {self._error_detail(response)}"
            )
        except AIProviderError:
            raise
        except Exception as e:
            raise AIProviderError(f"No se pudo conectar con OpenCode Zen: {str(e)}")

    @staticmethod
    def _parse_responses(data: Dict[str, Any]) -> str:
        for item in data.get("output", []) or []:
            if item.get("type") != "message":
                continue
            for content in item.get("content", []) or []:
                if content.get("type") == "output_text" and content.get("text"):
                    return content["text"]
        return "No se obtuvo respuesta de la IA."

    @staticmethod
    def _error_detail(response: requests.Response) -> str:
        try:
            return response.json().get("error", {}).get("message", response.text[:200])
        except Exception:
            return response.text[:200]


class GeminiProvider(BaseAIProvider):
    def __init__(self, api_key: str, model: Optional[str] = None) -> None:
        self.api_key = api_key
        self.model = model or DEFAULT_GEMINI_MODEL

    def generate(self, prompt: str) -> str:
        if not self.api_key:
            raise AIProviderError("API Key de Gemini no configurada. Ingrésala en Proveedor IA.")
        try:
            response = requests.post(
                f"{GEMINI_API_BASE}/models/{self.model}:generateContent",
                params={"key": self.api_key},
                json={
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0.2},
                },
                timeout=AI_TIMEOUT_SECONDS,
            )
            if response.status_code == 200:
                data = response.json()
                candidates = data.get("candidates", []) or []
                parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
                text = "".join(p.get("text", "") for p in parts).strip()
                return text or "No se obtuvo respuesta de la IA."
            raise AIProviderError(
                f"Error en Gemini: Código {response.status_code} - {self._error_detail(response)}"
            )
        except AIProviderError:
            raise
        except Exception as e:
            raise AIProviderError(f"No se pudo conectar con Gemini: {str(e)}")

    @staticmethod
    def _error_detail(response: requests.Response) -> str:
        try:
            return response.json().get("error", {}).get("message", response.text[:200])
        except Exception:
            return response.text[:200]


def get_gemini_models(api_key: str) -> List[str]:
    """Lista modelos con soporte generateContent desde la API de Google."""
    if not api_key:
        return list(GEMINI_MODEL_FALLBACK)
    try:
        response = requests.get(
            f"{GEMINI_API_BASE}/models",
            params={"key": api_key, "pageSize": 100},
            timeout=15,
        )
        if response.status_code != 200:
            return list(GEMINI_MODEL_FALLBACK)
        models: List[str] = []
        for m in response.json().get("models", []) or []:
            name = m.get("name", "")
            if name.startswith("models/"):
                name = name[len("models/"):]
            if name and "generateContent" in (m.get("supportedGenerationMethods") or []):
                models.append(name)
        return models or list(GEMINI_MODEL_FALLBACK)
    except Exception:
        return list(GEMINI_MODEL_FALLBACK)


def get_ai_settings() -> Dict[str, Any]:
    """Lee la fila única de ai_settings. Fallback a env si la tabla no existe."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT selected_provider, zen_api_key, gemini_api_key, gemini_model "
                "FROM ai_settings ORDER BY id LIMIT 1"
            )
            row = cursor.fetchone()
            if row:
                return {
                    "selected_provider": row[0] or DEFAULT_AI_PROVIDER,
                    "zen_api_key": row[1] or "",
                    "gemini_api_key": row[2] or "",
                    "gemini_model": row[3] or DEFAULT_GEMINI_MODEL,
                }
        finally:
            cursor.close()
            conn.close()
    except Exception:
        pass
    return {
        "selected_provider": os.getenv("AI_PROVIDER", DEFAULT_AI_PROVIDER),
        "zen_api_key": os.getenv("OPENCODE_API_KEY", ""),
        "gemini_api_key": os.getenv("GEMINI_API_KEY", ""),
        "gemini_model": DEFAULT_GEMINI_MODEL,
    }


def get_provider(provider_id: Optional[str] = None) -> BaseAIProvider:
    settings = get_ai_settings()
    pid = (provider_id or settings.get("selected_provider") or DEFAULT_AI_PROVIDER).lower()
    catalog = {p["id"]: p for p in AI_PROVIDER_CATALOG}
    entry = catalog.get(pid)
    if entry is None:
        entry = catalog[DEFAULT_AI_PROVIDER]
    if entry["group"] == "free":
        return ZenProvider(
            api_key=settings.get("zen_api_key", ""),
            model=entry["model"] or "",
            endpoint=entry["endpoint"] or "chat",
        )
    if entry["group"] == "apikey":
        return GeminiProvider(
            api_key=settings.get("gemini_api_key", ""),
            model=settings.get("gemini_model") or DEFAULT_GEMINI_MODEL,
        )
    return OllamaProvider()
