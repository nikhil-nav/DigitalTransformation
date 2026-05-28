# Azure Web App Setup — Backend Container Deployment

This guide covers creating an Azure App Service (Web App for Containers) and wiring all required GitHub secrets so the existing CI/CD workflow can build, push, and deploy the backend image automatically.

---

## Prerequisites

| Tool | Install |
|------|---------|
| Azure CLI | `brew install azure-cli` (macOS) or https://aka.ms/installazurecliwindows |
| GitHub CLI | `brew install gh` |

Log in to both:

```bash
az login
gh auth login
```

---

## Fixed values (already exist)

| Item | Value |
|------|-------|
| Resource Group | `rg-propel-dev` |
| ACR name | `navikenzpropeldev` |
| Docker image name | `plan-digital-transformation-dev-backend` |
| GitHub repo | `<owner>/<repo>` — replace in commands below |

---

## Step 1 — Collect ACR credentials

```bash
# Login server (e.g. navikenzpropeldev.azurecr.io)
az acr show \
  --name navikenzpropeldev \
  --resource-group rg-propel-dev \
  --query loginServer \
  --output tsv

# Enable admin account (required for username/password auth)
az acr update \
  --name navikenzpropeldev \
  --resource-group rg-propel-dev \
  --admin-enabled true

# Admin username
az acr credential show \
  --name navikenzpropeldev \
  --resource-group rg-propel-dev \
  --query username \
  --output tsv

# Admin password (use password, not password2)
az acr credential show \
  --name navikenzpropeldev \
  --resource-group rg-propel-dev \
  --query "passwords[0].value" \
  --output tsv
```

Copy and save these three values — you will need them in Step 4.

---

## Step 2 — Create the Azure App Service plan

```bash
az appservice plan create \
  --name asp-digitrans-dev \
  --resource-group rg-propel-dev \
  --sku B1 \
  --is-linux
```

Use `--sku B2` or higher if you need more memory/CPU.

---

## Step 3 — Create the Web App (container)

```bash
az webapp create \
  --name digital-transformation-dev-backend \
  --resource-group rg-propel-dev \
  --plan asp-digitrans-dev \
  --deployment-container-image-name navikenzpropeldev.azurecr.io/plan-digital-transformation-dev-backend:latest
```

> The `--name` value becomes the app's subdomain: `digital-transformation-dev-backend.azurewebsites.net`.
> It must be globally unique — change it if the name is taken.

### Configure the container registry on the Web App

```bash
ACR_PASSWORD=$(az acr credential show \
  --name navikenzpropeldev \
  --resource-group rg-propel-dev \
  --query "passwords[0].value" \
  --output tsv)

az webapp config container set \
  --name digital-transformation-dev-backend \
  --resource-group rg-propel-dev \
  --container-registry-url https://navikenzpropeldev.azurecr.io \
  --container-registry-user navikenzpropeldev \
  --container-registry-password "$ACR_PASSWORD"
```

### Set the listening port (FastAPI runs on 8000)

```bash
az webapp config appsettings set \
  --name digital-transformation-dev-backend \
  --resource-group rg-propel-dev \
  --settings WEBSITES_PORT=8000
```

---

## Step 4 — Create a Service Principal for GitHub Actions

The `AZURE_CREDENTIALS` secret gives the workflow permission to call `azure/login` and `azure/webapps-deploy`.

```bash
SUBSCRIPTION_ID=$(az account show --query id --output tsv)

az ad sp create-for-rbac \
  --name sp-propel-dev-github \
  --role contributor \
  --scopes /subscriptions/$SUBSCRIPTION_ID/resourceGroups/rg-propel-dev \
  --sdk-auth
```

The command prints a JSON block like:

```json
{
  "clientId": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "clientSecret": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "subscriptionId": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "tenantId": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "activeDirectoryEndpointUrl": "https://login.microsoftonline.com",
  "resourceManagerEndpointUrl": "https://management.azure.com/",
  "activeDirectoryGraphResourceId": "https://graph.windows.net/",
  "sqlManagementEndpointUrl": "https://management.core.windows.net:8443/",
  "galleryEndpointUrl": "https://gallery.azure.com/",
  "managementEndpointUrl": "https://management.core.windows.net/"
}
```

Copy the **entire JSON block** — this is the value for `AZURE_CREDENTIALS`.

---

## Step 5 — Set GitHub secrets

Replace `<owner>/<repo>` with your actual GitHub repository (e.g. `Navikenz/DigitalTransformation`).

```bash
REPO="<owner>/<repo>"

# ACR secrets
gh secret set ACR_LOGIN_SERVER \
  --repo "$REPO" \
  --body "navikenzpropeldev.azurecr.io"

gh secret set ACR_USERNAME \
  --repo "$REPO" \
  --body "navikenzpropeldev"

gh secret set ACR_PASSWORD \
  --repo "$REPO" \
  --body "$(az acr credential show \
    --name navikenzpropeldev \
    --resource-group rg-propel-dev \
    --query "passwords[0].value" \
    --output tsv)"

# Azure deployment secrets
gh secret set AZURE_WEBAPP_NAME \
  --repo "$REPO" \
  --body "digital-transformation-dev-backend"

# Paste the full JSON block from Step 4 when prompted
gh secret set AZURE_CREDENTIALS \
  --repo "$REPO"
```

The last command opens an editor (or reads from stdin). Paste the full JSON block from Step 4, then save/close.

Alternatively, pipe it directly:

```bash
gh secret set AZURE_CREDENTIALS \
  --repo "$REPO" \
  --body '{
  "clientId": "...",
  "clientSecret": "...",
  "subscriptionId": "...",
  "tenantId": "...",
  ...
}'
```

---

## Step 6 — Verify secrets are set

```bash
gh secret list --repo "$REPO"
```

Expected output:

```
ACR_LOGIN_SERVER    Updated ...
ACR_PASSWORD        Updated ...
ACR_USERNAME        Updated ...
AZURE_CREDENTIALS   Updated ...
AZURE_WEBAPP_NAME   Updated ...
```

---

## Step 7 — Trigger the workflow

Push any change to `backend/` on the `main` or `develop` branch:

```bash
git push origin main
```

Monitor the run:

```bash
gh run list --repo "$REPO" --workflow backend.yaml
gh run watch --repo "$REPO"
```

After a successful run, the app is live at:

```
https://digital-transformation-dev-backend.azurewebsites.net
```

---

## Troubleshooting

| Symptom | Check |
|---------|-------|
| `unauthorized` on ACR push | Admin account not enabled — re-run the `az acr update --admin-enabled true` command |
| `App Service plan not found` | Verify `asp-digitrans-dev` exists: `az appservice plan list -g rg-propel-dev -o table` |
| Container fails to start | Check logs: `az webapp log tail --name digital-transformation-dev-backend --resource-group rg-propel-dev` |
| `WEBSITES_PORT` mismatch | Confirm app setting is `8000` to match FastAPI's `EXPOSE 8000` |
| Service principal permission denied | Ensure the SP has `Contributor` on `rg-propel-dev` and also `AcrPush` on the ACR |

### Grant AcrPush to the service principal (if needed)

```bash
ACR_ID=$(az acr show --name navikenzpropeldev --resource-group rg-propel-dev --query id --output tsv)
SP_ID=$(az ad sp list --display-name sp-propel-dev-github --query "[0].appId" --output tsv)

az role assignment create \
  --assignee "$SP_ID" \
  --role AcrPush \
  --scope "$ACR_ID"
```

---

## Summary — secrets required by the workflow

| Secret | Source |
|--------|--------|
| `ACR_LOGIN_SERVER` | `navikenzpropeldev.azurecr.io` (static) |
| `ACR_USERNAME` | `az acr credential show --query username` |
| `ACR_PASSWORD` | `az acr credential show --query "passwords[0].value"` |
| `AZURE_CREDENTIALS` | JSON from `az ad sp create-for-rbac --sdk-auth` |
| `AZURE_WEBAPP_NAME` | `digital-transformation-dev-backend` (name chosen in Step 3) |
