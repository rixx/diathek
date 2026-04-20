from django.contrib.auth.models import (
    AbstractBaseUser,
    BaseUserManager,
    PermissionsMixin,
)
from django.db import models


class UserManager(BaseUserManager):
    def create_user(self, username, name=None, password=None, **extra_fields):
        if not username:
            raise ValueError("username is required")
        user = self.model(username=username, name=name or username, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, username, password, name=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("can_upload", True)
        return self.create_user(
            username=username, name=name, password=password, **extra_fields
        )


class User(AbstractBaseUser, PermissionsMixin):
    username = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    can_upload = models.BooleanField(default=False)
    last_poll = models.DateTimeField(null=True, blank=True, db_index=True)

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = ["name"]

    objects = UserManager()

    def __str__(self):
        return self.name or self.username

    def get_full_name(self):
        return self.name

    def get_short_name(self):
        return self.name
