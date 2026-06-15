# AI Scout — Infrastructure as Code (Bicep)

Reproducible definition of every Azure resource for AI Scout (resource group `rg-ai-scout`).
This is the **source of truth** going forward — change infra here, not in the Portal/CLI.

## Files
- `main.bicep` — all resources + passwordless role assignments (resource-group scoped)
- `main.bicepparam` — production values (names, locations, your object ID, GitHub repo/branch)

## What's defined
KB + Function storage (shared-key disabled), the GitHub-OIDC user-assigned identity + federated
credential, the Foundry account/project/`nano` deployment (local auth disabled), ACS email
(passwordless), the Flex-Consumption Function + App Insights, and all RBAC role assignments
(Blob/Table Data Contributor, Cognitive Services OpenAI User, Communication & Email Service Owner).

## Validate against live
```powershell
az deployment group what-if -g rg-ai-scout -f main.bicep -p main.bicepparam
```
The 11 core resources report **No change**. Role assignments show as *Create* because the live
ones were made with random CLI-generated names while this template uses deterministic `guid()`
names; deploying reconciles them (same principal/role/scope — harmless). A few read-only/cosmetic
properties also differ.

## Deploy (rebuild from scratch, or adopt)
```powershell
az deployment group create -g rg-ai-scout -f main.bicep -p main.bicepparam
```

## Notes
- The Azure-managed email subdomain and the Functions deployment container are runtime-generated;
  a fresh deploy produces new values for those.
- App Insights links to the region's default Log Analytics workspace (auto-created if absent).
