# Security Policy

## Supported version

Security fixes target the latest `main` branch and the latest tagged release.

## Private reporting

Use GitHub private vulnerability reporting:

`Security` → `Advisories` → `Report a vulnerability`

Do not publish authentication bypasses, credentials, tokens, exploit code, private camera frames, or real port/customer data in an issue.

Include:

- affected version or commit;
- reproducible steps using synthetic/local data;
- impact and affected role/tenant;
- whether cross-organization access is possible;
- suggested mitigation when known.

## Response expectations

The maintainer will acknowledge a valid report, assess severity, coordinate a fix, and publish remediation notes when disclosure is safe. This project does not promise a commercial SLA.

## Deployment warning

The documented demo accounts, local passwords, and `.env.example` values are not production credentials. A production deployment requires new secrets, TLS, an identity provider, network controls, encrypted backup, monitoring, and a formal security assessment.

See [docs/security.md](docs/security.md) for the threat model and controls.
