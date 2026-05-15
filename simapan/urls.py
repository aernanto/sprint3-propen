"""
URL configuration for simapan project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/auth/', include('users.urls')),
    path('api/members/', include('members.urls')),
    path('api/staff/members/', include('members.staff_urls')),
    path('api/staff/loans/', include('loans.staff_urls')),
    path('api/staff/installments/', include('loans.staff_installment_urls')),
    path('api/manager/loans/', include('loans.manager_urls')),
    path('api/savings/', include('savings.urls')),
    path('api/notifications/', include('notifications.urls')),
    path('api/verifications/', include('verifications.urls')),
    path('api/config/', include('config.urls')),
    path('api/loans/', include('loans.urls')),
    path('api/installments/', include('loans.pay_urls')),
    path('api/auth/password/', include('members.password_reset_urls')),
    path('api/resignations/', include('resignations.urls')),
    path('api/manager/resignations/', include('resignations.manager_urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    