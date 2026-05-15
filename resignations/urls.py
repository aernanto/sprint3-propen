from django.urls import path

from .views import ResignationCreateView, ResignationMeView, ResignationSettlementView

urlpatterns = [
    path('', ResignationCreateView.as_view(), name='resignation-create'),
    path('settlement/', ResignationSettlementView.as_view(), name='resignation-settlement'),
    path('me/', ResignationMeView.as_view(), name='resignation-me'),
]
