from abc import ABC, abstractmethod
import os
import requests
from typing import Dict, Any

class BaseAIProvider(ABC):
    @abstractmethod
    def analyze_alert(self, alert_data: Dict[str, Any]) -> str:
        pass

class OllamaProvider(BaseAIProvider):
    def __init__(self):
        self.host = os.getenv("OLLAMA_HOST", "http://ollama:11434")
        self.model = os.getenv("OLLAMA_MODEL", "llama3.2")

    def analyze_alert(self, alert_data: Dict[str, Any]) -> str:
        # Extraemos etiquetas y anotaciones para pasárselas completas a la IA
        labels = alert_data.get("labels", {})
        annotations = alert_data.get("annotations", {})
        
        # Formateamos los datos en texto legible para que el modelo analice todo el contexto
        labels_formatted = "\n".join([f"  - {k}: {v}" for k, v in labels.items()])
        annotations_formatted = "\n".join([f"  - {k}: {v}" for k, v in annotations.items()])

        prompt = (
            f"Actúa como un SRE y experto en DevOps senior. Analiza la siguiente alerta de infraestructura.\n"
            f"Usa las etiquetas y anotaciones de forma interna para ubicar el problema (clúster, nodo, servicio, entorno), "
            f"pero **no enumeres las etiquetas**. \n"
            f"Escribe un diagnóstico ultra conciso de una sola oración y un listado de máximo 3 pasos cortos para resolverlo.\n\n"
            f"Etiquetas (Labels):\n{labels_formatted}\n\n"
            f"Anotaciones (Annotations):\n{annotations_formatted}"
        )
        try:
            response = requests.post(
                f"{self.host}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "num_predict": 500,  # Límite para mantener agilidad
                        "temperature": 0.2
                    }
                },
                timeout=45
            )
            if response.status_code == 200:
                return response.json().get("response", "No se obtuvo respuesta de la IA.")
            return f"Error en Ollama: Código {response.status_code}"
        except Exception as e:
            return f"No se pudo conectar con Ollama local: {str(e)}"

class GeminiProvider(BaseAIProvider):
    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY", "")

    def analyze_alert(self, alert_data: Dict[str, Any]) -> str:
        if not self.api_key:
            return "Error: API Key de Gemini no configurada."
        return f"[Simulado Gemini] Análisis para: {alert_data.get('labels', {}).get('alertname', 'Desconocida')}"

class AIProviderFactory:
    @staticmethod
    def get_provider() -> BaseAIProvider:
        provider_type = os.getenv("AI_PROVIDER", "ollama").lower()
        if provider_type == "gemini":
            return GeminiProvider()
        return OllamaProvider()
