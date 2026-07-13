# Testing Standards

## Coverage

- Every public function must have at least one test
- Cover: happy path, at least one edge case, at least one invalid input
- For functions that return None on error, test the None case explicitly

## Test structure

- One test file per module: `test_<module>.py`
- Test function names: `test_<function>_<scenario>` (e.g. `test_coerce_numeric_with_none`)
- Use `pytest.mark.parametrize` for value-driven cases (3+ similar test cases)
- No test should depend on another test's side effects - each test is independent

## Assertions

- Assert the specific value, not just truthiness: `assert result == 0.0` not `assert result`
- For exception tests: `with pytest.raises(ValueError):`

## What not to test

- Private functions (prefix `_`) - test via the public interface
- Implementation details - test behaviour, not how it's achieved
