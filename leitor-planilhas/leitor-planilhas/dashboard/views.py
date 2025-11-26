from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from statistics import StatisticsError
from typing import Any, Dict, Iterable, List
from zipfile import BadZipFile

import statistics
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.views import LoginView
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views.generic import TemplateView
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from .forms import (
    PlanilhaUploadForm,
    ProfessorCreationForm,
    ProfessorProfileForm,
    UserProfileForm,
)
from .models import ProfessorProfile, Turma
from .services import ensure_turmas_sincronizadas, invalidate_dataset_cache, load_dataset


STATUS_PROFILES = [
    {
        "id": "critico",
        "label": "Crítico",
        "range": "Abaixo de 2,00",
        "min": None,
        "max": 2.0,
        "color": "#ef4444",
        "bg": "#fee2e2",
        "icon": "alert-triangle",
    },
    {
        "id": "atencao",
        "label": "Atenção",
        "range": "Entre 2,00 e 5,00",
        "min": 2.0,
        "max": 5.0,
        "color": "#f59e0b",
        "bg": "#fef3c7",
        "icon": "alert-circle",
    },
    {
        "id": "bom",
        "label": "Bom",
        "range": "Entre 5,00 e 7,00",
        "min": 5.0,
        "max": 7.0,
        "color": "#22c55e",
        "bg": "#dcfce7",
        "icon": "check-circle",
    },
    {
        "id": "otimo",
        "label": "Ótimo",
        "range": "Entre 7,00 e 9,00",
        "min": 7.0,
        "max": 9.0,
        "color": "#3b82f6",
        "bg": "#dbeafe",
        "icon": "sparkles",
    },
    {
        "id": "excelente",
        "label": "Excelente",
        "range": "Acima de 9,00",
        "min": 9.0,
        "max": None,
        "color": "#1e3a8a",
        "bg": "#c7d2fe",
        "icon": "shield-check",
    },
]


COORDINATOR_GROUP = "Coordenadores"
PROFESSOR_GROUP = "Professores"

STUDENTS_PER_PAGE = 50
DEFAULT_SORT_FIELD = "nota"
DEFAULT_SORT_DIRECTION = "desc"

STUDENT_SORT_FIELDS = {
    "turma": lambda student: (student.get("turma") or "").lower(),
    "nome": lambda student: (student.get("nome") or "").lower(),
    "nota": lambda student: float(student.get("nota") or 0.0),
    "percentual_nota": lambda student: float(student.get("percentual_nota") or 0.0),
    "acertos": lambda student: int(student.get("acertos") or 0),
    "percentual_acertos": lambda student: float(student.get("percentual_acertos") or 0.0),
    "arquivo": lambda student: (student.get("arquivo") or "").lower(),
    "status": lambda student: (student.get("status", {}).get("label") or "").lower(),
}

STUDENT_HEADER_LABELS = {
    "turma": _("Turma"),
    "nome": _("Aluno"),
    "nota": _("Nota"),
    "percentual_nota": _("% Nota"),
    "acertos": _("Acertos"),
    "percentual_acertos": _("% Acerto"),
    "arquivo": _("Planilha"),
    "status": _("Status"),
}


def _usuario_eh_coordenador(user) -> bool:
    if not user.is_authenticated:
        return False
    return user.is_superuser or user.groups.filter(name=COORDINATOR_GROUP).exists()


def _turmas_permitidas_para_usuario(user, turmas_dataset: Iterable[str]) -> List[str]:
    if not user.is_authenticated:
        return []
    if _usuario_eh_coordenador(user):
        return list(turmas_dataset)
    try:
        perfil = user.perfil_professor
    except ProfessorProfile.DoesNotExist:
        return []
    return list(perfil.turmas.values_list("nome", flat=True))


def _preparar_tabela_estudantes(
    request: HttpRequest,
    estudantes: List[Dict[str, Any]],
    colunas: List[str],
    default_sort: str = DEFAULT_SORT_FIELD,
) -> Dict[str, Any]:
    sort_field = request.GET.get("sort") or default_sort
    if sort_field not in STUDENT_SORT_FIELDS or sort_field not in colunas:
        sort_field = default_sort if default_sort in colunas else colunas[0]

    sort_direction = request.GET.get("direction") or DEFAULT_SORT_DIRECTION
    if sort_direction not in ("asc", "desc"):
        sort_direction = DEFAULT_SORT_DIRECTION

    key_fn = STUDENT_SORT_FIELDS.get(sort_field, STUDENT_SORT_FIELDS[DEFAULT_SORT_FIELD])
    estudantes_ordenados = sorted(estudantes, key=key_fn, reverse=(sort_direction == "desc"))

    paginator = Paginator(estudantes_ordenados, STUDENTS_PER_PAGE)
    page_number = request.GET.get("page")
    students_page = paginator.get_page(page_number)

    headers = []
    for coluna in colunas:
        label = STUDENT_HEADER_LABELS.get(coluna, coluna.title())
        is_active = sort_field == coluna
        if is_active:
            next_direction = "desc" if sort_direction == "asc" else "asc"
        else:
            next_direction = "asc"
        headers.append(
            {
                "id": coluna,
                "label": label,
                "is_active": is_active,
                "direction": sort_direction if is_active else None,
                "next_direction": next_direction,
            }
        )

    return {
        "students_sorted": estudantes_ordenados,
        "students_page": students_page,
        "headers": headers,
        "current_sort": sort_field,
        "current_direction": sort_direction,
    }


class DashboardLoginView(LoginView):
    template_name = "dashboard/login.html"
    redirect_authenticated_user = True

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.fields["username"].widget.attrs.update(
            {"autofocus": True, "placeholder": "Seu usuário", "autocomplete": "username"}
        )
        form.fields["password"].widget.attrs.update(
            {"placeholder": "Sua senha", "autocomplete": "current-password"}
        )
        return form

    def form_valid(self, form):
        messages.success(self.request, "Login realizado com sucesso.")
        return super().form_valid(form)

    def form_invalid(self, form):
        messages.error(self.request, "Não foi possível realizar o login. Verifique suas credenciais.")
        return super().form_invalid(form)


class DashboardLogoutView(TemplateView):
    template_name = "dashboard/logout.html"

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if request.user.is_authenticated:
            logout(request)
        return super().dispatch(request, *args, **kwargs)

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        # Garante compatibilidade com formulários que usem POST.
        return self.get(request, *args, **kwargs)


@login_required(login_url=reverse_lazy("dashboard:login"))
def dashboard_view(request: HttpRequest) -> HttpResponse:
    dataset = load_dataset()
    students = dataset.get("students", [])
    available_turmas = dataset.get("turmas", [])
    available_arquivos = dataset.get("arquivos", [])

    turmas_permitidas = _turmas_permitidas_para_usuario(request.user, available_turmas)
    if turmas_permitidas:
        students = [student for student in students if student.get("turma") in turmas_permitidas]
        available_arquivos = sorted({student.get("arquivo") for student in students if student.get("arquivo")})
        available_turmas = turmas_permitidas
    elif not _usuario_eh_coordenador(request.user):
        students = []
        available_turmas = []
        available_arquivos = []
    else:
        available_turmas = list(available_turmas)

    filtros = _extrair_filtros(request.GET)
    if filtros["turma"] and filtros["turma"] not in available_turmas:
        filtros["turma"] = ""
    estudantes_filtrados = _aplicar_filtros(students, filtros)
    estudantes_filtrados = _remover_duplicados(estudantes_filtrados)
    insights = _gerar_insights(estudantes_filtrados)

    tabela_context = _preparar_tabela_estudantes(
        request,
        estudantes_filtrados,
        ["turma", "nome", "nota", "percentual_nota", "acertos", "percentual_acertos", "arquivo"],
    )

    context = {
        "students": tabela_context["students_page"],
        "filters": filtros,
        "turmas": available_turmas,
        "arquivos": available_arquivos,
        "insights": insights,
        "total_estudantes": len(students),
        "is_coordinator": _usuario_eh_coordenador(request.user),
        "student_table_headers": tabela_context["headers"],
        "current_sort": tabela_context["current_sort"],
        "current_direction": tabela_context["current_direction"],
        "page_obj": tabela_context["students_page"],
        "paginator": tabela_context["students_page"].paginator,
        "is_paginated": tabela_context["students_page"].has_other_pages(),
    }
    return render(request, "dashboard/index.html", context)


@login_required(login_url=reverse_lazy("dashboard:login"))
def dashboard_visual_view(request: HttpRequest) -> HttpResponse:
    dataset = load_dataset()
    students = dataset.get("students", [])
    available_turmas = dataset.get("turmas", [])
    available_arquivos = dataset.get("arquivos", [])

    turmas_permitidas = _turmas_permitidas_para_usuario(request.user, available_turmas)
    if turmas_permitidas:
        students = [student for student in students if student.get("turma") in turmas_permitidas]
        available_arquivos = sorted({student.get("arquivo") for student in students if student.get("arquivo")})
        available_turmas = turmas_permitidas
    elif not _usuario_eh_coordenador(request.user):
        students = []
        available_turmas = []
        available_arquivos = []
    else:
        available_turmas = list(available_turmas)

    filtros = _extrair_filtros(request.GET)
    if filtros["turma"] and filtros["turma"] not in available_turmas:
        filtros["turma"] = ""
    estudantes_filtrados = _aplicar_filtros(students, filtros)
    estudantes_filtrados = _remover_duplicados(estudantes_filtrados)
    insights = _gerar_insights(estudantes_filtrados)
    estudantes_enriquecidos = [_anotar_status_estudante(estudante) for estudante in estudantes_filtrados]
    visual_data = _gerar_dados_visuais(estudantes_enriquecidos, insights)

    tabela_context = _preparar_tabela_estudantes(
        request,
        estudantes_enriquecidos,
        ["turma", "nome", "status", "nota", "percentual_nota", "acertos", "percentual_acertos", "arquivo"],
    )

    context = {
        "students": tabela_context["students_page"],
        "filters": filtros,
        "turmas": available_turmas,
        "arquivos": available_arquivos,
        "insights": insights,
        "total_estudantes": len(students),
        "status_profiles": STATUS_PROFILES,
        "visual_data": visual_data,
        "is_coordinator": _usuario_eh_coordenador(request.user),
        "student_table_headers": tabela_context["headers"],
        "current_sort": tabela_context["current_sort"],
        "current_direction": tabela_context["current_direction"],
        "page_obj": tabela_context["students_page"],
        "paginator": tabela_context["students_page"].paginator,
        "is_paginated": tabela_context["students_page"].has_other_pages(),
    }
    return render(request, "dashboard/visual.html", context)


@login_required(login_url=reverse_lazy("dashboard:login"))
def questoes_view(request: HttpRequest) -> HttpResponse:
    dataset = load_dataset()
    students = dataset.get("students", [])
    available_turmas = dataset.get("turmas", [])
    available_arquivos = dataset.get("arquivos", [])
    question_bank = dataset.get("question_bank", {})

    turmas_permitidas = _turmas_permitidas_para_usuario(request.user, available_turmas)
    if turmas_permitidas:
        students = [student for student in students if student.get("turma") in turmas_permitidas]
        available_arquivos = sorted({student.get("arquivo") for student in students if student.get("arquivo")})
        available_turmas = turmas_permitidas
    elif not _usuario_eh_coordenador(request.user):
        students = []
        available_turmas = []
        available_arquivos = []
    else:
        available_turmas = list(available_turmas)

    filtros = _extrair_filtros(request.GET)
    if filtros["turma"] and filtros["turma"] not in available_turmas:
        filtros["turma"] = ""
    estudantes_filtrados = _aplicar_filtros(students, filtros)
    estudantes_filtrados = _remover_duplicados(estudantes_filtrados)
    metricas = _construir_metricas_questoes(estudantes_filtrados, question_bank)

    busca = request.GET.get("busca", "").strip()
    if busca:
        metricas = [m for m in metricas if busca.lower() in str(m["questao"]).lower()]

    taxa_lista = [item["taxa_acerto"] for item in metricas if item["respondidas"] > 0]
    media_taxa = round(statistics.mean(taxa_lista), 2) if taxa_lista else 0.0
    try:
        mediana_taxa = round(statistics.median(taxa_lista), 2) if taxa_lista else 0.0
    except StatisticsError:
        mediana_taxa = media_taxa
    desvio_taxa = round(statistics.pstdev(taxa_lista), 2) if len(taxa_lista) > 1 else 0.0

    melhores = sorted(metricas, key=lambda item: item["taxa_acerto"], reverse=True)[:5]
    piores = sorted(metricas, key=lambda item: item["taxa_acerto"])[:5]

    grafico = {
        "labels": [item["questao"] for item in metricas],
        "values": [item["taxa_acerto"] for item in metricas],
        "weights": [item["peso"] for item in metricas],
    }

    context = {
        "filters": filtros,
        "turmas": available_turmas,
        "arquivos": available_arquivos,
        "is_coordinator": _usuario_eh_coordenador(request.user),
        "questoes": metricas,
        "busca": busca,
        "estatisticas": {
            "total": len(metricas),
            "media": media_taxa,
            "mediana": mediana_taxa,
            "desvio_padrao": desvio_taxa,
        },
        "melhores": melhores,
        "piores": piores,
        "grafico": grafico,
    }
    return render(request, "dashboard/questoes.html", context)


@login_required(login_url=reverse_lazy("dashboard:login"))
def perfil_view(request: HttpRequest) -> HttpResponse:
    profile, profile_created = ProfessorProfile.objects.get_or_create(usuario=request.user)

    if request.method == "POST":
        user_form = UserProfileForm(request.POST, instance=request.user)
        profile_form = ProfessorProfileForm(request.POST, request.FILES, instance=profile)
        if user_form.is_valid() and profile_form.is_valid():
            user_form.save()
            profile_form.save()
            messages.success(request, _("Perfil atualizado com sucesso."))
            return redirect("dashboard:perfil")
        messages.error(request, _("Revise os dados informados e tente novamente."))
    else:
        user_form = UserProfileForm(instance=request.user)
        profile_form = ProfessorProfileForm(instance=profile)

    turmas_autorizadas = profile.turmas.all() if profile.pk else []

    context = {
        "user_form": user_form,
        "profile_form": profile_form,
        "turmas_autorizadas": turmas_autorizadas,
        "is_coordinator": _usuario_eh_coordenador(request.user),
    }
    return render(request, "dashboard/perfil.html", context)


@login_required(login_url=reverse_lazy("dashboard:login"))
@user_passes_test(_usuario_eh_coordenador, login_url=reverse_lazy("dashboard:login"), redirect_field_name=None)
def coordinator_dashboard(request: HttpRequest) -> HttpResponse:
    ensure_turmas_sincronizadas()

    planilhas_dir = Path(settings.PLANILHAS_DIR)
    planilhas_dir.mkdir(parents=True, exist_ok=True)

    turmas_queryset = Turma.objects.order_by("nome")

    upload_form = PlanilhaUploadForm()
    professor_form = ProfessorCreationForm(turmas_queryset=turmas_queryset)

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "upload":
            upload_form = PlanilhaUploadForm(request.POST, request.FILES)
            if upload_form.is_valid():
                arquivo = upload_form.cleaned_data["arquivo"]
                destino = planilhas_dir / arquivo.name
                with destino.open("wb+") as destination:
                    for chunk in arquivo.chunks():
                        destination.write(chunk)
                try:
                    workbook = load_workbook(destino, read_only=True, data_only=True)
                    workbook.close()
                except (BadZipFile, InvalidFileException, KeyError):
                    destino.unlink(missing_ok=True)
                    messages.error(
                        request,
                        _("Não foi possível abrir a planilha. Confirme que o arquivo está em formato .xlsx válido."),
                    )
                    return redirect("dashboard:coordenacao")
                invalidate_dataset_cache()
                dataset_atualizado = load_dataset()
                planilha_tem_dados = any(
                    student.get("arquivo") == arquivo.name for student in dataset_atualizado.get("students", [])
                )
                if not planilha_tem_dados:
                    destino.unlink(missing_ok=True)
                    invalidate_dataset_cache()
                    messages.error(
                        request,
                        _(
                            "Não foi possível interpretar a planilha %(arquivo)s. "
                            "Verifique se ela segue o modelo esperado (com gabarito e pesos)."
                        )
                        % {"arquivo": arquivo.name},
                    )
                    return redirect("dashboard:coordenacao")
                ensure_turmas_sincronizadas()
                messages.success(
                    request,
                    _("Planilha %(arquivo)s salva com sucesso.") % {"arquivo": arquivo.name},
                )
                return redirect("dashboard:coordenacao")
            else:
                messages.error(request, _("Não foi possível enviar a planilha."))
        elif action == "criar_professor":
            professor_form = ProfessorCreationForm(request.POST, turmas_queryset=Turma.objects.order_by("nome"))
            if professor_form.is_valid():
                novo_usuario = professor_form.save()
                perfil, perfil_criado = ProfessorProfile.objects.get_or_create(usuario=novo_usuario)
                perfil.turmas.set(professor_form.cleaned_data["turmas"])
                messages.success(
                    request,
                    _("Professor %(nome)s cadastrado com sucesso.")
                    % {"nome": novo_usuario.get_full_name() or novo_usuario.username},
                )
                return redirect("dashboard:coordenacao")
            else:
                messages.error(request, _("Revise os dados do professor e tente novamente."))
        else:
            messages.error(request, _("Ação não reconhecida."))

    professores = (
        ProfessorProfile.objects.select_related("usuario")
        .prefetch_related("turmas")
        .order_by("usuario__first_name", "usuario__username")
    )
    arquivos_planilhas = sorted(path.name for path in planilhas_dir.glob("*.xlsx"))

    contexto = {
        "upload_form": upload_form,
        "professor_form": professor_form,
        "planilhas": arquivos_planilhas,
        "professores": professores,
        "tem_turmas": turmas_queryset.exists(),
        "is_coordinator": True,
    }
    return render(request, "dashboard/coordenacao.html", contexto)


def _extrair_filtros(params: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "turma": params.get("turma", "").strip(),
        "arquivo": params.get("arquivo", "").strip(),
        "nome": params.get("nome", "").strip(),
        "nota_min": _converter_float(params.get("nota_min")),
        "nota_max": _converter_float(params.get("nota_max")),
    }


def _converter_float(value: Any) -> float | None:
    if value in (None, "", " "):
        return None
    try:
        texto = str(value).replace(",", ".")
        return float(texto)
    except ValueError:
        return None


def _aplicar_filtros(students: Iterable[Dict[str, Any]], filtros: Dict[str, Any]) -> List[Dict[str, Any]]:
    resultado = []
    nome_busca = filtros.get("nome", "").lower()
    for student in students:
        if filtros.get("turma") and student.get("turma") != filtros["turma"]:
            continue
        if filtros.get("arquivo") and student.get("arquivo") != filtros["arquivo"]:
            continue
        if nome_busca and nome_busca not in student.get("nome", "").lower():
            continue
        nota = student.get("nota")
        if filtros.get("nota_min") is not None and nota < filtros["nota_min"]:
            continue
        if filtros.get("nota_max") is not None and nota > filtros["nota_max"]:
            continue
        resultado.append(student)
    return resultado


def _remover_duplicados(students: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    vistos: set[tuple[Any, ...]] = set()
    sem_duplicados: List[Dict[str, Any]] = []
    for student in students:
        chave = (
            (student.get("nome") or "").strip().lower(),
            student.get("turma"),
            round(float(student.get("nota") or 0.0), 2),
            student.get("arquivo"),
        )
        if chave in vistos:
            continue
        vistos.add(chave)
        sem_duplicados.append(student)
    return sem_duplicados


def _gerar_insights(students: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not students:
        return {
            "total": 0,
            "media": 0.0,
            "melhor": None,
            "pior": None,
            "turmas": [],
            "top": [],
            "bottom": [],
            "questoes_dificeis": [],
            "questoes_faceis": [],
        }

    total = len(students)
    notas = [student["nota"] for student in students]
    media = round(sum(notas) / total, 2)
    try:
        mediana = round(statistics.median(notas), 2)
    except StatisticsError:
        mediana = media
    desvio_padrao = round(statistics.pstdev(notas), 2) if total > 1 else 0.0
    melhor = max(students, key=lambda student: student["nota"])
    pior = min(students, key=lambda student: student["nota"])

    turmas_agrupadas: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for student in students:
        turmas_agrupadas[student["turma"]].append(student)

    turmas_resumo = []
    for turma, membros in sorted(turmas_agrupadas.items()):
        total_turma = len(membros)
        media_turma = round(sum(m["nota"] for m in membros) / total_turma, 2)
        turmas_resumo.append(
            {
                "nome": turma,
                "total": total_turma,
                "media": media_turma,
                "melhor": max(membros, key=lambda item: item["nota"]),
                "pior": min(membros, key=lambda item: item["nota"]),
            }
        )

    top = sorted(students, key=lambda student: student["nota"], reverse=True)[:5]
    bottom = sorted(students, key=lambda student: student["nota"])[:5]

    questoes_estatistica = _calcular_estatistica_questoes(students)
    questoes_ordenadas = sorted(questoes_estatistica, key=lambda item: item["taxa_acerto"])
    questoes_dificeis = questoes_ordenadas[:5]
    questoes_faceis = list(reversed(questoes_ordenadas[-5:])) if questoes_ordenadas else []

    return {
        "total": total,
        "media": media,
        "mediana": mediana,
        "desvio_padrao": desvio_padrao,
        "melhor": melhor,
        "pior": pior,
        "turmas": turmas_resumo,
        "top": top,
        "bottom": bottom,
        "questoes_dificeis": questoes_dificeis,
        "questoes_faceis": questoes_faceis,
    }


def _calcular_estatistica_questoes(students: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    estatisticas: Dict[str, Dict[str, Any]] = {}

    for student in students:
        respostas = student.get("respostas", {})
        gabarito = student.get("gabarito", {})
        for questao, resposta_correta in gabarito.items():
            if resposta_correta is None:
                continue
            resposta = respostas.get(questao)
            entrada = estatisticas.setdefault(
                questao,
                {
                    "questao": questao,
                    "gabarito": resposta_correta,
                    "respondidas": 0,
                    "acertos": 0,
                },
            )
            entrada["respondidas"] += 1
            if resposta == resposta_correta:
                entrada["acertos"] += 1

    for estatistica in estatisticas.values():
        respondidas = estatistica["respondidas"]
        acertos = estatistica["acertos"]
        estatistica["taxa_acerto"] = round((acertos / respondidas * 100) if respondidas else 0.0, 2)

    return list(estatisticas.values())


def _anotar_status_estudante(student: Dict[str, Any]) -> Dict[str, Any]:
    status = _classificar_nota(student.get("nota", 0.0))
    anotado = student.copy()
    anotado["status"] = {
        "id": status["id"],
        "label": status["label"],
        "color": status["color"],
        "bg": status["bg"],
        "range": status["range"],
    }
    return anotado


def _gerar_dados_visuais(
    students: List[Dict[str, Any]],
    insights: Dict[str, Any],
) -> Dict[str, Any]:
    total = len(students)
    distribuicao_status = {perfil["id"]: 0 for perfil in STATUS_PROFILES}
    for student in students:
        status_id = student.get("status", {}).get("id")
        if status_id in distribuicao_status:
            distribuicao_status[status_id] += 1

    status_summary = []
    for perfil in STATUS_PROFILES:
        contador = distribuicao_status.get(perfil["id"], 0)
        status_summary.append(
            {
                "id": perfil["id"],
                "label": perfil["label"],
                "range": perfil["range"],
                "color": perfil["color"],
                "bg": perfil["bg"],
                "icon": perfil["icon"],
                "count": contador,
                "percentage": round((contador / total * 100), 1) if total > 0 else 0.0,
            }
        )

    turmas = insights.get("turmas", [])
    turma_colors = []
    for turma in turmas:
        perfil = _classificar_nota(turma.get("media", 0.0))
        turma_colors.append(perfil["color"])

    turma_chart = {
        "labels": [turma["nome"] for turma in turmas],
        "medias": [turma["media"] for turma in turmas],
        "colors": turma_colors,
    }

    notas = [student.get("nota", 0.0) for student in students]
    notas_ordenadas = sorted(notas, reverse=True)
    sparkline = {
        "labels": list(range(1, len(notas_ordenadas) + 1)),
        "values": notas_ordenadas,
    }

    scatter_points = [
        {
            "x": round(student.get("percentual_nota", 0.0), 2),
            "y": round(student.get("percentual_acertos", 0.0), 2),
            "nome": student.get("nome"),
            "turma": student.get("turma"),
        }
        for student in students
    ]

    try:
        quartis = statistics.quantiles(notas, n=4)
    except (StatisticsError, ValueError):
        quartis = []

    boxplot = {
        "min": round(min(notas), 2) if notas else 0.0,
        "q1": round(quartis[0], 2) if len(quartis) >= 1 else (round(notas_ordenadas[-1], 2) if notas else 0.0),
        "median": round(statistics.median(notas), 2) if notas else 0.0,
        "q3": round(quartis[2], 2) if len(quartis) >= 3 else (round(notas_ordenadas[0], 2) if notas else 0.0),
        "max": round(max(notas), 2) if notas else 0.0,
    }

    curva_percentis = {
        "labels": [
            round(idx * (100 / max(len(notas_ordenadas) - 1, 1)), 1)
            for idx in range(len(notas_ordenadas))
        ],
        "values": list(reversed(notas_ordenadas)),
    }

    top_students = sorted(students, key=lambda item: item.get("nota", 0.0), reverse=True)[:5]
    bottom_students = sorted(students, key=lambda item: item.get("nota", 0.0))[:5]

    return {
        "status_summary": status_summary,
        "turma_chart": turma_chart,
        "sparkline": sparkline,
        "scatter": scatter_points,
        "boxplot": boxplot,
        "percentile_curve": curva_percentis,
        "top_students": top_students,
        "bottom_students": bottom_students,
    }


def _construir_metricas_questoes(
    students: List[Dict[str, Any]],
    question_bank: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    estatisticas: Dict[str, Dict[str, Any]] = {}

    for questao, dados in question_bank.items():
        estatisticas[questao] = {
            "questao": questao,
            "gabarito": dados.get("gabarito"),
            "peso": dados.get("peso", 0.0),
            "respondidas": 0,
            "acertos": 0,
            "em_branco": 0,
        }

    for student in students:
        respostas = student.get("respostas", {})
        gabarito = student.get("gabarito", {})
        for questao, resposta_correta in gabarito.items():
            if resposta_correta is None:
                continue
            entrada = estatisticas.setdefault(
                questao,
                {
                    "questao": questao,
                    "gabarito": resposta_correta,
                    "peso": 0.0,
                    "respondidas": 0,
                    "acertos": 0,
                    "em_branco": 0,
                },
            )
            resposta = respostas.get(questao)
            if resposta is None:
                entrada["em_branco"] += 1
            else:
                entrada["respondidas"] += 1
                if resposta == resposta_correta:
                    entrada["acertos"] += 1

    metricas = []
    for questao, dados in estatisticas.items():
        total_alunos = dados["respondidas"] + dados["em_branco"]
        total_validos = max(dados["respondidas"], 1)
        taxa = round(dados["acertos"] / total_validos * 100, 2)
        metricas.append(
            {
                "questao": questao,
                "gabarito": dados.get("gabarito"),
                "peso": dados.get("peso", 0.0),
                "respondidas": dados["respondidas"],
                "em_branco": dados["em_branco"],
                "total_alunos": total_alunos,
                "acertos": dados["acertos"],
                "taxa_acerto": taxa,
                "dificuldade": round(100 - taxa, 2),
            }
        )

    metricas.sort(key=lambda item: item["taxa_acerto"])
    return metricas


def _classificar_nota(nota: float) -> Dict[str, Any]:
    for perfil in STATUS_PROFILES:
        minimo = perfil.get("min")
        maximo = perfil.get("max")
        if (minimo is None or nota >= minimo) and (maximo is None or nota < maximo):
            return perfil
    return STATUS_PROFILES[-1]
