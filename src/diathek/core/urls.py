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
    path("box/<uuid:box_uuid>/grid/", views.box_grid, name="box_grid"),
    path("galerie/", views.gallery, name="gallery"),
    path("box/<uuid:box_uuid>/archiv/", views.box_archive, name="box_archive"),
    path("orte/", views.place_list, name="place_list"),
    path("orte/<int:pk>/", views.place_set_coords, name="place_set_coords"),
    path("sammlungen/", views.collection_list, name="collection_list"),
    path("sammlung/neu/", views.collection_edit, name="collection_create"),
    path("sammlung/<int:pk>/", views.collection_detail, name="collection_detail"),
    path(
        "sammlung/<int:pk>/bearbeiten/", views.collection_edit, name="collection_edit"
    ),
    path("deploy/", views.trigger_deploy, name="deploy"),
    path("healthz/", views.healthz, name="healthz"),
    path("api/batch/", views.image_batch, name="image_batch"),
    path("api/image/<int:image_id>/", views.image_save, name="image_save"),
    path(
        "api/image/<int:image_id>/fragment/",
        views.image_fragment,
        name="image_fragment",
    ),
    path(
        "api/autocomplete/place/", views.place_autocomplete, name="place_autocomplete"
    ),
    path("api/autocomplete/date/", views.date_autocomplete, name="date_autocomplete"),
    path("api/state/", views.state, name="state"),
    path("api/driver/", views.driver_state, name="driver_state"),
    path("api/upload/", views.api_upload, name="api_upload"),
]
