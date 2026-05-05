# NHSE Clinical Data Pathology API

Our core programming language is Python.

Our docs are in README.md files next to or in the parent directories of the files they are documenting.

This repository is a cloud-hosted service (AWS Lambda) that provides a FHIR-based replacement for legacy PMIP EDIFACT pathology messaging flows, implementing the DAPB4101 information standard via the Pathology FHIR Implementation Guide.

The API:

* Receives FHIR Document Bundle payloads from laboratory/consumer systems containing pathology test results
* Validates bundles against the Pathology FHIR Implementation Guide
* Forwards validated requests to downstream provider systems (PDM — Pathology Data Manager, and MNS — Message Notification Service)
* Authenticates requests via NHS England's APIM layer using OAuth2/JWT

The repository contains the OpenAPI specification (openapi.yaml), Python Lambda handler, and test suites (unit, acceptance, integration, schema, contract).

`make build` will build the codebase so that it is ready for local testing. `make test-local` will run all tests that can successfully run locally.

For remote testing, a draft PR must have been created and the PR number added to the .env.remote file which should not be accessed by copilot. After building the container and adding the PR number to the .env.remote file, `make test-remote` will run all tests against the lambda deployed in AWS and capture their coverage.

To run non-unit tests individually or at a directory level, you will need to do so from the `pathology-api` directory. You will also need to obtain an APIGEE token and then pass it directly to pytest. E.g.
`poetry run pytest tests/contract/ -v --env="remote" --api-name=pathology-laboratory-reporting --proxy-name=pathology-laboratory-reporting--internal-dev--pathology-laboratory-reporting-pr-XX --apigee-access-token=$(proxygen pytest-nhsd-apim get-token | jq -r '.pytest_nhsd_apim_token')`

If the PR number is needed (e.g. to construct the `--proxy-name` flag) and you do not have it, ask the user to provide it before running the command.

The schema for this API can be found in `pathology-api/openapi.yaml`.

## Code reviews

When reviewing code, ensure you compare the changes made to files to all README.md containing directory structures, and update the directory structures accordingly.

## Docstrings and comments

* Use precise variable and function names to reduce the need for comments
* Use docstrings on high-level functions and classes to explain their purpose, inputs, outputs, and any side effects
* Avoid comments that state the obvious or repeat what the code does; instead, focus on explaining the intent behind the code, the reasons for non-obvious decisions, and any important trade-offs or constraints

## Formatting

* For Python files, use 4-space indentation and keep line lengths within Ruff limits (default 88 chars unless configured otherwise)
* For Python changes, keep code compatible with both `ruff format` and `ruff check`
* Let Ruff manage import ordering (isort rules are enabled via Ruff)
* Follow `.editorconfig` basics for all files: UTF-8, LF line endings, final newline, and no trailing whitespace
* Use tabs (not spaces) in `Makefile` and `.mk` files, per `.editorconfig`
* When wrapping a long string value inside parentheses, do not add a trailing comma if the value must remain a string
* For Markdown changes, keep content compatible with markdown lint checks (rules in `scripts/config/.markdownlint.yaml`; enforced by `scripts/githooks/check-markdown-format.sh`)
* For Markdown prose, write content that passes Vale English usage checks (rules in `scripts/config/vale/vale.ini`; enforced by `scripts/githooks/check-english-usage.sh`)

## Commits

Prepend `[AI-generated]` to the commit message when committing changes made by an AI agent.

## Security

This repository is currently public. Do not commit any secrets, tokens or credentials.
