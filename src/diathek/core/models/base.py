import datetime
import decimal
import uuid

from django.db import models


class BaseModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    log_action_prefix = None
    log_tracked_fields = ()

    class Meta:
        abstract = True

    def save(self, *args, user=None, skip_log=False, **kwargs):
        is_new = self._state.adding
        before = {} if is_new else self._previous_snapshot()
        super().save(*args, **kwargs)
        if skip_log or self.log_action_prefix is None:
            return
        after = self._snapshot()
        if is_new:
            self.log_action(
                f"{self.log_action_prefix}.create", user=user, before={}, after=after
            )
            return
        changes = [key for key in after if before.get(key) != after.get(key)]
        if not changes:
            return
        self.log_action(
            f"{self.log_action_prefix}.change",
            user=user,
            before={key: before.get(key) for key in changes},
            after={key: after[key] for key in changes},
        )

    def delete(self, *args, user=None, skip_log=False, **kwargs):
        should_log = not skip_log and self.log_action_prefix is not None
        if should_log:
            self.log_action(
                f"{self.log_action_prefix}.delete",
                user=user,
                before=self._snapshot(),
                after={},
            )
        return super().delete(*args, **kwargs)

    def _get_log_box_id(self):
        return None

    @staticmethod
    def _serialize_value(value):
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, datetime.datetime):
            return value.isoformat()
        if isinstance(value, datetime.date):
            return value.isoformat()
        if isinstance(value, uuid.UUID):
            return str(value)
        if isinstance(value, decimal.Decimal):
            return str(value.normalize())
        if isinstance(value, (int, float, str)):
            return value
        return str(value)

    def _snapshot(self):
        data = {}
        for field_name in self.log_tracked_fields:
            field = self._meta.get_field(field_name)
            if isinstance(field, models.ForeignKey):
                data[field_name] = getattr(self, field.attname)
            else:
                data[field_name] = self._serialize_value(getattr(self, field_name))
        return data

    def _previous_snapshot(self):
        if self.pk is None:
            return {}
        try:
            previous = self.__class__.objects.get(pk=self.pk)
        except self.__class__.DoesNotExist:
            return {}
        return previous._snapshot()

    def log_action(self, action_type, *, user=None, before=None, after=None, data=None):
        from diathek.core.models.auditlog import AuditLog

        payload = dict(data or {})
        if before is not None:
            payload["before"] = before
        if after is not None:
            payload["after"] = after
        return AuditLog.objects.create(
            content_object=self,
            box_id=self._get_log_box_id(),
            action_type=action_type,
            user=user,
            data=payload,
        )
