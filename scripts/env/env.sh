#!/bin/bash
set -e

PATHOLOGY_API_ENV_FILE_NAME=".env.pathology-api.local"
MOCK_ENV_FILE_NAME=".env.mock.local"


AWS_PROFILE=AWS-CDSPath-DEV_DevAccess-859065147940

cat > "$PATHOLOGY_API_ENV_FILE_NAME" <<EOF
CLIENT_TIMEOUT=1m
APIM_PRIVATE_KEY_NAME=/cds/pathology/dev/apim/private-key
APIM_API_KEY_NAME=/cds/pathology/dev/apim/api-key
APIM_TOKEN_EXPIRY_THRESHOLD=10m
APIM_KEY_ID=DEV-1
APIM_TOKEN_URL=http://mocks-api-gateway:5000/apim/oauth2/token
PDM_BUNDLE_URL=http://mocks-api-gateway:5000/pdm/FHIR/R4/Bundle
MNS_EVENT_URL=http://mocks-api-gateway:5000/mns/events
AWS_PROFILE=$AWS_PROFILE
EOF

cat > "$MOCK_ENV_FILE_NAME" <<EOF
AUTH_URL=http://mocks-api-gateway:5000/apim/oauth2/token
PUBLIC_KEY_URL=https://pki.dev.endpoints.pathology-laboratory-reporting.national.nhs.uk/pathology.jwks
API_KEY_SECRET_NAME=/cds/pathology/dev/jwks/secret
MOCK_TABLE_NAME=mock_services_dev
DDB_INDEX_TAG=$(git rev-parse --abbrev-ref HEAD)
AWS_PROFILE=$AWS_PROFILE
EOF
