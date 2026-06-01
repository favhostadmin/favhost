from django import template

register = template.Library()

@register.filter(name='filtered_by_type')
def filtered_by_type(queryset, doc_type):
    """
    Filters a queryset of PropertyDocument objects by their document_type.
    """
    return queryset.filter(document_type=doc_type)