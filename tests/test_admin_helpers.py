import json

from fastapi.responses import HTMLResponse

from app.web.routes.admin.helpers import (
    apply_htmx_response_headers,
    build_admin_toast_payload,
    merge_hx_trigger_headers,
    trigger_admin_toast,
)


def test_merge_hx_trigger_headers_combines_existing_payload():
    existing = json.dumps({"admin:refresh": {"target": "rules-table"}})

    merged = merge_hx_trigger_headers(
        existing,
        {"admin:toast": build_admin_toast_payload("Regra salva.", level="success")},
    )

    payload = json.loads(merged)
    assert payload["admin:refresh"] == {"target": "rules-table"}
    assert payload["admin:toast"]["message"] == "Regra salva."
    assert payload["admin:toast"]["level"] == "success"


def test_apply_htmx_response_headers_supports_toast_and_url_headers():
    response = HTMLResponse("ok")

    response = trigger_admin_toast(response, "Atualizado com sucesso.", level="success")
    response = apply_htmx_response_headers(
        response,
        push_url="/admin/rules?open_rule_id=1",
        reswap="outerHTML",
        retarget="#rules-table",
    )

    triggers = json.loads(response.headers["HX-Trigger"])
    assert triggers["admin:toast"]["message"] == "Atualizado com sucesso."
    assert triggers["admin:toast"]["level"] == "success"
    assert response.headers["HX-Push-Url"] == "/admin/rules?open_rule_id=1"
    assert response.headers["HX-Reswap"] == "outerHTML"
    assert response.headers["HX-Retarget"] == "#rules-table"
