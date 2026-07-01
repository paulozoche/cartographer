import wmill
import httpx


def main(
    session_id: str,
    unit_name: str,
    action: str = "analyze_unit",
    column: str = "",
    depth: str = "layer2",
    response: str = "",
    suggested_action: dict | None = None,
):
    if action == "clarify":
        message = response.strip() or "Não há ação pendente."
        return {"response": message}

    if action == "pending":
        message = response.strip() or "Deseja prosseguir com essa ação?"
        result: dict = {"response": message}
        if isinstance(suggested_action, dict) and suggested_action.get("action"):
            result["suggested_action"] = suggested_action
        return result

    core_api_url = wmill.get_variable("f/cartographer/CORE_API_URL").rstrip("/")

    if action == "analyze_unit":
        url = f"{core_api_url}/sessions/{session_id}/analyze_unit"
        body = {"unit_name": unit_name}
    elif action == "analyze_vertical":
        if not column.strip():
            raise ValueError("Coluna obrigatória para analyze_vertical")
        url = f"{core_api_url}/sessions/{session_id}/analyze_vertical"
        body = {
            "unit_name": unit_name,
            "depth": depth or "layer2",
            "key": column.strip(),
        }
    else:
        raise ValueError(f"Action não suportada: {action}")

    response = httpx.post(url, json=body, timeout=300.0)
    response.raise_for_status()
    return response.json()
