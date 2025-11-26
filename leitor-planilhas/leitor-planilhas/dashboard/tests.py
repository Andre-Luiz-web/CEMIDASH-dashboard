import shutil
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from openpyxl import Workbook
from PIL import Image

from . import services
from .models import ProfessorProfile, Turma
from .views import COORDINATOR_GROUP, PROFESSOR_GROUP


class DashboardPermissionsTests(TestCase):
    def setUp(self) -> None:
        user_model = get_user_model()
        self.professor_group, _ = Group.objects.get_or_create(name=PROFESSOR_GROUP)
        self.coordinator_group, _ = Group.objects.get_or_create(name=COORDINATOR_GROUP)

        self.turma = Turma.objects.create(nome="Turma A")

        self.professor_user = user_model.objects.create_user(
            username="professor",
            password="senha-segura",
            first_name="Prof",
            last_name="Teste",
        )
        self.professor_user.groups.add(self.professor_group)
        self.professor_profile = ProfessorProfile.objects.create(usuario=self.professor_user)
        self.professor_profile.turmas.add(self.turma)

        self.coordinator_user = user_model.objects.create_user(
            username="coordenador",
            password="senha-segura",
            first_name="Coord",
            last_name="Teste",
        )
        self.coordinator_user.groups.add(self.coordinator_group)

    @patch("dashboard.views.load_dataset")
    def test_professor_visualiza_apenas_suas_turmas(self, mock_load_dataset) -> None:
        mock_load_dataset.return_value = {
            "students": [
                {"nome": "Aluno 1", "turma": "Turma A", "arquivo": "planilha.xlsx", "nota": 8.5},
                {"nome": "Aluno 2", "turma": "Turma B", "arquivo": "outra.xlsx", "nota": 7.0},
            ],
            "turmas": ["Turma A", "Turma B"],
            "arquivos": ["planilha.xlsx", "outra.xlsx"],
        }

        self.client.force_login(self.professor_user)
        response = self.client.get(reverse("dashboard:visual"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Aluno 1")
        self.assertNotContains(response, "Aluno 2")

    @patch("dashboard.views.ensure_turmas_sincronizadas")
    def test_coordenador_acessa_area_coordenacao(self, mock_sync) -> None:
        mock_sync.return_value = []

        self.client.force_login(self.coordinator_user)
        response = self.client.get(reverse("dashboard:coordenacao"))

        self.assertEqual(response.status_code, 200)

    def test_professor_nao_acessa_area_coordenacao(self) -> None:
        self.client.force_login(self.professor_user)
        response = self.client.get(reverse("dashboard:coordenacao"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("dashboard:login"), response.headers.get("Location", ""))


class EnsureTurmasSyncTests(TestCase):
    def test_sync_cria_e_remove_turmas(self) -> None:
        Turma.objects.create(nome="Turma Antiga")

        with patch.object(services, "load_dataset") as mock_load_dataset:
            mock_load_dataset.return_value = {
                "students": [],
                "turmas": ["Turma Nova"],
                "arquivos": [],
                "question_bank": {},
            }
            services.ensure_turmas_sincronizadas()

        self.assertTrue(Turma.objects.filter(nome="Turma Nova").exists())
        self.assertFalse(Turma.objects.filter(nome="Turma Antiga").exists())


class CoordinatorUploadTests(TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.planilhas_dir = Path(self.tmpdir)

        user_model = get_user_model()
        self.coordinator_group, _ = Group.objects.get_or_create(name=COORDINATOR_GROUP)
        self.coordinator_user = user_model.objects.create_user(
            username="coordenador-upload",
            password="senha-segura",
        )
        self.coordinator_user.groups.add(self.coordinator_group)

    def tearDown(self) -> None:
        shutil.rmtree(self.planilhas_dir, ignore_errors=True)

    def test_upload_planilha_invalida(self) -> None:
        with override_settings(PLANILHAS_DIR=self.planilhas_dir):
            self.client.force_login(self.coordinator_user)
            response = self.client.post(
                reverse("dashboard:coordenacao"),
                {
                    "action": "upload",
                    "arquivo": SimpleUploadedFile(
                        "dados.xlsx",
                        b"conteudo-invalido",
                        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    ),
                },
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Não foi possível abrir a planilha")
        self.assertFalse((self.planilhas_dir / "dados.xlsx").exists())

    def test_upload_planilha_sem_formato_esperado(self) -> None:
        wb = Workbook()
        ws = wb.active
        ws.append(["Nº", "Turma", "Aluno"])
        ws.append([1, "3A", "Fulano"])
        buffer = BytesIO()
        wb.save(buffer)
        buffer.seek(0)

        with override_settings(PLANILHAS_DIR=self.planilhas_dir):
            self.client.force_login(self.coordinator_user)
            response = self.client.post(
                reverse("dashboard:coordenacao"),
                {
                    "action": "upload",
                    "arquivo": SimpleUploadedFile(
                        "incompleto.xlsx",
                        buffer.getvalue(),
                        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    ),
                },
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Não foi possível interpretar a planilha")
        self.assertFalse((self.planilhas_dir / "incompleto.xlsx").exists())


class DatasetParsingTests(TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.planilhas_dir = Path(self.tmpdir)

    def tearDown(self) -> None:
        shutil.rmtree(self.planilhas_dir, ignore_errors=True)

    def test_linha_gabarito_nao_vira_estudante(self) -> None:
        wb = Workbook()
        ws = wb.active
        ws.title = "3A"
        ws.append(["3A (30 alunos)", None, None, None, None])
        ws.append(["Nº", "CPF", "NOME", "NOTA", "Q1"])
        ws.append(["00", "00000000000", "GABARITO", None, "A"])
        ws.append(["VALORES", None, None, None, 1])
        ws.append(["00", "11111111111", "GABARITO", None, "A"])
        ws.append([1, "22222222222", "Aluno Real", None, "A"])
        wb.save(self.planilhas_dir / "gabarito.xlsx")

        with override_settings(PLANILHAS_DIR=self.planilhas_dir):
            services.invalidate_dataset_cache()
            dataset = services.load_dataset()

        nomes = {student["nome"] for student in dataset["students"]}
        self.assertIn("Aluno Real", nomes)
        self.assertNotIn("GABARITO", {nome.upper() for nome in nomes})


class DashboardSortingPaginationTests(TestCase):
    def setUp(self) -> None:
        user_model = get_user_model()
        self.superuser = user_model.objects.create_user(
            username="admin",
            password="senha-segura",
            is_superuser=True,
        )

    def _make_student(self, idx: int, nome: str, nota: float) -> Dict[str, Any]:
        acertos = max(int(round(nota)), 0)
        return {
            "turma": "T1",
            "nome": nome,
            "nota": nota,
            "max_nota": 10.0,
            "percentual_nota": round(nota * 10, 2),
            "acertos": acertos,
            "total_questoes": 10,
            "percentual_acertos": round(acertos / 10 * 100, 2),
            "arquivo": "simulado.xlsx",
            "respostas": {"Q1": "A"},
            "gabarito": {"Q1": "A"},
        }

    @patch("dashboard.views.load_dataset")
    def test_ordena_alunos_por_nome(self, mock_load_dataset) -> None:
        dataset = {
            "students": [
                self._make_student(1, "Carlos", 6.0),
                self._make_student(2, "Ana", 9.0),
                self._make_student(3, "Bruno", 7.5),
            ],
            "turmas": ["T1"],
            "arquivos": ["simulado.xlsx"],
        }
        mock_load_dataset.return_value = dataset

        self.client.force_login(self.superuser)
        response = self.client.get(reverse("dashboard:visual"), {"sort": "nome", "direction": "asc"})

        self.assertEqual(response.status_code, 200)
        page_obj = response.context["page_obj"]
        nomes = [student["nome"] for student in page_obj.object_list]
        self.assertEqual(nomes, ["Ana", "Bruno", "Carlos"])

    @patch("dashboard.views.load_dataset")
    def test_paginacao_limita_50_registros(self, mock_load_dataset) -> None:
        students = [
            self._make_student(i, f"Aluno {i:03d}", nota=float(i % 10))
            for i in range(1, 121)
        ]
        dataset = {
            "students": students,
            "turmas": ["T1"],
            "arquivos": ["simulado.xlsx"],
        }
        mock_load_dataset.return_value = dataset

        self.client.force_login(self.superuser)
        response = self.client.get(reverse("dashboard:visual"))

        self.assertEqual(response.status_code, 200)
        page_obj = response.context["page_obj"]
        self.assertEqual(len(page_obj.object_list), 50)
        self.assertEqual(page_obj.number, 1)

        response_page_3 = self.client.get(reverse("dashboard:visual"), {"page": 3})
        page_obj_3 = response_page_3.context["page_obj"]
        self.assertEqual(page_obj_3.number, 3)
        self.assertEqual(len(page_obj_3.object_list), 20)

    @patch("dashboard.views.load_dataset")
    def test_remove_duplicados_por_nome_turma_nota(self, mock_load_dataset) -> None:
        repetido = self._make_student(1, "Aluno X", 8.0)
        dataset = {
            "students": [repetido, repetido.copy()],
            "turmas": ["T1"],
            "arquivos": ["simulado.xlsx"],
        }
        mock_load_dataset.return_value = dataset

        self.client.force_login(self.superuser)
        response = self.client.get(reverse("dashboard:home"))

        page_obj = response.context["page_obj"]
        self.assertEqual(len(page_obj.object_list), 1)


class QuestoesViewTests(TestCase):
    def setUp(self) -> None:
        user_model = get_user_model()
        self.superuser = user_model.objects.create_user(
            username="admin-questoes",
            password="senha-segura",
            is_superuser=True,
        )

    @patch("dashboard.views.load_dataset")
    def test_exibe_metricas_de_questoes(self, mock_load_dataset) -> None:
        mock_load_dataset.return_value = {
            "students": [
                {
                    "turma": "T1",
                    "arquivo": "prova.xlsx",
                    "respostas": {"1": "A", "2": "B"},
                    "gabarito": {"1": "A", "2": "C"},
                    "nota": 7.5,
                },
                {
                    "turma": "T1",
                    "arquivo": "prova.xlsx",
                    "respostas": {"1": "B", "2": "C"},
                    "gabarito": {"1": "A", "2": "C"},
                    "nota": 6.0,
                },
            ],
            "turmas": ["T1"],
            "arquivos": ["prova.xlsx"],
            "question_bank": {
                "1": {"gabarito": "A", "peso": 1.0},
                "2": {"gabarito": "C", "peso": 1.5},
            },
        }

        self.client.force_login(self.superuser)
        response = self.client.get(reverse("dashboard:questoes"))

        self.assertEqual(response.status_code, 200)
        self.assertIn("questoes", response.context)
        questoes = response.context["questoes"]
        self.assertEqual(len(questoes), 2)
        self.assertEqual(response.context["estatisticas"]["total"], 2)


class PerfilViewTests(TestCase):
    def setUp(self) -> None:
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="prof",
            password="senha-segura",
            first_name="Prof",
            last_name="Original",
            email="prof@example.com",
        )
        self.profile = ProfessorProfile.objects.create(usuario=self.user)

    def tearDown(self) -> None:
        ProfessorProfile.objects.all().delete()

    def _dummy_avatar(self):
        image = Image.new("RGB", (2, 2), color="blue")
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        buffer.seek(0)
        return SimpleUploadedFile("avatar.png", buffer.read(), content_type="image/png")

    def test_atualiza_perfil(self) -> None:
        self.client.force_login(self.user)
        with tempfile.TemporaryDirectory() as tmpdir, override_settings(MEDIA_ROOT=tmpdir):
            response = self.client.post(
                reverse("dashboard:perfil"),
                {
                    "first_name": "Maria",
                    "last_name": "Souza",
                    "email": "maria@example.com",
                },
            )

        self.user.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.user.first_name, "Maria")
        self.assertEqual(self.user.email, "maria@example.com")

    def test_envia_avatar(self) -> None:
        self.client.force_login(self.user)
        with tempfile.TemporaryDirectory() as tmpdir, override_settings(MEDIA_ROOT=tmpdir):
            response = self.client.post(
                reverse("dashboard:perfil"),
                {
                    "first_name": "João",
                    "last_name": "Silva",
                    "email": "joao@example.com",
                    "avatar": self._dummy_avatar(),
                },
            )
            self.assertEqual(response.status_code, 302)
            self.profile.refresh_from_db()
            self.assertTrue(bool(self.profile.avatar))


class LogoutViewTests(TestCase):
    def setUp(self) -> None:
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="logout-user",
            password="senha-segura",
        )

    def test_logout_get_finaliza_sessao(self) -> None:
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard:logout"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Você saiu do CEMIDash")
        self.assertNotIn("_auth_user_id", self.client.session)

# Create your tests here.
