from django import template

register = template.Library()

@register.filter
def dict_get(dictionary, key):
    return dictionary.get(key)

@register.filter
def is_empty(result):
    if not result:
        return True
    if hasattr(result, 'nursery_primary_exam'):  # Nursery/Primary
        return (
            result.test == 0 and
            result.homework == 0 and
            result.classwork == 0 and
            result.nursery_primary_exam == 0
        )
    else:  # Junior/Senior
        return (
            result.ca == 0 and
            result.test_1 == 0 and
            result.test_2 == 0 and
            result.exam == 0
        )