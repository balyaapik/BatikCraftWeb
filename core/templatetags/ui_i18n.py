from django import template
from django.utils.safestring import mark_safe

from core.ui_language import DEFAULT_LANGUAGE, normalize_language, text
from core.ui_language_dashboard import DASHBOARD_TRANSLATIONS
from core.ui_language_detail import DETAIL_TRANSLATIONS
from core.ui_language_extra import EXTRA_TRANSLATIONS
from core.ui_language_pages import PAGE_TRANSLATIONS

register = template.Library()


CATALOGS = (
    DETAIL_TRANSLATIONS,
    DASHBOARD_TRANSLATIONS,
    EXTRA_TRANSLATIONS,
    PAGE_TRANSLATIONS,
)


@register.simple_tag(takes_context=True)
def t(context, key: str) -> str:
    """Return one translated UI string for the active interface language.

    Catalog entries are authored in this repository and may contain small
    pieces of markup such as ``<br>``, so they are returned as safe strings
    the same way Django treats ``{% translate %}`` output.
    """

    language = normalize_language(context.get("ui_language", DEFAULT_LANGUAGE))
    normalized_key = str(key)
    for catalog in CATALOGS:
        if normalized_key in catalog.get(language, {}):
            return mark_safe(catalog[language][normalized_key])
    return mark_safe(text(language, normalized_key))
