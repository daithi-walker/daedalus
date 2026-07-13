# Security Standards

## Credentials

- No hardcoded secrets, API keys, tokens, or passwords in code
- No credentials in log output, error messages, or stack traces
- Credentials passed via environment variables or mounted secret files only

## Input validation

- All user-supplied or externally-sourced data must be validated before use
- Use allowlists over denylists for string validation
- File paths from external input must be sanitised (no `..` traversal)

## Dangerous functions

- `eval()`, `exec()`, `pickle.loads()` - never on untrusted data
- `subprocess` - never with shell=True on user-controlled input
- SQL queries - parameterised queries only, never string interpolation

## Data handling

- No PII or sensitive data in log output or test fixtures - use synthetic data only
- Return generic error messages to callers; log specifics internally
- No production credentials, connection strings, or secrets in any file - if the task requires them, stop and report it
