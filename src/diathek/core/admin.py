from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.forms import UserCreationForm
from django.utils.html import format_html

from diathek.core.models import (
    AuditLog,
    Box,
    Collection,
    DriverState,
    Image,
    InviteCode,
    Place,
    User,
)


class DiathekUserCreationForm(UserCreationForm):
    class Meta:
        model = User
        fields = ("username", "name")


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    add_form = DiathekUserCreationForm
    list_display = ("username", "name", "is_staff", "is_active", "last_poll")
    search_fields = ("username", "name")
    ordering = ("username",)
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Personal", {"fields": ("name",)}),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        ("Important dates", {"fields": ("last_login", "last_poll")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("username", "name", "password1", "password2"),
            },
        ),
    )


@admin.register(InviteCode)
class InviteCodeAdmin(admin.ModelAdmin):
    list_filter = ("used_by",)
    search_fields = ("username", "name", "code")
    readonly_fields = ("code", "created_by", "created_at", "used_by", "used_at")
    fields = (
        "username",
        "name",
        "expires_at",
        "code",
        "created_by",
        "created_at",
        "used_by",
        "used_at",
    )

    def get_list_display(self, request):
        def invite_url(obj):
            url = request.build_absolute_uri(obj.get_absolute_url())
            return format_html('<a href="{0}">{0}</a>', url)

        invite_url.short_description = "Einladungslink"
        return ("username", "name", invite_url, "expires_at", "used_by", "used_at")

    def save_model(self, request, obj, form, change):
        if not change and obj.created_by_id is None:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(Box)
class BoxAdmin(admin.ModelAdmin):
    list_display = ("name", "sort_order", "archived", "archived_at", "created_at")
    list_filter = ("archived",)
    search_fields = ("name", "description")
    readonly_fields = ("uuid", "created_at", "updated_at", "archived_at")


@admin.register(Image)
class ImageAdmin(admin.ModelAdmin):
    list_display = (
        "filename",
        "box",
        "sequence_in_box",
        "place",
        "date_display",
        "version",
    )
    list_filter = ("box", "place_todo", "date_todo", "needs_flip")
    search_fields = ("filename", "description", "date_display")
    readonly_fields = (
        "uuid",
        "content_hash",
        "file_size",
        "width",
        "height",
        "version",
        "created_at",
        "updated_at",
    )


@admin.register(Place)
class PlaceAdmin(admin.ModelAdmin):
    list_display = ("name", "latitude", "longitude")
    search_fields = ("name",)


@admin.register(Collection)
class CollectionAdmin(admin.ModelAdmin):
    list_display = ("title", "immich_url", "created_at")
    search_fields = ("title", "description")
    filter_horizontal = ("boxes",)


@admin.register(DriverState)
class DriverStateAdmin(admin.ModelAdmin):
    list_display = ("driver", "current_box", "current_image", "updated_at")
    readonly_fields = ("created_at", "updated_at")


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "action_type", "user", "box", "content_type")
    list_filter = ("action_type", "content_type")
    search_fields = ("action_type",)
    readonly_fields = (
        "content_type",
        "object_id",
        "box",
        "action_type",
        "user",
        "timestamp",
        "data",
    )
