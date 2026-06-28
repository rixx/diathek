from django.urls import path

from diathek.core.api import views

app_name = "api"

urlpatterns = [
    path("images/", views.ImageListView.as_view(), name="image-list"),
    path("images/<int:pk>/", views.ImageDetailView.as_view(), name="image-detail"),
    path("places/", views.PlaceListView.as_view(), name="place-list"),
]
