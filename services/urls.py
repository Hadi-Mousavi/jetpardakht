from django.urls import path

from . import views

# The built-in <slug:slug> converter matches [-a-zA-Z0-9_]+ (ASCII only).
# Service.slug is guaranteed to be ASCII-only by the model's save() method,
# so every service URL is resolvable regardless of its Persian display name.
urlpatterns = [
    path('',                          views.service_catalog,      name='service_catalog'),
    path('<slug:slug>/',              views.service_order,        name='service_order'),
    path('files/<int:pk>/download/',  views.field_value_download, name='field_value_download'),
]
