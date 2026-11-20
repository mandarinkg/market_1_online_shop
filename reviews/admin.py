# reviews/admin.py

from django.contrib import admin
from .models import Review


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display    = ('user', 'product', 'rating', 'verified_purchase', 'is_active', 'created_at')
    list_filter     = ('rating', 'is_active', 'verified_purchase')
    search_fields   = ('user__username', 'product__title', 'text')
    readonly_fields = ('created_at', 'updated_at', 'verified_purchase')
    actions         = ['activate', 'deactivate']

    def activate(self, request, queryset):
        queryset.update(is_active=True)
    activate.short_description = '✅ Активировать отзывы'

    def deactivate(self, request, queryset):
        queryset.update(is_active=False)
    deactivate.short_description = '❌ Деактивировать отзывы'