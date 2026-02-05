from django import template
from django.db.models import Avg
from django.utils.safestring import mark_safe

register = template.Library()

@register.filter
def average_rating(technician):
    avg = technician.ratings.aggregate(avg=Avg('stars'))['avg']
    return avg or 0


@register.filter(name='add_class')
def add_class(bound_field, css_class):
    """Adds a CSS class to a BoundField's widget when rendering from templates.

    Usage in templates: {{ form.field|add_class:"form-control" }}
    """
    try:
        return bound_field.as_widget(attrs={"class": css_class})
    except Exception:
        return bound_field


@register.filter(name='is_image')
def is_image(file_field):
    """Return True if the uploaded file has an image extension."""
    if not file_field:
        return False
    try:
        import os
        ext = os.path.splitext(file_field.name)[1].lower()
        return ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg']
    except Exception:
        return False


@register.filter(name='file_exists')
def file_exists(file_field):
    """Return True if the uploaded file exists in storage."""
    if not file_field:
        return False
    try:
        return file_field.storage.exists(file_field.name)
    except Exception:
        return False


@register.filter(name='is_pdf')
def is_pdf(file_field):
    """Return True if the uploaded file is a PDF (by extension)."""
    if not file_field:
        return False
    try:
        import os
        ext = os.path.splitext(file_field.name)[1].lower()
        return ext == '.pdf'
    except Exception:
        return False


@register.filter(name='basename')
def basename(file_field):
    """Return the filename portion of a FileField or file path."""
    if not file_field:
        return ''
    try:
        import os
        return os.path.basename(file_field.name)
    except Exception:
        return ''
