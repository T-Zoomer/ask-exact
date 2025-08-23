from django.contrib import admin
from .models import ExactOnlineToken, ExactOnlineAuthState


@admin.register(ExactOnlineToken)
class ExactOnlineTokenAdmin(admin.ModelAdmin):
    list_display = ['session_key', 'expires_at', 'is_expired_display', 'created_at']
    list_filter = ['created_at', 'expires_at']
    search_fields = ['session_key']
    readonly_fields = ['created_at', 'updated_at', 'is_expired_display', 'expires_soon_display']
    
    def is_expired_display(self, obj):
        return obj.is_expired()
    is_expired_display.boolean = True
    is_expired_display.short_description = 'Expired'
    
    def expires_soon_display(self, obj):
        return obj.expires_soon()
    expires_soon_display.boolean = True
    expires_soon_display.short_description = 'Expires Soon'
    
    fieldsets = (
        ('Token Information', {
            'fields': ('session_key', 'token_type')
        }),
        ('Expiration', {
            'fields': ('expires_at', 'is_expired_display', 'expires_soon_display')
        }),
        ('API Information', {
            'fields': ('division', 'base_server_uri'),
            'classes': ('collapse',)
        }),
        ('Token Data', {
            'fields': ('access_token', 'refresh_token'),
            'classes': ('collapse',),
            'description': 'Sensitive information - handle with care'
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(ExactOnlineAuthState)
class ExactOnlineAuthStateAdmin(admin.ModelAdmin):
    list_display = ['session_key', 'state', 'is_used', 'is_valid_display', 'created_at']
    list_filter = ['is_used', 'created_at']
    search_fields = ['session_key', 'state']
    readonly_fields = ['created_at', 'is_valid_display']
    
    def is_valid_display(self, obj):
        return obj.is_valid()
    is_valid_display.boolean = True
    is_valid_display.short_description = 'Valid'
    
    fieldsets = (
        ('OAuth State', {
            'fields': ('session_key', 'state', 'is_used', 'is_valid_display')
        }),
        ('Timestamps', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )
