from django.urls import path

from diathek.core import views

urlpatterns = [
    path("", views.index, name="index"),
    path("import/", views.import_view, name="import"),
    path("unsorted/", views.unsorted_view, name="unsorted"),
    path("unsorted/assign/", views.unsorted_assign, name="unsorted_assign"),
    path("register/<str:code>/", views.register, name="register"),
    path(
        "box/<uuid:box_uuid>/<int:image_id>/", views.image_detail, name="image_detail"
    ),
    path("api/image/<int:image_id>/", views.image_save, name="image_save"),
    path(
        "api/image/<int:image_id>/fragment/",
        views.image_fragment,
        name="image_fragment",
    ),
]
