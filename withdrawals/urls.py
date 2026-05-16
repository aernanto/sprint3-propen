from django.urls import path

from .views import WithdrawalCreateView, WithdrawalMeView

urlpatterns = [
    path('', WithdrawalCreateView.as_view(), name='withdrawal-create'),
    path('me/', WithdrawalMeView.as_view(), name='withdrawal-me'),
]
