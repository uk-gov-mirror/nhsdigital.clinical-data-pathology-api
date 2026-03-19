#!/bin/bash

set -euo pipefail

# Generic test runner script
# Usage: run-test.sh <test-type>
# Where test-type is one of: unit, integration, contract, schema, acceptance
#
# Behaviour varies by environment (ENV variable, loaded from .env):
#   ENV=local  → runs pytest directly against the local Lambda/RIE
#   ENV=remote → passes --env=remote, --api-name, --proxy-name, and
#                --apigee-access-token to pytest so the pytest-nhsd-apim
#                plugin can authenticate with the APIM proxy.
#
#                Unit tests always run in local mode regardless of ENV.

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <test-type>"
  echo "Where test-type is one of: unit, integration, contract, schema, acceptance"
  exit 1
fi

TEST_TYPE="$1"

# Validate test type early
if [[ ! "$TEST_TYPE" =~ ^(unit|integration|contract|schema|acceptance)$ ]]; then
  echo "Error: Unknown test type '$TEST_TYPE'"
  echo "Valid types are: unit, integration, contract, schema, acceptance"
  exit 1
fi

cd "$(git rev-parse --show-toplevel)"

# Determine test path based on test type
if [[ "$TEST_TYPE" = "unit" ]]; then
  TEST_PATH="src/ test_*.py"
else
  TEST_PATH="tests/${TEST_TYPE}/"
fi

cd pathology-api
mkdir -p test-artefacts

echo "Running ${TEST_TYPE} tests for pathology-api..."

# Set coverage path based on test type
if [[ "$TEST_TYPE" = "unit" ]]; then
  COV_PATH="."
else
  COV_PATH="src/pathology_api"
fi

if [[ "$ENV" = "remote" ]] && [[ "$TEST_TYPE" != "unit" ]]; then
  # Note: TEST_PATH is intentionally unquoted to allow glob expansion for unit tests
  poetry run pytest ${TEST_PATH} --env="remote" -v \
    --api-name="${PROXYGEN_API_NAME}" --proxy-name="${PROXYGEN_API_NAME}--internal-dev--${PROXYGEN_API_NAME}-pr-${PR_NUMBER}" \
    --apigee-access-token="${APIGEE_ACCESS_TOKEN}" \
    --cov="${COV_PATH}" \
    --cov-report=html:test-artefacts/coverage-html \
    --cov-report=term \
    --junit-xml="test-artefacts/${TEST_TYPE}-tests.xml" \
    --html="test-artefacts/${TEST_TYPE}-tests.html" --self-contained-html
else
  poetry run pytest ${TEST_PATH} -v \
    --cov="${COV_PATH}" \
    --cov-report=html:test-artefacts/coverage-html \
    --cov-report=term \
    --junit-xml="test-artefacts/${TEST_TYPE}-tests.xml" \
    --html="test-artefacts/${TEST_TYPE}-tests.html" --self-contained-html
fi


# Save coverage data file for merging
mv .coverage "test-artefacts/coverage.${TEST_TYPE}"

if [[ "$TEST_TYPE" = "unit" ]]; then
  cd ..
  cd mocks
  mkdir -p test-artefacts
  echo "Running ${TEST_TYPE} tests for mocks..."
    # Note: TEST_PATH is intentionally unquoted to allow glob expansion for unit tests
  poetry run pytest ${TEST_PATH} -v \
    --cov=${COV_PATH} \
    --cov-report=html:test-artefacts/coverage-html \
    --cov-report=term \
    --junit-xml="test-artefacts/${TEST_TYPE}-tests.xml" \
    --html="test-artefacts/${TEST_TYPE}-tests.html" --self-contained-html

  mv .coverage "test-artefacts/coverage.${TEST_TYPE}"
fi


