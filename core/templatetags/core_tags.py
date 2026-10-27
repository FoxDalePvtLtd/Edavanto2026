"""
Core custom template filters and tags for Edvanto student learning.
"""

from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """
    Safely retrieve an item from a dictionary by key.
    Usage: {{ progress_by_lesson|get_item:lesson.id }}
    """
    if not isinstance(dictionary, dict):
        return None
    return dictionary.get(key)


@register.filter
def format_seconds(seconds):
    """
    Format positive seconds into human-readable duration (e.g. 12:45 or 1h 15m).
    """
    if not seconds:
        return ""
    try:
        total = int(seconds)
    except (TypeError, ValueError):
        return ""

    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60

    if hours > 0:
        return f"{hours}h {minutes}m"
    if minutes > 0:
        return f"{minutes}m {secs}s"
    return f"{secs}s"
