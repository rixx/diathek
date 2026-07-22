import factory

from diathek.core.models import (
    Box,
    DriverState,
    Image,
    ImmichEditSession,
    InviteCode,
    Place,
    User,
)


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User

    username = factory.Sequence(lambda n: f"user{n}")
    name = factory.Sequence(lambda n: f"User {n}")

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        password = kwargs.pop("password", "s3cret-pass-phrase")
        user = model_class(*args, **kwargs)
        user.set_password(password)
        user.save()
        return user


class InviteCodeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = InviteCode

    username = factory.Sequence(lambda n: f"invitee{n}")
    name = factory.Sequence(lambda n: f"Invitee {n}")


class PlaceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Place

    name = factory.Sequence(lambda n: f"Place {n}")


class BoxFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Box

    name = factory.Sequence(lambda n: f"Box {n}")


class ImageFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Image
        skip_postgeneration_save = True

    box = factory.SubFactory(BoxFactory)
    filename = factory.Sequence(lambda n: f"scan_{n:04d}.jpg")
    sequence_in_box = factory.Sequence(lambda n: n + 1)

    @factory.post_generation
    def immich_uploaded(self, create, extracted, **kwargs):
        """Mark the image as already uploaded and current in Immich.

        Use ``ImageFactory(..., immich_uploaded=True)`` so the parent box is
        ``immich_complete`` (asset id set and signature matches the current
        metadata).
        """
        if not extracted:
            return
        self.immich_asset_id = f"asset-{self.uuid}"
        self.immich_signature = self.compute_immich_signature()
        if create:
            self.save(skip_log=True, bump_version=False)


class DriverStateFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = DriverState
        django_get_or_create = ("pk",)

    pk = 1


class ImmichEditSessionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ImmichEditSession

    user = factory.SubFactory(UserFactory, immich_api_key="api-key-123")
    data = factory.LazyFunction(list)
