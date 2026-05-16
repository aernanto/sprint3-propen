from django.db import models
from users.models import User


class Notification(models.Model):
    TYPE_CHOICES = [
        ('REGISTRATION', 'Registration'),
        ('SAVING',       'Saving'),
        ('LOAN',         'Loan'),
        ('RESIGNATION',  'Resignation'),
        ('GENERAL',      'General'),
    ]

    recipient    = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    type         = models.CharField(max_length=20, choices=TYPE_CHOICES, default='GENERAL')
    title        = models.CharField(max_length=255)
    message      = models.TextField()
    is_read      = models.BooleanField(default=False)
    redirect_url = models.CharField(max_length=255, blank=True)  # e.g. /dashboard/member/loans/3
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'[{self.type}] {self.title} → {self.recipient.email}'