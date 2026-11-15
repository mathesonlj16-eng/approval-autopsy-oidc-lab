# Approval Autopsy — GitHub Actions OIDC Lab

A small, public security-testing repository exploring how to verify **GitHub Actions job identity** before allowing a build or release operation.

This is an **experimental lab**, not a standalone product or production authorization service. The repository contains test clients and JWT verification logic; some hosted verifier infrastructure and supporting evidence are intentionally maintained outside this repository.

## What it demonstrates

- Obtaining a GitHub Actions OIDC identity token for an intended audience.
- Validating token signatures against GitHub's published signing keys and checking explicit identity claims.
- Separating build and release roles instead of accepting a matching audience alone.
- Exercising negative cases such as wrong audience, cross-role requests, replay attempts, substituted artifacts, changed workflow attempts and revoked approvals.
- Reporting test decisions without printing bearer tokens.

## Code map

| File | Purpose |
| --- | --- |
| [`oidc_verifier.py`](oidc_verifier.py) | JWT validation and claim-policy checks |
| [`oidc_probe.py`](oidc_probe.py) | GitHub Actions token requests and negative identity tests |
| [`alpha-live-client.py`](alpha-live-client.py) | Hosted lab client for approval and authorization cases |
| [`phase7_client.py`](phase7_client.py) | Disposable-artifact release, replay and substitution test cases |
| [`.github/workflows/`](.github/workflows/) | GitHub Actions lab workflows |

## Scope and limitations

- Successful tests are evidence for the specific lab conditions, **not proof of general production security**.
- The hosted verifier and disposable endpoints are not provided as a reusable service by this repository.
- No private credentials or live authorization tokens should be committed or included in screenshots or logs.
- The scripts are designed for controlled experiments in authorized GitHub Actions environments, not an unauthenticated local demo.

Related work: [AgencyFlow AI](https://github.com/mathesonlj16-eng/AgencyFlow-AI) · [Notice Atlas](https://github.com/mathesonlj16-eng/notice-atlas-demo)
