from django import template

register = template.Library()


@register.filter
def csv_contains(csv_string, needle):
    """
    Returns True if `needle` is one of the comma-separated values in
    `csv_string`. Usage:

        {% if url_name|csv_contains:"user_list,user_form" %}
    """
    if not csv_string or not needle:
        return False
    return str(needle) in {part.strip() for part in str(csv_string).split(",")}