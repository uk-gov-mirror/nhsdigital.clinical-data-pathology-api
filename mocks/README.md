# Mocks Lambda

## Testing

There are currently only unit tests for the mocks

### Continuous

All tests run automatically in the CI/CD pipeline on every push and pull request. **Any test failure at any level will cause the pipeline to fail and prevent the PR from being merged.**

Additionally, code coverage is collected from all test types, merged, and analyzed by SonarCloud. PRs must meet minimum coverage thresholds to pass quality gates.

### Quick Test Commands

```bash
# Run all unit, contract, and schema tests
poetry run pytest -v
```

## Project Structure

```text
mocks
├── src
│   └── apim_mock
│       ├── __init__.py
│       ├── auth_check.py
│       └── handler.py
├── tests
│   └── apim_mock
├── README.md
├── lambda_handler.py
└── pyproject.toml
```

### Implementing a new mock

Create a new package under the `src` folder
