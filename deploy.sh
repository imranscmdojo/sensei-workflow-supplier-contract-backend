#!/bin/bash
set -e

PROJECT_ID="test-rag-corpus-project"
FIREBASE_PROJECT_ID="sensei-ask-project"
REGION="us-west1"
SERVICE_NAME="sensei-workflow-supplier-contract-container"

# Load .env if present (SMTP_HOST/PORT/USER/FROM for feedback emails)
if [ -f .env ]; then
  set -a; source .env; set +a
fi

echo "Deploying $SERVICE_NAME to Cloud Run..."

# Build and deploy
gcloud run deploy $SERVICE_NAME \
  --source . \
  --project $PROJECT_ID \
  --region $REGION \
  --platform managed \
  --allow-unauthenticated \
  --memory 2Gi \
  --cpu 2 \
  --timeout 3600 \
  --set-env-vars \
  PROJECT_ID=$PROJECT_ID,FIREBASE_PROJECT_ID=$FIREBASE_PROJECT_ID,LOCATION=$REGION,\
RAG_CORPUS=projects/test-rag-corpus-project/locations/us-west1/ragCorpora/137359788634800128,\
APP_BASE_URL="${APP_BASE_URL:-https://www.scmsensei.ai}",\
SMTP_HOST="${SMTP_HOST:-smtp.gmail.com}",SMTP_PORT="${SMTP_PORT:-587}",\
SMTP_USER="${SMTP_USER:-muhammad@scmdojo.com}",SMTP_FROM="${SMTP_FROM:-}" \
  --update-secrets "SMTP_PASS=smtp-pass:latest"

echo "Deployment complete!"
echo "Service URL: https://$SERVICE_NAME-214011868588.us-west1.run.app"