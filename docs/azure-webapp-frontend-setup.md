# Azure Web App Setup — Frontend Container Deployment

This guide covers creating the GitHub Actions workflow for the frontend and provisioning the Azure App Service, mirroring the backend setup.

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
| Docker image name | `plan-digital-transformation-dev-frontend` |
| Frontend port | `3000` |
| Backend App Service URL | `https://digital-transformation-dev-backend.azurewebsites.net` |
| GitHub repo | `<owner>/<repo>` — replace in commands below |

---

## Step 1 — Create the GitHub Actions workflow

Create `.github/workflows/frontend.yaml`:

```yaml
name: Frontend CI/CD

on:
  push:
    branches: [main, develop]
    paths:
      - "frontend/**"
      - ".github/workflows/frontend.yaml"
  pull_request:
    branches: [main]
    paths:
      - "frontend/**"
      - ".github/workflows/frontend.yaml"

env:
  IMAGE_NAME: plan-digital-transformation-dev-frontend

jobs:
  build-and-deploy:
    name: Build, Push & Deploy
    runs-on: ubuntu-latest
    if: github.event_name == 'push'

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Log in to Azure Container Registry
        uses: docker/login-action@v3
        with:
          registry: ${{ secrets.ACR_LOGIN_SERVER }}
          username: ${{ secrets.ACR_USERNAME }}
          password: ${{ secrets.ACR_PASSWORD }}

      - name: Build and push image to ACR
        uses: docker/build-push-action@v6
        with:
          context: ./frontend
          push: true
          tags: |
            ${{ secrets.ACR_LOGIN_SERVER }}/${{ env.IMAGE_NAME }}:sha-${{ github.sha }}
            ${{ secrets.ACR_LOGIN_SERVER }}/${{ env.IMAGE_NAME }}:latest
          cache-from: type=gha
          cache-to: type=gha,mode=max

      - name: Log in to Azure
        uses: azure/login@v2
        with:
          creds: ${{ secrets.AZURE_CREDENTIALS }}

      - name: Deploy to Azure App Service
        uses: azure/webapps-deploy@v3
        with:
          app-name: ${{ secrets.AZURE_FRONTEND_WEBAPP_NAME }}
          images: ${{ secrets.ACR_LOGIN_SERVER }}/${{ env.IMAGE_NAME }}:sha-${{ github.sha }}
```

> The frontend workflow reuses the same `ACR_*` and `AZURE_CREDENTIALS` secrets as the backend. Only `AZURE_FRONTEND_WEBAPP_NAME` is new.

---

## Step 2 — Create the App Service plan

Skip this step if `asp-digitrans-dev` already exists from the backend setup. Verify first:

```bash
az appservice plan list --resource-group rg-propel-dev --output table
```

If it does not exist, create it:

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

Next.js listens on port 3000. The `BACKEND_URL` env var points the frontend proxy at the backend App Service:

```bash
az webapp config appsettings set \
  --name digital-transformation-dev-frontend \
  --resource-group rg-propel-dev \
  --settings \
    WEBSITES_PORT=3000 \
    BACKEND_URL=https://digital-transformation-dev-backend.azurewebsites.net
```

---

## Step 4 — Set the new GitHub secret

The backend setup already added `ACR_LOGIN_SERVER`, `ACR_USERNAME`, `ACR_PASSWORD`, and `AZURE_CREDENTIALS`. Only one new secret is needed:

```bash
REPO="<owner>/<repo>"

gh secret set AZURE_FRONTEND_WEBAPP_NAME \
  --repo "$REPO" \
  --body "digital-transformation-dev-frontend"
```

---

## Step 5 — Verify all secrets

```bash
gh secret list --repo "$REPO"
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
gh run list --repo "$REPO" --workflow frontend.yaml
gh run watch --repo "$REPO"
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
| Container fails to start | Check logs: `az webapp log tail --name digital-transformation-dev-frontend --resource-group rg-propel-dev` |
| `WEBSITES_PORT` mismatch | Confirm app setting is `3000` to match Next.js `EXPOSE 3000` |
| `/api/*` calls fail | Verify `BACKEND_URL` app setting points to the backend App Service URL |
| `App Service plan not found` | Verify `asp-digitrans-dev` exists: `az appservice plan list -g rg-propel-dev -o table` |

---

## Summary — secrets required by the frontend workflow

| Secret | Value | Shared with backend? |
|--------|-------|----------------------|
| `ACR_LOGIN_SERVER` | `navikenzpropeldev.azurecr.io` | Yes |
| `ACR_USERNAME` | `navikenzpropeldev` | Yes |
| `ACR_PASSWORD` | from `az acr credential show` | Yes |
| `AZURE_CREDENTIALS` | JSON from `az ad sp create-for-rbac` | Yes |
| `AZURE_FRONTEND_WEBAPP_NAME` | `digital-transformation-dev-frontend` | No — new |
