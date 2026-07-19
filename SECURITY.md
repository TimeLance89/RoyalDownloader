# Security policy

## Supported version

Security fixes target the current `main` branch. Please update older builds
before reporting a vulnerability.

## Reporting a vulnerability

Do not publish sensitive details, credentials, or complete logs in a public
issue. Prefer GitHub private vulnerability reporting:

**Security → Advisories → Report a vulnerability**

If private reporting is unavailable, open an issue without technical details
and request a private contact channel.

A useful report includes:

- affected build ID or commit SHA;
- reproducible steps;
- expected and actual behavior;
- impact and possible attack path;
- sanitized logs without tokens, passwords, cookies, or private addresses.

High-priority examples include authentication bypasses, path traversal,
unexpected command execution, credential disclosure, and update-process
manipulation.
