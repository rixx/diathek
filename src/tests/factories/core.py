import factory

from diathek.core.models import InviteCode, User


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
