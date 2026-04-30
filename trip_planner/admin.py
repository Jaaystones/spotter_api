from django.contrib import admin

from .models import EldLogSheet


@admin.register(EldLogSheet)
class EldLogSheetAdmin(admin.ModelAdmin):
	list_display = ('id', 'created_at')
	readonly_fields = ('created_at', 'payload')
