import json
from pathlib import Path

from app.main import app


def identity_contract() -> dict:
    spec = app.openapi()
    paths = {
        path: value
        for path, value in spec["paths"].items()
        if path.startswith(("/api/v1/auth/", "/api/v1/users/me", "/api/v1/admin/students"))
        and "/imports/" not in path
    }
    needed = set()

    def references(value):
        if isinstance(value, dict):
            if "$ref" in value and value["$ref"].startswith("#/components/schemas/"):
                needed.add(value["$ref"].rsplit("/", 1)[-1])
            for child in value.values():
                references(child)
        elif isinstance(value, list):
            for child in value:
                references(child)

    references(paths)
    schemas = {}
    while needed - schemas.keys():
        for name in sorted(needed - schemas.keys()):
            schemas[name] = spec["components"]["schemas"][name]
            references(schemas[name])
    return {
        "paths": paths,
        "schemas": schemas,
        "securitySchemes": spec["components"]["securitySchemes"],
    }


def test_identity_openapi_snapshot():
    snapshot = Path(__file__).with_name("openapi_contract.json")
    assert identity_contract() == json.loads(snapshot.read_text(encoding="utf-8"))


def test_openapi_auth_contract_shapes():
    contract = identity_contract()
    assert len(contract["paths"]) == 13
    assert set(contract["paths"]["/api/v1/users/me/data-requests"]) == {"get", "post"}
    assert set(contract["paths"]["/api/v1/users/me"]) == {"get", "patch"}
    paths = contract["paths"]
    registration = paths["/api/v1/auth/register"]["post"]
    assert registration["deprecated"] is True
    assert "201" not in registration["responses"] and "200" not in registration["responses"]
    assert registration["responses"]["403"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/ErrorEnvelope")
    assert "CORRECTION" in contract["schemas"]["DataRequestType"]["enum"]
    summary = contract["schemas"]["UserSummaryDTO"]
    assert "display_name" in summary["properties"]
    assert "display_name" not in summary["required"]
    assert [entry["required"] for entry in contract["schemas"]["LoginRequest"]["oneOf"]] == [
        ["email"],
        ["username"],
    ]
    for path in ("/api/v1/auth/logout", "/api/v1/auth/logout-all", "/api/v1/auth/password/reset"):
        assert "content" not in paths[path]["post"]["responses"]["204"]
    login = paths["/api/v1/auth/login"]["post"]
    assert login["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/LoginRequest"
    )
    assert login["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/TokenResponse"
    )
    for method in ("get", "patch"):
        assert paths["/api/v1/users/me"][method]["security"] == [{"HTTPBearer": []}]
    for operation in paths.values():
        for endpoint in operation.values():
            for status in ("401", "403", "422", "429", "503"):
                schema = endpoint["responses"][status]["content"]["application/json"]["schema"]
                assert schema["$ref"].endswith("/ErrorEnvelope")
    assert "error" in contract["schemas"]["ErrorEnvelope"]["properties"]
