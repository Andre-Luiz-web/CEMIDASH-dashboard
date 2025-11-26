from __future__ import annotations

from typing import Any

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import Group
from django.utils.translation import gettext_lazy as _

from .models import Turma
from .models import ProfessorProfile


class PlanilhaUploadForm(forms.Form):
    arquivo = forms.FileField(
        label=_("Planilha (.xlsx)"),
        help_text=_("Envie arquivos Excel no formato .xlsx para atualizar os dados do dashboard."),
        allow_empty_file=False,
        widget=forms.ClearableFileInput(attrs={"accept": ".xlsx", "class": "input"}),
    )

    def clean_arquivo(self) -> Any:
        arquivo = self.cleaned_data["arquivo"]
        if arquivo and not arquivo.name.lower().endswith(".xlsx"):
            raise forms.ValidationError(_("Apenas arquivos .xlsx são suportados."))
        return arquivo


class ProfessorCreationForm(UserCreationForm):
    first_name = forms.CharField(label=_("Nome"), max_length=150)
    last_name = forms.CharField(label=_("Sobrenome"), max_length=150)
    email = forms.EmailField(label=_("E-mail institucional"))
    turmas = forms.ModelMultipleChoiceField(
        label=_("Turmas que o professor poderá visualizar"),
        queryset=Turma.objects.none(),
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ("username", "first_name", "last_name", "email")

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        turmas_queryset = kwargs.pop("turmas_queryset", None)
        super().__init__(*args, **kwargs)
        self.fields["username"].label = _("Usuário (sem espaços)")
        self.fields["password1"].label = _("Senha")
        self.fields["password2"].label = _("Confirmação da senha")
        if turmas_queryset is None:
            turmas_queryset = Turma.objects.order_by("nome")
        self.fields["turmas"].queryset = turmas_queryset
        for field_name in ["username", "password1", "password2", "first_name", "last_name", "email"]:
            field = self.fields[field_name]
            field.widget.attrs.update({"class": "input"})

    def save(self, commit: bool = True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        if commit:
            user.save()
            professor_group, _ = Group.objects.get_or_create(name="Professores")
            user.groups.add(professor_group)
        return user


class UserProfileForm(forms.ModelForm):
    class Meta:
        model = get_user_model()
        fields = ("first_name", "last_name", "email")
        labels = {
            "first_name": _("Nome"),
            "last_name": _("Sobrenome"),
            "email": _("E-mail institucional"),
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({"class": "input"})


class ProfessorProfileForm(forms.ModelForm):
    avatar = forms.ImageField(
        label=_("Foto (opcional)"),
        required=False,
        widget=forms.FileInput(attrs={"class": "input"}),
    )

    class Meta:
        model = ProfessorProfile
        fields = ("avatar",)
