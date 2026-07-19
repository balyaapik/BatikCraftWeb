#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${1:-${PROJECT_ID:-}}"
REGION="${REGION:-asia-southeast2}"
GITHUB_REPOSITORY="${GITHUB_REPOSITORY:-balyaapik/BatikCraftWeb}"
GITHUB_REPOSITORY_ID="1302937681"
GITHUB_OWNER_ID="9858800"
ARTIFACT_REPOSITORY="batikcraft"
DEPLOYER_SA_NAME="github-deployer"
RUNTIME_SA_NAME="batikcraft-runtime"
POOL_ID="github-actions"
PROVIDER_ID="batikcraftweb"

if [[ -z "$PROJECT_ID" ]]; then
  echo "Usage: $0 FIREBASE_PROJECT_ID"
  echo "Or set PROJECT_ID before running this script."
  exit 1
fi

for command_name in gcloud firebase python3; do
  command -v "$command_name" >/dev/null 2>&1 || {
    echo "Required command not found: $command_name"
    exit 1
  }
done

echo "Configuring Firebase/Google Cloud project: $PROJECT_ID"
gcloud config set project "$PROJECT_ID" >/dev/null

PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
DEPLOYER_SA="${DEPLOYER_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
RUNTIME_SA="${RUNTIME_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

# Cloud Run requires billing to be linked even when usage remains inside free quotas.
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  iamcredentials.googleapis.com \
  sts.googleapis.com \
  firebase.googleapis.com \
  firebasehosting.googleapis.com \
  --project "$PROJECT_ID"

if ! gcloud artifacts repositories describe "$ARTIFACT_REPOSITORY" \
  --project "$PROJECT_ID" \
  --location "$REGION" >/dev/null 2>&1; then
  gcloud artifacts repositories create "$ARTIFACT_REPOSITORY" \
    --project "$PROJECT_ID" \
    --location "$REGION" \
    --repository-format docker \
    --description "BatikCraftWeb container images"
fi

if ! gcloud iam service-accounts describe "$DEPLOYER_SA" --project "$PROJECT_ID" >/dev/null 2>&1; then
  gcloud iam service-accounts create "$DEPLOYER_SA_NAME" \
    --project "$PROJECT_ID" \
    --display-name "BatikCraft GitHub deployer"
fi

if ! gcloud iam service-accounts describe "$RUNTIME_SA" --project "$PROJECT_ID" >/dev/null 2>&1; then
  gcloud iam service-accounts create "$RUNTIME_SA_NAME" \
    --project "$PROJECT_ID" \
    --display-name "BatikCraft Cloud Run runtime"
fi

for role in \
  roles/run.admin \
  roles/artifactregistry.writer \
  roles/firebasehosting.admin \
  roles/secretmanager.viewer \
  roles/serviceusage.serviceUsageConsumer; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member "serviceAccount:${DEPLOYER_SA}" \
    --role "$role" \
    --condition=None >/dev/null
 done

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member "serviceAccount:${RUNTIME_SA}" \
  --role roles/secretmanager.secretAccessor \
  --condition=None >/dev/null

gcloud iam service-accounts add-iam-policy-binding "$RUNTIME_SA" \
  --project "$PROJECT_ID" \
  --member "serviceAccount:${DEPLOYER_SA}" \
  --role roles/iam.serviceAccountUser >/dev/null

if ! gcloud iam workload-identity-pools describe "$POOL_ID" \
  --project "$PROJECT_ID" \
  --location global >/dev/null 2>&1; then
  gcloud iam workload-identity-pools create "$POOL_ID" \
    --project "$PROJECT_ID" \
    --location global \
    --display-name "GitHub Actions"
fi

if ! gcloud iam workload-identity-pools providers describe "$PROVIDER_ID" \
  --project "$PROJECT_ID" \
  --location global \
  --workload-identity-pool "$POOL_ID" >/dev/null 2>&1; then
  gcloud iam workload-identity-pools providers create-oidc "$PROVIDER_ID" \
    --project "$PROJECT_ID" \
    --location global \
    --workload-identity-pool "$POOL_ID" \
    --display-name "BatikCraftWeb GitHub Actions" \
    --issuer-uri "https://token.actions.githubusercontent.com/" \
    --attribute-mapping "google.subject=assertion.sub,attribute.repository_id=assertion.repository_id,attribute.repository_owner_id=assertion.repository_owner_id,attribute.ref=assertion.ref" \
    --attribute-condition "assertion.repository_id=='${GITHUB_REPOSITORY_ID}' && assertion.repository_owner_id=='${GITHUB_OWNER_ID}' && assertion.ref=='refs/heads/main'"
fi

WIF_PROVIDER="$(gcloud iam workload-identity-pools providers describe "$PROVIDER_ID" \
  --project "$PROJECT_ID" \
  --location global \
  --workload-identity-pool "$POOL_ID" \
  --format='value(name)')"

WIF_PRINCIPAL="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}/attribute.repository_id/${GITHUB_REPOSITORY_ID}"
gcloud iam service-accounts add-iam-policy-binding "$DEPLOYER_SA" \
  --project "$PROJECT_ID" \
  --member "$WIF_PRINCIPAL" \
  --role roles/iam.workloadIdentityUser >/dev/null

upsert_secret() {
  local secret_name="$1"
  local secret_value="$2"

  if gcloud secrets describe "$secret_name" --project "$PROJECT_ID" >/dev/null 2>&1; then
    printf '%s' "$secret_value" | gcloud secrets versions add "$secret_name" \
      --project "$PROJECT_ID" \
      --data-file=- >/dev/null
  else
    printf '%s' "$secret_value" | gcloud secrets create "$secret_name" \
      --project "$PROJECT_ID" \
      --replication-policy automatic \
      --data-file=- >/dev/null
  fi
}

DJANGO_SECRET_KEY="${DJANGO_SECRET_KEY:-$(python3 -c 'import secrets; print(secrets.token_urlsafe(60))')}"
if [[ -z "${DATABASE_URL:-}" ]]; then
  read -r -s -p "PostgreSQL DATABASE_URL (for example Neon): " DATABASE_URL
  echo
fi

if [[ -z "$DATABASE_URL" ]]; then
  echo "DATABASE_URL cannot be empty."
  exit 1
fi

upsert_secret "django-secret-key" "$DJANGO_SECRET_KEY"
upsert_secret "database-url" "$DATABASE_URL"
unset DJANGO_SECRET_KEY DATABASE_URL

if ! firebase hosting:sites:get "$PROJECT_ID" --project "$PROJECT_ID" >/dev/null 2>&1; then
  echo "Creating the default Firebase Hosting site..."
  firebase hosting:sites:create "$PROJECT_ID" --project "$PROJECT_ID"
fi

if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  gh variable set GCP_PROJECT_ID --repo "$GITHUB_REPOSITORY" --body "$PROJECT_ID"
  gh variable set GCP_RUNTIME_SERVICE_ACCOUNT --repo "$GITHUB_REPOSITORY" --body "$RUNTIME_SA"
  gh secret set GCP_WORKLOAD_IDENTITY_PROVIDER --repo "$GITHUB_REPOSITORY" --body "$WIF_PROVIDER"
  gh secret set GCP_SERVICE_ACCOUNT --repo "$GITHUB_REPOSITORY" --body "$DEPLOYER_SA"
  echo "GitHub Actions variables and secrets configured."
else
  cat <<EOF

Set the following values in GitHub repository settings:

Repository variables:
  GCP_PROJECT_ID=$PROJECT_ID
  GCP_RUNTIME_SERVICE_ACCOUNT=$RUNTIME_SA

Repository secrets:
  GCP_WORKLOAD_IDENTITY_PROVIDER=$WIF_PROVIDER
  GCP_SERVICE_ACCOUNT=$DEPLOYER_SA
EOF
fi

cat <<EOF

Bootstrap complete.

Firebase Hosting URL after deployment:
  https://${PROJECT_ID}.web.app

Run the GitHub Actions workflow after this branch is merged:
  Deploy Firebase and Cloud Run
EOF
