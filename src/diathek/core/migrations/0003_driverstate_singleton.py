from django.db import migrations


def create_singleton(apps, schema_editor):
    DriverState = apps.get_model("core", "DriverState")
    DriverState.objects.get_or_create(pk=1)


def remove_singleton(apps, schema_editor):
    DriverState = apps.get_model("core", "DriverState")
    DriverState.objects.filter(pk=1).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0002_box_place_image_driverstate_collection_auditlog_and_more")
    ]

    operations = [migrations.RunPython(create_singleton, remove_singleton)]
