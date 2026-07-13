# Coding Standards

## Python

- All public functions and methods must have type hints on parameters and return values
- Use `Optional[X]` (or `X | None` for Python 3.10+) for values that can be None
- One-line docstrings on all public functions - describe what it returns, not what it does
- No multi-line docstrings unless the function has non-obvious parameters
- No comments explaining what the code does - only comments explaining *why* a non-obvious choice was made
- No trailing whitespace; files end with a newline
- `snake_case` for functions and variables, `PascalCase` for classes, `UPPER_SNAKE` for constants

## Error handling

- Validate at system boundaries (user input, external API responses) - not internally
- Raise specific exceptions, not bare `Exception`
- Do not swallow exceptions silently

## General

- Functions do one thing - if you need "and" to describe it, split it
- No repeated logic - if the same pattern appears more than twice, extract a helper or constant
- No magic numbers - assign them to named constants
- No dead code - if it's not used, delete it
