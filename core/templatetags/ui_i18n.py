from django import template

from core.ui_language import DEFAULT_LANGUAGE, normalize_language, text
from core.ui_language_dashboard import DASHBOARD_TRANSLATIONS
from core.ui_language_detail import DETAIL_TRANSLATIONS
from core.ui_language_extra import EXTRA_TRANSLATIONS

register = template.Library()


@register.simple_tag(takes_context=True)
def t(context, key: str) -> str:
    """Return one translated UI string for the active session language."""

    language = normalize_language(context.get("ui_language", DEFAULT_LANGUAGE))
    normalized_key = str(key)
    for catalog in (
        DETAIL_TRANSLATIONS,
        DASHBOARD_TRANSLATIONS,
        EXTRA_TRANSLATIONS,
    ):
        if normalized_key in catalog.get(language, {}):
            return catalog[language][normalized_key]
    return text(language, normalized_key)
