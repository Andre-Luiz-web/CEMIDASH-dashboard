from django.contrib import admin

from .models import ProfessorProfile, Turma


@admin.register(Turma)
class TurmaAdmin(admin.ModelAdmin):
    list_display = ("nome", "criado_em")
    search_fields = ("nome",)
    ordering = ("nome",)


@admin.register(ProfessorProfile)
class ProfessorProfileAdmin(admin.ModelAdmin):
    list_display = ("usuario", "lista_turmas", "criado_em")
    search_fields = ("usuario__username", "usuario__first_name", "usuario__last_name")
    filter_horizontal = ("turmas",)

    @admin.display(description="turmas")
    def lista_turmas(self, obj: ProfessorProfile) -> str:
        return ", ".join(obj.turmas.values_list("nome", flat=True))
