from django import template
from django.core.exceptions import ObjectDoesNotExist


register = template.Library()


@register.simple_tag(takes_context=True)
def querystring(context, **kwargs) -> str:
    """
    Helper to build query strings while preserving existing parameters.
    Passing None removes a parameter (useful to reset pagination).
    """
    request = context.get("request")
    if request is None:
        return ""

    query = request.GET.copy()
    for key, value in kwargs.items():
        if value is None:
            query.pop(key, None)
        else:
            query[key] = value
    return query.urlencode()


@register.filter
def professor_profile(user):
    if not getattr(user, "is_authenticated", False):
        return None
    try:
        return user.perfil_professor
    except ObjectDoesNotExist:
        return None
