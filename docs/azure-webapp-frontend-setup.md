# Azure Web App Setup — Frontend Container Deployment

This guide covers provisioning the Azure App Service for the frontend and wiring GitHub secrets so the CI/CD workflow builds, pushes, and deploys the Next.js container automatically.

The workflow file `.github/workflows/frontend.yaml` is already committed to the repo. The Azure Web App `digital-transformation-dev-frontend` is already created. This doc serves as a reference and re-creation guide.

---

## Prerequisites

Same as backend — Azure CLI and GitHub CLI logged in:

```bash
az login
gh auth login
```

---

## Fixed values

| Item | Value |
|------|-------|
| Resource Group | `rg-propel-dev` |
| ACR name | `navikenzpropeldev` |
| App Service plan | `asp-digitrans-dev` (shared with backend) |
| Docker image name | `plan-digital-transformation-dev-frontend` |
| Frontend port | `3000` |
| Frontend App Service | `digital-transformation-dev-frontend` |
| Backend App Service URL | `https://digital-transformation-dev-backend.azurewebsites.net` |
| GitHub repo | `Navikenz/DigitalTransformation` |

---

## How BACKEND_URL works

`frontend/next.config.ts` reads `BACKEND_URL` at server startup and uses it to proxy all `/api/*` requests to the backend:

```ts
const backend = process.env.BACKEND_URL ?? "http://localhost:8000";

rewrites: () => [{ source: "/api/:path*", destination: `${backend}/api/:path*` }]
```

Setting `BACKEND_URL` as an Azure App Service app setting injects it at runtime — no rebuild needed when the backend URL changes.

---

## Step 1 — GitHub Actions workflow

The file `.github/workflows/frontend.yaml` is already in the repo. It:
- Triggers on pushes to `main`/`develop` that touch `frontend/**`
- Builds the Docker image from `./frontend`
- Pushes two tags to ACR: `sha-<commit>` and `latest`
- Deploys the SHA-tagged image to `AZURE_FRONTEND_WEBAPP_NAME`

Reuses the same `ACR_*` and `AZURE_CREDENTIALS` secrets as the backend. Only `AZURE_FRONTEND_WEBAPP_NAME` is new.

---

## Step 2 — Create the App Service plan

Skip if `asp-digitrans-dev` already exists (it does if the backend is set up). Verify:

```bash
az appservice plan list --resource-group rg-propel-dev --output table
```

If missing, create it:

```bash
az appservice plan create \
  --name asp-digitrans-dev \
  --resource-group rg-propel-dev \
  --sku B1 \
  --is-linux
```

---

## Step 3 — Create the Web App (container)

```bash
az webapp create \
  --name digital-transformation-dev-frontend \
  --resource-group rg-propel-dev \
  --plan asp-digitrans-dev \
  --deployment-container-image-name navikenzpropeldev.azurecr.io/plan-digital-transformation-dev-frontend:latest
```

> App will be live at: `https://digital-transformation-dev-frontend.azurewebsites.net`

### Configure the container registry on the Web App

```bash
ACR_PASSWORD=$(az acr credential show \
  --name navikenzpropeldev \
  --resource-group rg-propel-dev \
  --query "passwords[0].value" \
  --output tsv)

az webapp config container set \
  --name digital-transformation-dev-frontend \
  --resource-group rg-propel-dev \
  --container-registry-url https://navikenzpropeldev.azurecr.io \
  --container-registry-user navikenzpropeldev \
  --container-registry-password "$ACR_PASSWORD"
```

### Set the listening port and backend URL

```bash
az webapp config appsettings set \
  --name digital-transformation-dev-frontend \
  --resource-group rg-propel-dev \
  --settings \
    WEBSITES_PORT=3000 \
    BACKEND_URL="https://digital-transformation-dev-backend.azurewebsites.net"
```

---

## Step 4 — Set the GitHub secret

The backend setup already added `ACR_LOGIN_SERVER`, `ACR_USERNAME`, `ACR_PASSWORD`, and `AZURE_CREDENTIALS`. Only one new secret is needed:

```bash
gh secret set AZURE_FRONTEND_WEBAPP_NAME \
  --repo "Navikenz/DigitalTransformation" \
  --body "digital-transformation-dev-frontend"
```

---

## Step 5 — Verify all secrets

```bash
gh secret list --repo "Navikenz/DigitalTransformation"
```

Expected output (combined with backend secrets):

```
ACR_LOGIN_SERVER              Updated ...
ACR_PASSWORD                  Updated ...
ACR_USERNAME                  Updated ...
AZURE_CREDENTIALS             Updated ...
AZURE_FRONTEND_WEBAPP_NAME    Updated ...
AZURE_WEBAPP_NAME             Updated ...
```

---

## Step 6 — Trigger the workflow

Push any change to `frontend/` on the `main` or `develop` branch:

```bash
git push origin main
```

Monitor the run:

```bash
gh run list --repo "Navikenz/DigitalTransformation" --workflow frontend.yaml
gh run watch --repo "Navikenz/DigitalTransformation"
```

After a successful run, the app is live at:

```
https://digital-transformation-dev-frontend.azurewebsites.net
```

---

## Troubleshooting

| Symptom | Check |
|---------|-------|
| `unauthorized` on ACR push | Admin account not enabled — `az acr update --name navikenzpropeldev --admin-enabled true` |
| Container fails to start (exit 127) | Check `entrypoint.sh` or startup command is present in the image |
| Container fails to start (exit 255) | Download logs and check the failure log (see below) |
| `WEBSITES_PORT` mismatch | Confirm app setting is `3000` to match Next.js `EXPOSE 3000` |
| `/api/*` calls return 502/timeout | Verify `BACKEND_URL` app setting: `az webapp config appsettings list --name digital-transformation-dev-frontend --resource-group rg-propel-dev --output table` |
| `App Service plan not found` | Verify `asp-digitrans-dev` exists: `az appservice plan list -g rg-propel-dev -o table` |

### Get container logs

```bash
az webapp log download \
  --name digital-transformation-dev-frontend \
  --resource-group rg-propel-dev \
  --log-file /tmp/frontend-logs.zip

unzip -o /tmp/frontend-logs.zip -d /tmp/frontend-logs/
cat /tmp/frontend-logs/LogFiles/StartupLogs/*_failure.log
cat /tmp/frontend-logs/LogFiles/*_docker.log | tail -100
```

### Update BACKEND_URL without redeploying

If the backend URL changes, update the app setting and restart — no image rebuild needed:

```bash
az webapp config appsettings set \
  --name digital-transformation-dev-frontend \
  --resource-group rg-propel-dev \
  --settings BACKEND_URL="https://<new-backend-url>"

az webapp restart \
  --name digital-transformation-dev-frontend \
  --resource-group rg-propel-dev
```

---

## Summary — secrets required by the frontend workflow

| Secret | Value | Shared with backend? |
|--------|-------|----------------------|
| `ACR_LOGIN_SERVER` | `navikenzpropeldev.azurecr.io` | Yes |
| `ACR_USERNAME` | `navikenzpropeldev` | Yes |
| `ACR_PASSWORD` | from `az acr credential show` | Yes |
| `AZURE_CREDENTIALS` | JSON from `az ad sp create-for-rbac` | Yes |
| `AZURE_FRONTEND_WEBAPP_NAME` | `digital-transformation-dev-frontend` | No — new |
