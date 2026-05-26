from __future__ import annotations

from fastapi.testclient import TestClient
from pathlib import Path
import pytest

from agnostic.ai.ports.ai_orchestrator import AIResponse
from agnostic.infrastructure.ai.grok_client import GroqAPIError
from agnostic.interfaces.api.dependencies import get_ai_client
from agnostic.interfaces.api import create_app
from agnostic.interfaces.api.app import _bounded_json_preview


def test_health_route_returns_ok() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_root_route_returns_visual_interface() -> None:
    pytest.skip("Interface visual baseada em cards foi desativada em favor do chat no terminal.")
    client = TestClient(create_app())

    response = client.get("/")

    assert response.status_code == 200
    assert "Analisador de Dados Agnóstico" in response.text
    assert "Resumo da origem" in response.text
    assert "Unidade anterior" in response.text
    assert "Próxima unidade" in response.text
    assert "Copiar quadro" in response.text
    assert "Resumo humano" in response.text
    assert "Payload bruto" in response.text
    assert "Ativar modo foco" in response.text or "Desativar modo foco" in response.text
    assert "Setup essencial" in response.text
    assert "Painel de Ferramentas" in response.text
    assert "Painel de Orientação" in response.text
    assert "Tabelas da origem" in response.text
    assert "Árvore de recortes" in response.text
    assert "Nenhuma unidade carregada ainda." in response.text
    assert "Trilha de exploração: ainda vazia." in response.text
    assert "Baixar resumo" in response.text
    assert "Execute uma análise detalhada para habilitar o download." in response.text


def test_root_route_summary_shows_origin_overview_and_table_previews(monkeypatch, tmp_path: Path) -> None:
    pytest.skip("Interface visual baseada em cards foi desativada em favor do chat no terminal.")
    monkeypatch.setenv(
        "AGNOSTIC_DATA_ANALYSER_RESULTS_DIR",
        str(tmp_path / "results"),
    )
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text(
        "event_id,category\n"
        "1,A\n"
        "2,B\n",
        encoding="utf-8",
    )

    client = TestClient(create_app())

    response = client.get(
        "/",
        params={
            "source_type": "csv",
            "source_path": str(csv_path),
            "action": "summary",
        },
    )

    assert response.status_code == 200
    assert "Contexto de origem" in response.text
    assert "Estrutura analítica" in response.text
    assert "Banco: sample.csv" in response.text
    assert "tabelas detectadas" in response.text
    assert "Melhores pistas:" in response.text
    assert "Pista principal:" in response.text
    assert "sample.csv" in response.text
    assert "prioridade" in response.text
    assert "Resumo das colunas mais relevantes:" in response.text
    assert "event_id:" in response.text
    assert "sample.csv: 2 linhas, 2 colunas." in response.text
    assert "Árvore de recortes" in response.text
    assert "Detalhes técnicos (oculto)" in response.text
    assert "As métricas por unidade aparecem após a análise detalhada." not in response.text


def test_ai_consult_route_returns_simulated_response() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/ai/consult",
        json={"prompt": "Summarize the current system state."},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "grok"
    assert data["simulated"] is True
    assert data["quota_per_hour"] == 30


def test_bounded_json_preview_truncates_large_payload() -> None:
    preview = _bounded_json_preview({"blob": "x" * 5_000}, max_bytes=512)

    assert "payload truncado para evitar explosão de saída" in preview
    assert len(preview.encode("utf-8")) < 1_000


def test_ai_consult_route_returns_gateway_error_on_provider_failure() -> None:
    app = create_app()

    class FailingClient:
        def send(self, prompt: str, *, system_prompt: str | None = None) -> AIResponse:
            raise GroqAPIError("Groq request failed: HTTP 403 Forbidden")

    app.dependency_overrides[get_ai_client] = lambda: FailingClient()
    client = TestClient(app)

    response = client.post(
        "/ai/consult",
        json={"prompt": "Summarize the current system state."},
    )

    assert response.status_code == 502
    assert "403 Forbidden" in response.json()["detail"]


def test_tabular_analysis_route_returns_structured_result(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(
        "AGNOSTIC_DATA_ANALYSER_RESULTS_DIR",
        str(tmp_path / "results"),
    )
    client = TestClient(create_app())

    response = client.post(
        "/analysis/tabular",
        json={
            "unit_name": "events",
            "columns": ["event_id", "category"],
            "rows": [
                [1, "A"],
                [2, "B"],
                [3, "C"],
            ],
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert "summary" in data
    assert "Unidade events" in data["summary"]
    assert data["persisted_to"].endswith("events.json")
    assert data["unit_name"] == "events"
    assert data["standardized"]["row_count"] == 3
    assert data["standardized"]["column_order"] == ["event_id", "category"]
    assert set(data["columns"]) == {"event_id", "category"}
    for column_payload in data["columns"].values():
        recortes = column_payload.get("recortes_internos", [])
        assert len(recortes) <= 5
        for recorte in recortes:
            assert recorte["tipo"] in {"dominancia", "excecao", "ausencia"}
            assert recorte["prioridade"] in {"alta", "media", "baixa"}
            assert recorte["estado_estrutural"] in {"ativo", "estavel", "ambiguo", "esgotado"}
            assert recorte["transicoes_permitidas"]
    assert Path(data["persisted_to"]).exists()

    download_response = client.get(
        "/analysis/summary/download",
        params={"persisted_to": data["persisted_to"]},
    )
    assert download_response.status_code == 200
    assert download_response.headers["content-type"].startswith("text/markdown")
    assert "attachment; filename=" in download_response.headers["content-disposition"]
    assert "# Resumo da análise" in download_response.text
    assert "- Unidade: `events`" in download_response.text


def test_tabular_analysis_route_enforces_default_row_limit(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGNOSTIC_DATA_ANALYSER_RESULTS_DIR", str(tmp_path / "results"))
    monkeypatch.setenv("AGNOSTIC_ANALYSIS_MAX_ROWS_PER_UNIT", "2")
    client = TestClient(create_app())

    response = client.post(
        "/analysis/tabular",
        json={
            "unit_name": "events",
            "columns": ["event_id"],
            "rows": [[1], [2], [3]],
        },
    )

    assert response.status_code == 413
    assert "limite efetivo de 2 linhas" in response.json()["detail"]


def test_tabular_analysis_route_allows_request_override_to_disable_row_limit(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGNOSTIC_DATA_ANALYSER_RESULTS_DIR", str(tmp_path / "results"))
    monkeypatch.setenv("AGNOSTIC_ANALYSIS_MAX_ROWS_PER_UNIT", "2")
    client = TestClient(create_app())

    response = client.post(
        "/analysis/tabular",
        json={
            "unit_name": "events",
            "columns": ["event_id"],
            "rows": [[1], [2], [3]],
            "max_rows": 0,
        },
    )

    assert response.status_code == 200
    assert response.json()["standardized"]["row_count"] == 3


def test_source_inspection_route_uses_real_datasource(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(
        "AGNOSTIC_DATA_ANALYSER_RESULTS_DIR",
        str(tmp_path / "results"),
    )
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text(
        "event_id,category\n"
        "1,A\n"
        "2,B\n",
        encoding="utf-8",
    )

    client = TestClient(create_app())

    response = client.post(
        "/analysis/source",
        json={
            "source_type": "csv",
            "source_path": str(csv_path),
            "analyze_units": True,
            "unit_limit": 3,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["unit_names"] == ["sample.csv"]
    assert "summary" in data
    assert "sample.csv" in data["summary"]
    assert "Unidade em foco: sample.csv" in data["summary"]
    assert data["persisted_to"].endswith("sample.csv.json")
    assert data["source"]["display_name"] == "sample.csv"
    assert data["source"]["unit_count"] == 1
    assert len(data["units"]) == 1
    assert data["units"][0]["unit_name"] == "sample.csv"
    assert data["units"][0]["metrics_summary"]
    assert "linhas" in data["units"][0]["metrics_summary"][0]
    assert data["units"][0]["persisted_to"].endswith("sample.csv.json")
    for column_payload in data["units"][0]["columns"].values():
        recortes = column_payload.get("recortes_internos", [])
        assert len(recortes) <= 5
        for recorte in recortes:
            assert recorte["tipo"] in {"dominancia", "excecao", "ausencia"}
            assert recorte["prioridade"] in {"alta", "media", "baixa"}
            assert recorte["estado_estrutural"] in {"ativo", "estavel", "ambiguo", "esgotado"}
            assert recorte["transicoes_permitidas"]
    assert Path(data["persisted_to"]).exists()


def test_source_inspection_route_can_filter_selected_unit(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(
        "AGNOSTIC_DATA_ANALYSER_RESULTS_DIR",
        str(tmp_path / "results"),
    )
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text(
        "event_id,category\n"
        "1,A\n"
        "2,B\n",
        encoding="utf-8",
    )

    client = TestClient(create_app())

    response = client.post(
        "/analysis/source",
        json={
            "source_type": "csv",
            "source_path": str(csv_path),
            "analyze_units": True,
            "unit_limit": 3,
            "unit_name": "sample.csv",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["unit_names"] == ["sample.csv"]
    assert len(data["units"]) == 1
    assert data["units"][0]["unit_name"] == "sample.csv"
    assert data["unit_previews"][0]["description"].startswith("Unidade sample.csv:")
    assert "Unidade selecionada: sample.csv" in data["summary"]
    assert data["persisted_to"].endswith("sample.csv.json")
    assert Path(data["persisted_to"]).exists()


def test_root_route_detail_mode_shows_focused_unit_panel(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(
        "AGNOSTIC_DATA_ANALYSER_RESULTS_DIR",
        str(tmp_path / "results"),
    )
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text(
        "event_id,category\n"
        "1,A\n"
        "2,B\n",
        encoding="utf-8",
    )

    client = TestClient(create_app())

    response = client.get(
        "/",
        params={
            "source_type": "csv",
            "source_path": str(csv_path),
            "action": "details",
            "unit_name": "sample.csv",
        },
    )

    assert response.status_code == 200
    assert "Contexto da tabela" in response.text
    assert "Tabela em foco" in response.text
    assert "Estrutura analítica" in response.text
    assert "Detalhe" in response.text
    assert "focus-columns" in response.text
    assert "Métricas calculadas da tabela" in response.text
    assert "Detalhes técnicos (oculto)" in response.text
    assert "Layer 1" not in response.text
    assert "Layer 2" not in response.text
    assert "Colunas disponíveis nesta tabela." in response.text
    assert "Explore as colunas sem sair da tabela atual." in response.text
    assert "Árvore de recortes" in response.text
    assert "Voltar à origem" in response.text


def test_root_route_detail_mode_shows_action_controls_on_left(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(
        "AGNOSTIC_DATA_ANALYSER_RESULTS_DIR",
        str(tmp_path / "results"),
    )
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text(
        "event_id,category\n"
        "1,A\n"
        "2,B\n",
        encoding="utf-8",
    )

    client = TestClient(create_app())

    response = client.get(
        "/",
        params={
            "source_type": "csv",
            "source_path": str(csv_path),
            "action": "details",
            "unit_name": "sample.csv",
        },
    )

    assert response.status_code == 200
    assert "Setup essencial" in response.text
    assert "Resumo da origem" in response.text
    assert "Explorar rápido" not in response.text
    assert "Analisar unidade" not in response.text
    assert "Limpar estado salvo" not in response.text


def test_root_route_column_mode_shows_focused_column_panel(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(
        "AGNOSTIC_DATA_ANALYSER_RESULTS_DIR",
        str(tmp_path / "results"),
    )
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text(
        "event_id,category\n"
        "1,A\n"
        "2,B\n",
        encoding="utf-8",
    )

    client = TestClient(create_app())

    response = client.get(
        "/",
        params={
            "source_type": "csv",
            "source_path": str(csv_path),
            "action": "column",
            "unit_name": "sample.csv",
            "column_name": "event_id",
        },
    )

    assert response.status_code == 200
    assert "Contexto da coluna" in response.text
    assert "Estrutura analítica" in response.text
    assert "Sinais" in response.text
    assert "Capacidades" in response.text
    assert "Perfil dominante" in response.text
    assert "Cards" in response.text
    assert "Recortes internos relevantes" in response.text
    assert "Caminhos" in response.text
    assert "Amostra da coluna" in response.text
    assert "Contexto do valor / célula" in response.text
    assert "Estrutura analítica" in response.text
    assert "Detalhes técnicos (oculto)" in response.text
    assert "Layer 1" not in response.text
    assert "Layer 2" not in response.text
    assert "Recortes internos relevantes desta coluna." in response.text
    assert "Escolha o recorte mais informativo para avançar." in response.text
    assert "Árvore de recortes" in response.text
    assert "Voltar à tabela" in response.text


def test_source_inspection_route_returns_clear_error_for_missing_file() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/analysis/source",
        json={
            "source_type": "sqlite",
            "source_path": "/home/paulo/projects/bancos/does-not-exist.db",
            "analyze_units": True,
            "unit_limit": 3,
        },
    )

    assert response.status_code == 404
    assert "Caminho da origem não encontrado" in response.json()["detail"]


def test_source_inspection_route_returns_clear_error_for_directory_path(tmp_path: Path) -> None:
    directory = tmp_path / "db-folder"
    directory.mkdir()

    client = TestClient(create_app())

    response = client.post(
        "/analysis/source",
        json={
            "source_type": "sqlite",
            "source_path": str(directory),
            "analyze_units": True,
            "unit_limit": 3,
        },
    )

    assert response.status_code == 400
    assert "deve apontar para um arquivo" in response.json()["detail"]
