from django import template

from core.ui_language import DEFAULT_LANGUAGE, text

register = template.Library()


@register.simple_tag(takes_context=True)
def t(context, key: str) -> str:
    """Return one translated UI string for the active session language."""

    return text(str(context.get("ui_language", DEFAULT_LANGUAGE)), str(key))
