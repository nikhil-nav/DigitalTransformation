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

## Step 2 — Allow Azure App Service to reach PostgreSQL

The backend connects to Azure Database for PostgreSQL. By default the firewall blocks all Azure traffic — add a rule to permit it:

```bash
az postgres flexible-server firewall-rule create \
  --name propelpgdevdb \
  --resource-group rg-propel-dev \
  --rule-name AllowAzureServices \
  --start-ip-address 0.0.0.0 \
  --end-ip-address 0.0.0.0
```

Verify the rule exists:

```bash
az postgres flexible-server firewall-rule list \
  --name propelpgdevdb \
  --resource-group rg-propel-dev \
  --output table
```

---

## Step 3 — Create the Azure App Service plan

```bash
az appservice plan create \
  --name asp-digitrans-dev \
  --resource-group rg-propel-dev \
  --sku B1 \
  --is-linux
```

Use `--sku B2` or higher if you need more memory/CPU.

---

## Step 4 — Create the Web App (container)

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

### Set app settings (port + database)

Azure PostgreSQL enforces SSL — include `?sslmode=require` in the connection string:

```bash
az webapp config appsettings set \
  --name digital-transformation-dev-backend \
  --resource-group rg-propel-dev \
  --settings \
    WEBSITES_PORT=8000 \
    DATABASE_URL="postgresql://dev_user:PropelUser123@propelpgdevdb.postgres.database.azure.com:5432/digital_transformation_dev?sslmode=require" \
    POSTGRES_USER="dev_user" \
    POSTGRES_PASSWORD="PropelUser123" \
    POSTGRES_DB="digital_transformation_dev"
```

---

## Step 5 — Create a Service Principal for GitHub Actions

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

## Step 6 — Set GitHub secrets

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

# Paste the full JSON block from Step 5 when prompted
gh secret set AZURE_CREDENTIALS \
  --repo "$REPO"
```

The last command opens an editor (or reads from stdin). Paste the full JSON block from Step 5, then save/close.

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

## Step 7 — Verify secrets are set

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

## Step 8 — Trigger the workflow

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
| Exit code 127 on container start | `entrypoint.sh` not copied into image — ensure `COPY entrypoint.sh ./` is in `backend/Dockerfile` |
| `DATABASE_URL` not set / app crashes at startup | Set via `az webapp config appsettings set` (see Step 4) |
| PostgreSQL connection refused | Firewall rule missing — re-run Step 2 |
| PostgreSQL SSL error | Add `?sslmode=require` to `DATABASE_URL` (Azure PostgreSQL enforces SSL) |
| `unauthorized` on ACR push | Admin account not enabled — re-run `az acr update --admin-enabled true` |
| `App Service plan not found` | Verify `asp-digitrans-dev` exists: `az appservice plan list -g rg-propel-dev -o table` |
| Container logs empty | Download full logs: `az webapp log download --name digital-transformation-dev-backend --resource-group rg-propel-dev --log-file /tmp/logs.zip` |
| `WEBSITES_PORT` mismatch | Confirm app setting is `8000` to match FastAPI's `EXPOSE 8000` |
| Service principal permission denied | Ensure the SP has `Contributor` on `rg-propel-dev` and also `AcrPush` on the ACR |

### Get container logs

```bash
az webapp log download \
  --name digital-transformation-dev-backend \
  --resource-group rg-propel-dev \
  --log-file /tmp/backend-logs.zip

unzip -o /tmp/backend-logs.zip -d /tmp/backend-logs/
cat /tmp/backend-logs/LogFiles/StartupLogs/*_failure.log
cat /tmp/backend-logs/LogFiles/*_docker.log | tail -100
```

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
| `AZURE_WEBAPP_NAME` | `digital-transformation-dev-backend` (name chosen in Step 4) |
