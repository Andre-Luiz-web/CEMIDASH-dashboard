from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class Turma(models.Model):
    nome = models.CharField(_("nome"), max_length=255, unique=True)
    criado_em = models.DateTimeField(_("criado em"), auto_now_add=True)

    class Meta:
        ordering = ["nome"]
        verbose_name = _("turma")
        verbose_name_plural = _("turmas")

    def __str__(self) -> str:
        return self.nome


class ProfessorProfile(models.Model):
    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="perfil_professor",
        verbose_name=_("usuário"),
    )
    turmas = models.ManyToManyField(Turma, related_name="professores", verbose_name=_("turmas"))
    avatar = models.ImageField(
        _("foto de perfil"),
        upload_to="avatars/",
        blank=True,
        null=True,
    )
    criado_em = models.DateTimeField(_("criado em"), auto_now_add=True)

    class Meta:
        verbose_name = _("perfil de professor")
        verbose_name_plural = _("perfis de professor")

    def __str__(self) -> str:
        return f"Professor {self.usuario.get_full_name() or self.usuario.username}"
