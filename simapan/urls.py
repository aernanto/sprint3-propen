from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from members.views import MemberDashboardView

urlpatterns = [
    path('admin/', admin.site.urls),

    # Auth & members
    path('api/auth/', include('users.urls')),
    path('api/members/', include('members.urls')),
    path('api/auth/password/', include('members.password_reset_urls')),

    # Dashboards
    path('api/dashboards/', include('members.dashboard_urls')),
    path('api/dashboards/member/', MemberDashboardView.as_view()),

    # Staff
    path('api/staff/members/', include('members.staff_urls')),
    path('api/staff/withdrawals/', include('savings.staff_urls')),
    path('api/staff/loans/', include('loans.staff_urls')),
    path('api/staff/installments/', include('loans.staff_installment_urls')),
    path('api/staff/refunds/', include('refunds.urls')),
    path('api/manager/loans/', include('loans.manager_urls')),
    path('api/chairman/', include('loans.chairman_urls')),
    path('api/manager/resignations/', include('resignations.manager_urls')),

    # Core features
    path('api/savings/', include('savings.urls')),
    path('api/notifications/', include('notifications.urls')),
    path('api/verifications/', include('verifications.urls')),
    path('api/config/', include('config.urls')),
    path('api/loans/', include('loans.urls')),
    path('api/installments/', include('loans.pay_urls')),
    path('api/resignations/', include('resignations.urls')),
    path('api/manager/resignations/', include('resignations.manager_urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
