#!/usr/bin/env bash
set -euo pipefail

secretName="$1"

echo "Retrieving secret from AWS Secrets Manager: $secretName ..." >&2

SECRET_VALUE=$(aws secretsmanager get-secret-value --secret-id "$secretName" --query 'SecretString' --output text)
echo "${SECRET_VALUE}"
