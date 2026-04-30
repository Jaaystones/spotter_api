from django.db import models


class EldLogSheet(models.Model):
	created_at = models.DateTimeField(auto_now_add=True)
	payload = models.JSONField(default=dict)

	class Meta:
		ordering = ['-created_at']

	def __str__(self):
		return f'EldLogSheet #{self.pk}'
