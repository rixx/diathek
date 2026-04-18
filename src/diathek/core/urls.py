from django.urls import path

from diathek.core import views

urlpatterns = [path("register/<str:code>/", views.register, name="register")]
