from __future__ import annotations

from .config import Settings
from .schemas import ModelCatalogEntry, ModelCatalogResponse, ModelProvider, SessionModelConfig


class ModelCatalog:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._models_by_provider = {
            "openai": self._parse_models(
                settings.openai_available_models,
                fallback=settings.default_openai_model,
            ),
            "anthropic": self._parse_models(
                settings.anthropic_available_models,
                fallback=settings.default_anthropic_model,
            ),
        }

    def as_response(self) -> ModelCatalogResponse:
        models = [
            ModelCatalogEntry(
                provider=provider,
                model_name=model_name,
                label=model_name,
            )
            for provider, model_names in self._models_by_provider.items()
            for model_name in model_names
        ]
        return ModelCatalogResponse(
            default_provider=self.settings.default_model_provider,
            default_model_name=self.default_for(self.settings.default_model_provider),
            models=models,
        )

    def default_config(self) -> SessionModelConfig:
        provider = self.settings.default_model_provider
        return SessionModelConfig(
            model_provider=provider,
            model_name=self.default_for(provider),
        )

    def validate(self, provider: ModelProvider, model_name: str) -> SessionModelConfig:
        normalized = model_name.strip()
        if normalized not in self._models_by_provider[provider]:
            raise ValueError(f"Model '{normalized}' is not enabled for provider '{provider}'")
        return SessionModelConfig(model_provider=provider, model_name=normalized)

    def default_for(self, provider: ModelProvider) -> str:
        return self._models_by_provider[provider][0]

    def _parse_models(self, raw_value: str | None, fallback: str) -> list[str]:
        if raw_value:
            models = [item.strip() for item in raw_value.split(",") if item.strip()]
            if models:
                return self._dedupe(models)
        return [fallback]

    def _dedupe(self, values: list[str]) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for value in values:
            if value not in seen:
                seen.add(value)
                deduped.append(value)
        return deduped
