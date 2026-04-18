from django.contrib.auth import login
from django.shortcuts import get_object_or_404, redirect, render

from diathek.core.forms import RegistrationForm
from diathek.core.models import InviteCode


def register(request, code):
    invite = get_object_or_404(InviteCode, code=code)
    if not invite.is_valid:
        return render(
            request, "core/register_invalid.html", {"invite": invite}, status=410
        )

    if request.method == "POST":
        form = RegistrationForm(request.POST, invite=invite)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect("/")
    else:
        form = RegistrationForm(invite=invite)
    return render(request, "core/register.html", {"form": form, "invite": invite})
