
# Register your models here.
from django.contrib import admin
from django.utils.html import format_html
import os
from .models import Technician, ServiceRequest

@admin.register(Technician)
class TechnicianAdmin(admin.ModelAdmin):
    list_display = ['name', 'email', 'skill', 'home_address', 'service_areas', 'has_experience_certificate', 'idproof_link', 'experience_certificate_link', 'is_approved', 'is_active']
    list_filter = ['skill', 'is_approved', 'is_active']

    def has_experience_certificate(self, obj):
        return bool(obj.experience_certificate)
    has_experience_certificate.boolean = True
    has_experience_certificate.short_description = 'Has Certificate'
    search_fields = ['name', 'email', 'phone']
    readonly_fields = ['user', 'idproof', 'experience_certificate']
    fields = ['user', 'name', 'email', 'phone', 'skill', 'address', 'service_locations', 'experience_years', 'idproof', 'experience_certificate', 'photo', 'is_approved', 'is_active', 'discount_percent', 'discount_valid_until']

    def home_address(self, obj):
        return obj.address if obj.address else 'Not provided'
    home_address.short_description = 'Home Address'

    def service_areas(self, obj):
        return obj.service_locations if obj.service_locations else 'Not specified'
    service_areas.short_description = 'Service Areas'

    def idproof_link(self, obj):
        if obj.idproof:
            return format_html('<a href="{}" target="_blank">View</a>', obj.idproof.url)
        return 'No ID proof'
    idproof_link.short_description = 'ID Proof'

    def experience_certificate_link(self, obj):
        if obj.experience_certificate:
            url = obj.experience_certificate.url
            name = os.path.basename(obj.experience_certificate.name)
            lower = name.lower()
            # If the certificate is an image, show a small thumbnail plus filename link
            if lower.endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
                return format_html(
                    '<a href="{url}" target="_blank"><img src="{url}" style="width:64px;height:auto;display:block;margin-bottom:4px;border-radius:4px;"/></a><a href="{url}" target="_blank">{name}</a>',
                    url=url, name=name
                )
            # Otherwise show a filename link
            return format_html('<a href="{}" target="_blank">{}</a>', url, name)
        return 'No Certificate'
    experience_certificate_link.short_description = 'Experience Certificate'

admin.site.register(ServiceRequest)

