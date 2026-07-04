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
    path("box/<uuid:box_uuid>/download/", views.box_download, name="box_download"),
    path("galerie/", views.gallery, name="gallery"),
    path("box/neu/", views.box_edit, name="box_create"),
    path("box/<uuid:box_uuid>/bearbeiten/", views.box_edit, name="box_edit"),
    path("box/<uuid:box_uuid>/archiv/", views.box_archive, name="box_archive"),
    path(
        "box/<uuid:box_uuid>/immich/",
        views.box_immich_finalize,
        name="box_immich_finalize",
    ),
    path(
        "box/<uuid:box_uuid>/immich/status/",
        views.box_immich_status,
        name="box_immich_status",
    ),
    path(
        "box/<uuid:box_uuid>/immich/erneut/",
        views.box_immich_retry,
        name="box_immich_retry",
    ),
    path("orte/", views.place_list, name="place_list"),
    path("orte/<int:pk>/", views.place_set_coords, name="place_set_coords"),
    path("konto/", views.account_settings, name="account_settings"),
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
        "api/image/<int:image_id>/immich/",
        views.image_apply_immich,
        name="image_apply_immich",
    ),
    path(
        "api/autocomplete/place/", views.place_autocomplete, name="place_autocomplete"
    ),
    path("api/autocomplete/date/", views.date_autocomplete, name="date_autocomplete"),
    path("api/state/", views.state, name="state"),
    path("api/driver/", views.driver_state, name="driver_state"),
    path("api/upload/", views.api_upload, name="api_upload"),
    path("api/upload/prepare/", views.upload_prepare, name="upload_prepare"),
]
