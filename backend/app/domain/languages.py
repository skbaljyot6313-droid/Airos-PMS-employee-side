"""Canonical language registry — ONE definition, imported everywhere.

Employee-facing text and audio languages. Adding a language means adding
one entry here (plus frontend translation resources); nothing else in the
API needs to change. `locale` is the BCP-47 tag handed to device TTS.

The backend stores only the ISO 639-1 `code`; presentation metadata
(name/native_name/locale) is served to clients via the languages
endpoint, never trusted from the wire.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Language:
    code: str
    name: str
    native_name: str
    locale: str  # TTS locale tag, e.g. "en-IN"


SUPPORTED_LANGUAGES: tuple[Language, ...] = (
    Language(code="en", name="English", native_name="English", locale="en-IN"),
    Language(code="hi", name="Hindi", native_name="हिन्दी", locale="hi-IN"),
    Language(code="mr", name="Marathi", native_name="मराठी", locale="mr-IN"),
)

SUPPORTED_LANGUAGE_CODES: frozenset[str] = frozenset(
    lang.code for lang in SUPPORTED_LANGUAGES
)

DEFAULT_LANGUAGE = "en"


def is_supported(code: str) -> bool:
    return code in SUPPORTED_LANGUAGE_CODES


def tts_locale(code: str) -> str:
    """TTS locale for a language code; falls back to the default's locale."""
    for lang in SUPPORTED_LANGUAGES:
        if lang.code == code:
            return lang.locale
    return next(lang.locale for lang in SUPPORTED_LANGUAGES
                if lang.code == DEFAULT_LANGUAGE)
