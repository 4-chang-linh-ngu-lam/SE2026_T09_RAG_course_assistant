# Lumi Service Auth

`lumi-service-auth` is the shared Python implementation for Lumi Service JWTs (Python 3.10+). It contains the token contract, signing/verifying logic, service trust policy and typed errors. It has no dependency on Core, FastAPI, ORM, database, or business modules. Each service supplies its own immutable `ServiceAuthConfig` and must use a separate signing key.

## Install

From the monorepo root, install the package into a consumer's environment:

```sh
python -m pip install ./packages/service-auth
```

For Core development, install the shared package and Core's development dependencies:

```sh
cd services/core
python -m pip install -e ../../packages/service-auth
python -m pip install -e '.[dev]'
```

Core pins `lumi-service-auth==0.1.0` in its dependency metadata. Always install the package from this monorepo path before installing Core; CI follows the same order. Docker builds both projects from their local paths and the runtime installs only from the generated wheelhouse (`--no-index`), so it cannot fetch a same-named package from a public registry.

The Core CI workflow performs the same two installations and runs the external-consumer packaging test under `packages/service-auth/tests`. Docker Compose builds Core with the monorepo root as build context; `services/core/Dockerfile` builds wheels for both projects, then installs those wheels in the runtime image. The root `.dockerignore` allowlists only the package and Core runtime inputs so RAG data, Web files, local environments and repository metadata are excluded.

## Contract

Configure a service identity, issuer, current `kid`, that service's private-key file, issued audience/scope allowlists, and verifier trust entries. Every trust entry is keyed by `kid` and binds one issuer, one service subject, one public key, permitted audiences and permitted scopes. Keep old and new public keys in the trust map only during the approved rotation overlap; remove the old entry to revoke that key.

The shared package accepts configuration explicitly and does not load environment variables or secrets itself. Core maps its settings into `ServiceAuthConfig` and supplies the FastAPI dependency. Other services can use the same package without importing Core:

```python
from lumi_service_auth import ServiceAuthConfig, verify_service_jwt

principal = verify_service_jwt(
    bearer_token,
    service_auth_config,
    required_scopes={"core:check_access"},
    audience="core",
)
```

The service-token contract is RS256 with `iss`, `sub`, string `aud`, list `scope`, `token_type=service`, integer `iat`/`exp`, optional integer `nbf`, and header `kid`. The verifier validates `nbf` with the configured clock skew; the signer does not currently emit it. Token lifetime is capped at 300 seconds and verifier clock skew at 30 seconds. Do not use a User JWT key or treat a Core `X-Service-Key` as a Service JWT fallback. Key provisioning and rotation are operator responsibilities; this package does not create or distribute production keys.

## Package tests

```sh
python -m pip install './packages/service-auth[test]'
python -m pytest packages/service-auth/tests -q
```

The external-consumer test builds and installs a wheel into a temporary target, then signs and verifies a token from a process whose working directory is outside Core. Test keys are temporary and are never written into the repository.
