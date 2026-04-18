import factory

from diathek.core.models import (
    Box,
    Collection,
    DriverState,
    Image,
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

    box = factory.SubFactory(BoxFactory)
    filename = factory.Sequence(lambda n: f"scan_{n:04d}.jpg")
    sequence_in_box = factory.Sequence(lambda n: n + 1)


class CollectionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Collection

    title = factory.Sequence(lambda n: f"Collection {n}")


class DriverStateFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = DriverState
        django_get_or_create = ("pk",)

    pk = 1
