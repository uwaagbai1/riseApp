from django import template
from accounts.constants import TERM_CHOICES

register = template.Library()

@register.filter
def get_item(dictionary, key):
    """
    Custom filter to get an item from a dictionary by key.
    Returns None if the key doesn't exist.
    """
    return dictionary.get(key)

@register.filter
def result_field(results, subject_id, field):
    result = results.filter(subject_id=subject_id).first()
    return getattr(result, field, '') if result else ''

@register.filter
def get_term_display(term):
    term_dict = dict(TERM_CHOICES)
    return term_dict.get(term, term)

@register.filter
def lookup(dictionary, key):
    return dictionary.get(key)

@register.filter
def filter(queryset, arg):
    key, value = arg.split(':')
    return queryset.filter(**{key: value}).first()

@register.filter
def ordinal_suffix(value):
    try:
        value = int(value)
        if 11 <= (value % 100) <= 13:
            return 'th'
        return {1: 'st', 2: 'nd', 3: 'rd'}.get(value % 10, 'th')
    except (ValueError, TypeError):
        return ''
        
