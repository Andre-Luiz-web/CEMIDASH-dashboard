from django.urls import path

from .views import (
    DashboardLoginView,
    DashboardLogoutView,
    coordinator_dashboard,
    dashboard_view,
    dashboard_visual_view,
    perfil_view,
    questoes_view,
)

app_name = "dashboard"

urlpatterns = [
    path("login/", DashboardLoginView.as_view(), name="login"),
    path("logout/", DashboardLogoutView.as_view(), name="logout"),
    path("perfil/", perfil_view, name="perfil"),
    path("questoes/", questoes_view, name="questoes"),
    path("coordenacao/", coordinator_dashboard, name="coordenacao"),
    path("resumo/", dashboard_view, name="home"),
    path("old", dashboard_view),
    path("", dashboard_visual_view, name="visual"),
]
