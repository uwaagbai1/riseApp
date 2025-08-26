from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from accounts.views.base import (
    handler400 as custom_handler400,
    handler403 as custom_handler403,
    handler404 as custom_handler404,
    handler500 as custom_handler500
)

handler400 = custom_handler400
handler403 = custom_handler403
handler404 = custom_handler404
handler500 = custom_handler500

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('main.urls')),
    path('portal/', include('accounts.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
