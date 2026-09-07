# Security policy

Do not report exposed API credentials in a public Issue. Use GitHub's private vulnerability reporting page for this repository once available, or contact the maintainer through the GitHub profile.

When sharing diagnostics:

- Never attach `.gui_state.json`.
- Remove API endpoints, keys, usernames, and local paths from logs.
- Use a revoked test key when reproducing authentication problems.

Supported security fixes target the latest Release on Ubuntu 22.04 amd64.
