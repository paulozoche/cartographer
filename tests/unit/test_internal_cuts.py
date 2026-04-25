from agnostic.core.internal_cuts import attach_internal_cuts


def test_attach_internal_cuts_adds_dominant_values_and_keeps_exception() -> None:
    payload = {
        "unit_name": "events",
        "columns": {
            "ssn": {
                "layer1_metrics": {
                    "mode_frequency": {"value": "A", "count": 2, "ratio": 0.10},
                    "frequency": {"counts": {"A": 2, "B": 1, "C": 1}},
                    "unique_ratio": 0.75,
                    "null_ratio": 0.0,
                    "empty_string_ratio": 0.0,
                }
            }
        },
    }

    result = attach_internal_cuts(payload)
    recortes = result["columns"]["ssn"]["recortes_internos"]
    tipos = [item["tipo"] for item in recortes]
    ids = [item["id"] for item in recortes]

    assert "dominancia" in tipos
    assert "excecao" in tipos
    assert any("dominant_values" in recorte_id for recorte_id in ids)


def test_exception_group_option_uses_multiscale_rule() -> None:
    payload = {
        "unit_name": "events",
        "columns": {
            "token": {
                "layer1_metrics": {
                    "mode_frequency": {"value": "A", "count": 50, "ratio": 0.5},
                    "frequency": {
                        "counts": {
                            "A": 50,
                            "B": 20,
                            "C": 10,
                            "D": 8,
                            "E": 6,
                            "r1": 1,
                            "r2": 1,
                            "r3": 1,
                            "r4": 1,
                            "r5": 1,
                            "r6": 1,
                        }
                    },
                    "unique_ratio": 0.11,
                    "null_ratio": 0.0,
                    "empty_string_ratio": 0.0,
                }
            }
        },
    }

    result = attach_internal_cuts(payload)
    recortes = result["columns"]["token"]["recortes_internos"]
    excecao = next(item for item in recortes if item["tipo"] == "excecao")

    assert excecao["metadata"]["show_group_option"] is True
    destinos = [item["destino"] for item in excecao["transicoes_permitidas"]]
    assert "recorte" in destinos
