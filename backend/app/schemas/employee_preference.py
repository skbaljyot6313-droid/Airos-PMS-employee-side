"""Employee preference contracts — language settings on the wire."""

from pydantic import BaseModel, field_validator

from app.domain.languages import is_supported


class LanguageMeta(BaseModel):
    code: str
    name: str
    native_name: str


class EmployeePreferencesOut(BaseModel):
    text_language: str
    audio_language: str
    available_languages: list[LanguageMeta]


class EmployeePreferencesPatch(BaseModel):
    """Partial update — each field independent; omitted fields keep their
    stored value. Language codes are validated against the registry, so
    unsupported codes are a 422 before the service runs."""

    text_language: str | None = None
    audio_language: str | None = None

    @field_validator("text_language", "audio_language")
    @classmethod
    def _supported(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip().lower()
        if not is_supported(v):
            raise ValueError(f"unsupported language code: {v!r}")
        return v
