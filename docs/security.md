# Security Design

## Threat model

Primary concerns are account compromise, cross-organization access, insecure operational updates, malicious uploads, token theft, injection, sensitive evidence exposure, and unsafe assumptions about automated safety decisions.

## Controls implemented

- PBKDF2-SHA256 with random salt and 240,000 iterations.
- JWT access tokens with organization and role claims.
- Persisted SHA-256 refresh-token hashes, 14-day expiry, rotation, revocation, and replay rejection.
- Failed-login counting and an in-memory eight-attempt/five-minute throttle.
- Role checks on berth plans, yard moves, incident transitions, simulation, CV, OCR, snapshots, and audit.
- Server-derived organization scope on all operational queries.
- SQLAlchemy parameterization and Pydantic validation.
- Explicit idempotency keys for state-changing events.
- Append-only audit creation through normal APIs.
- Security response headers and configurable CORS.
- Evidence served from a dedicated generated-data path.
- Non-root Docker users for API and worker.
- CI dependency and syntax checks.

## Production hardening required

- Replace the local JWT secret, passwords, and service credentials.
- Use an external identity provider, MFA, short access-token lifetime, secure HttpOnly cookies, token-family compromise handling, and distributed rate limiting.
- Put evidence behind authenticated signed URLs rather than an open static route.
- Enforce upload size, MIME sniffing, antivirus scanning, image decoding limits, and object-store policies for user uploads.
- Enable TLS, HSTS, CSP, network segmentation, private database access, secrets management, database encryption, audit export, SIEM, and intrusion detection.
- Use fine-grained permissions instead of the demonstration role strings.
- Perform dependency, image, SAST, DAST, penetration, privacy, and safety assessments.

## Safety boundary

Computer-vision events are operational indicators requiring human review. The software must not be treated as a certified safety controller or as the sole basis for disciplinary or emergency actions.
