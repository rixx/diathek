from django.urls import path

from diathek.core import views

urlpatterns = [
    path("", views.index, name="index"),
    path("import/", views.import_view, name="import"),
    path("unsorted/", views.unsorted_view, name="unsorted"),
    path("unsorted/assign/", views.unsorted_assign, name="unsorted_assign"),
    path("register/<str:code>/", views.register, name="register"),
]
