targetScope = 'resourceGroup'

@description('Location for KB storage and managed identity')
param kbLocation string = 'centralindia'

@description('Location for AI services, function app, and function storage')
param appLocation string = 'eastus2'

@description('Data location for Communication Services')
param communicationDataLocation string = 'India'

@description('Base name for KB storage account')
param kbStorageBaseName string = 'staiscoutv9uothke'

@description('Base name for function storage account')
param fnStorageBaseName string = 'stscoutfb764mah9s'

@description('Base name for managed identity')
param identityName string = 'id-ai-scout-gh'

@description('Base name for Cognitive Services account')
param cognitiveServicesName string = 'aiscoutageony'

@description('Base name for Foundry project')
param projectName string = 'scout'

@description('Base name for Email Service')
param emailServiceName string = 'email-ai-scout'

@description('Base name for Communication Service')
param communicationServiceName string = 'acs-ai-scout'

@description('Base name for Function App')
param functionAppName string = 'fn-ai-scout-fb'

@description('Base name for the Static Web App (Chugh Vibes marketing site)')
param staticWebAppName string = 'swa-ai-scout'

@description('Base name for App Service Plan')
param appServicePlanName string = 'ASP-rgaiscout-0373'

@description('User principal ID for role assignments')
param userPrincipalId string = 'b180b691-ddd2-4365-a356-0e16bf5fd93e'

@description('GitHub repository for federated credential')
param githubRepository string = 'Chugh3012/ai-learning'

@description('GitHub branch for federated credential')
param githubBranch string = 'main'

@description('Base name for the Log Analytics workspace (metrics store)')
param logAnalyticsName string = 'log-ai-scout'

@description('Base name for the metrics Data Collection Endpoint')
param metricsDceName string = 'dce-ai-scout'

@description('Base name for the metrics Data Collection Rule')
param metricsDcrName string = 'dcr-ai-scout'

@description('Apply RBAC role assignments (default off so the template re-deploys idempotently; enable for a fresh environment or to (re)apply roles).')
param assignRoles bool = false

@description('Email for operational alerts. Empty (default) deploys NO alert rules or action group, keeping the template at $0; set it to opt into the basic alert rules (~$0.50/rule/mo).')
param alertEmail string = ''

@description('Fire the source-health alert when feeds_failed in a day exceeds this.')
param alertFeedsFailedMax int = 8

@description('Fire the cost alert when a day of model spend (USD) exceeds this.')
param alertCostBudgetUsd int = 1

// KB Storage Account (shared-key disabled, public blob access disabled)
resource kbStorage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: kbStorageBaseName
  location: kbLocation
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}

resource kbBlobContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  name: 'knowledge'
  parent: kbBlobService
  properties: {
    publicAccess: 'None'
  }
}

// Data protection for the owned KB: versioning keeps every overwrite recoverable, and soft
// delete guards against accidental blob/container deletion. Pairs with the daily snapshot
// the pipeline takes on upload and the `ai_scout.cli.restore` restore command.
resource kbBlobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  name: 'default'
  parent: kbStorage
  properties: {
    isVersioningEnabled: true
    deleteRetentionPolicy: {
      enabled: true
      days: 14
    }
    containerDeleteRetentionPolicy: {
      enabled: true
      days: 14
    }
  }
}

// Function Storage Account
resource fnStorage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: fnStorageBaseName
  location: appLocation
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}

resource fnTables 'Microsoft.Storage/storageAccounts/tableServices@2023-05-01' = {
  name: 'default'
  parent: fnStorage
}

resource feedbackTokensTable 'Microsoft.Storage/storageAccounts/tableServices/tables@2023-05-01' = {
  name: 'feedbacktokens'
  parent: fnTables
}

resource feedbackEventsTable 'Microsoft.Storage/storageAccounts/tableServices/tables@2023-05-01' = {
  name: 'feedbackevents'
  parent: fnTables
}

// Newsletter subscribers (double opt-in): pending rows keyed by email hash + a confirm
// token; on confirm they flip to active. Written passwordless by the Function's identity.
resource subscribersTable 'Microsoft.Storage/storageAccounts/tableServices/tables@2023-05-01' = {
  name: 'subscribers'
  parent: fnTables
}

// Per-user profiles (one user -> many): PartitionKey = userId, RowKey = profileId. Keeps
// profiles a first-class table alongside the subscribers (user) table rather than a JSON blob.
resource profilesTable 'Microsoft.Storage/storageAccounts/tableServices/tables@2023-05-01' = {
  name: 'profiles'
  parent: fnTables
}

// Cached generic top-5 edition the pipeline writes and the subscribe Function reads to send
// each newly-confirmed user their first email instantly (no wait for the next daily run).
resource editionsTable 'Microsoft.Storage/storageAccounts/tableServices/tables@2023-05-01' = {
  name: 'editions'
  parent: fnTables
}

// Per-IP fixed-window counter that caps how many confirmation emails one source can trigger
// (anti-spam / cost guard on the anonymous subscribe endpoint). IP is hashed, not stored raw.
resource rateLimitTable 'Microsoft.Storage/storageAccounts/tableServices/tables@2023-05-01' = {
  name: 'ratelimit'
  parent: fnTables
}

// User-Assigned Managed Identity
resource managedIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: identityName
  location: kbLocation
}

resource federatedCredential 'Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials@2023-01-31' = {
  name: 'gh-main'
  parent: managedIdentity
  properties: {
    audiences: [
      'api://AzureADTokenExchange'
    ]
    issuer: 'https://token.actions.githubusercontent.com'
    subject: 'repo:${githubRepository}:ref:refs/heads/${githubBranch}'
  }
}

// Cognitive Services (AI Services) Account
resource cognitiveServices 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: cognitiveServicesName
  location: appLocation
  sku: {
    name: 'S0'
  }
  kind: 'AIServices'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    customSubDomainName: cognitiveServicesName
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
  }
}

// Model Deployment
resource modelDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  name: 'nano'
  parent: cognitiveServices
  sku: {
    name: 'GlobalStandard'
    capacity: 50
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-4.1-nano'
      version: '2025-04-14'
    }
    versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
  }
}

// Production ranking/drafting model (chosen via labeled golden-set eval — best quality/cost).
// Serialized after 'nano' because an account allows one deployment operation at a time.
resource miniDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  name: 'mini'
  parent: cognitiveServices
  dependsOn: [
    modelDeployment
  ]
  sku: {
    name: 'GlobalStandard'
    capacity: 50
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-4.1-mini'
      version: '2025-04-14'
    }
    versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
  }
}

// Embedding model for personalization (two-tower retrieval): embeds each item + each user's
// interest sentence once; per-user match = a cheap dot product (O(items+users), not items×users).
// text-embedding-3-large is Azure's latest/most-capable embedding model (no successor exists as
// of 2026-05); reduced to 256 dims via the `dimensions` param keeps storage tiny while still
// beating ada-002. Serialized after 'mini' (one deploy op per account at a time).
resource embedDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  name: 'embed'
  parent: cognitiveServices
  dependsOn: [
    miniDeployment
  ]
  sku: {
    name: 'GlobalStandard'
    capacity: 50
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'text-embedding-3-large'
      version: '1'
    }
    versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
  }
}

// Foundry Project
resource foundryProject 'Microsoft.CognitiveServices/accounts/projects@2026-05-01' = {
  name: projectName
  parent: cognitiveServices
  location: appLocation
  kind: 'AIServices'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    isDefault: true
  }
}

// Email Service
resource emailService 'Microsoft.Communication/EmailServices@2023-04-01' = {
  name: emailServiceName
  location: 'global'
  properties: {
    dataLocation: communicationDataLocation
  }
}

// Azure Managed Email Domain
resource emailDomain 'Microsoft.Communication/EmailServices/Domains@2023-04-01' = {
  name: 'AzureManagedDomain'
  parent: emailService
  location: 'global'
  properties: {
    domainManagement: 'AzureManaged'
    userEngagementTracking: 'Disabled'
  }
}

// Communication Service
resource communicationService 'Microsoft.Communication/CommunicationServices@2023-04-01' = {
  name: communicationServiceName
  location: 'global'
  properties: {
    dataLocation: communicationDataLocation
    linkedDomains: [
      emailDomain.id
    ]
  }
}

// Application Insights
resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: functionAppName
  location: appLocation
  kind: 'web'
  properties: {
    Application_Type: 'web'
    RetentionInDays: 90
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
  }
}

// App Service Plan (Flex Consumption)
resource appServicePlan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: appServicePlanName
  location: appLocation
  sku: {
    name: 'FC1'
    tier: 'FlexConsumption'
  }
  kind: 'functionapp'
  properties: {
    reserved: true
  }
}

// Function App
resource functionApp 'Microsoft.Web/sites@2024-04-01' = {
  name: functionAppName
  location: appLocation
  kind: 'functionapp,linux'
  tags: {
    'azd-service-name': 'feedback'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: appServicePlan.id
    clientAffinityEnabled: false
    httpsOnly: true
    functionAppConfig: {
      deployment: {
        storage: {
          type: 'blobContainer'
          value: '${fnStorage.properties.primaryEndpoints.blob}app-package-fnaiscoutfb-5507037'
          authentication: {
            // Passwordless: the Function's system-assigned identity pulls the deployment
            // package (no connection string / account key). Requires Storage Blob Data
            // Contributor on fnStorage for this identity (granted below).
            type: 'SystemAssignedIdentity'
          }
        }
      }
      scaleAndConcurrency: {
        maximumInstanceCount: 100
        instanceMemoryMB: 2048
      }
      runtime: {
        name: 'python'
        version: '3.13'
      }
    }
    siteConfig: {
      minTlsVersion: '1.2'
      scmMinTlsVersion: '1.2'
      ftpsState: 'Disabled'
      http20Enabled: true
      cors: {
        // The Chugh Vibes site (Static Web App origin) POSTs the subscribe form here.
        // Scoped to that single origin (no wildcard); credentials are not used.
        supportCredentials: false
        allowedOrigins: [
          'https://${staticSite.properties.defaultHostname}'
        ]
      }
      appSettings: [
        {
          name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
          value: appInsights.properties.ConnectionString
        }
        {
          name: 'AzureWebJobsStorage__accountName'
          value: fnStorage.name
        }
        {
          // Double opt-in confirmation emails (passwordless: Function identity -> ACS).
          name: 'ACS_ENDPOINT'
          value: 'https://${communicationService.properties.hostName}'
        }
        {
          name: 'EMAIL_SENDER'
          value: 'DoNotReply@${emailDomain.properties.fromSenderDomain}'
        }
      ]
    }
  }
}

// Static Web App (Free tier) — hosts the Chugh Vibes marketing + subscribe site (web/).
// Content is published with the SWA deployment token (swa deploy ./web), so no repo link here.
resource staticSite 'Microsoft.Web/staticSites@2024-04-01' = {
  name: staticWebAppName
  location: appLocation
  sku: {
    name: 'Free'
    tier: 'Free'
  }
  properties: {
    allowConfigFileUpdates: true
    stagingEnvironmentPolicy: 'Enabled'
  }
}

// Role Assignments - Storage Blob Data Contributor on KB Storage
resource kbStorageBlobUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (assignRoles) {
  name: guid(kbStorage.id, userPrincipalId, 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
  scope: kbStorage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
    principalId: userPrincipalId
    principalType: 'User'
  }
}

resource kbStorageBlobIdentityRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (assignRoles) {
  name: guid(kbStorage.id, managedIdentity.id, 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
  scope: kbStorage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
    principalId: managedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// Role Assignments - Storage Table Data Contributor on Function Storage
resource fnStorageTableFunctionRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (assignRoles) {
  name: guid(fnStorage.id, functionApp.id, '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3')
  scope: fnStorage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3')
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource fnStorageTableUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (assignRoles) {
  name: guid(fnStorage.id, userPrincipalId, '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3')
  scope: fnStorage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3')
    principalId: userPrincipalId
    principalType: 'User'
  }
}

resource fnStorageTableIdentityRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (assignRoles) {
  name: guid(fnStorage.id, managedIdentity.id, '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3')
  scope: fnStorage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3')
    principalId: managedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// Role Assignments - Storage Blob Data Contributor on Function Storage (Flex deployment package,
// pulled passwordless by the Function's system-assigned identity; the user can publish too).
resource fnStorageBlobFunctionRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (assignRoles) {
  name: guid(fnStorage.id, functionApp.id, 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
  scope: fnStorage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource fnStorageBlobUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (assignRoles) {
  name: guid(fnStorage.id, userPrincipalId, 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
  scope: fnStorage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
    principalId: userPrincipalId
    principalType: 'User'
  }
}

// Storage Queue Data Contributor on Function Storage. The Flex Consumption host uses queues
// for internal coordination via its identity; required once shared-key access is disabled.
resource fnStorageQueueFunctionRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (assignRoles) {
  name: guid(fnStorage.id, functionApp.id, '974c5e8b-45b9-4653-ba55-5f855dd0fb88')
  scope: fnStorage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '974c5e8b-45b9-4653-ba55-5f855dd0fb88')
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// Role Assignments - Cognitive Services OpenAI User
resource cognitiveServicesUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (assignRoles) {
  name: guid(cognitiveServices.id, userPrincipalId, '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd')
  scope: cognitiveServices
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd')
    principalId: userPrincipalId
    principalType: 'User'
  }
}

resource cognitiveServicesIdentityRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (assignRoles) {
  name: guid(cognitiveServices.id, managedIdentity.id, '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd')
  scope: cognitiveServices
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd')
    principalId: managedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// Role Assignments - Communication and Email Service Owner
resource communicationServiceUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (assignRoles) {
  name: guid(communicationService.id, userPrincipalId, '09976791-48a7-449e-bb21-39d1a415f350')
  scope: communicationService
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '09976791-48a7-449e-bb21-39d1a415f350')
    principalId: userPrincipalId
    principalType: 'User'
  }
}

resource communicationServiceIdentityRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (assignRoles) {
  name: guid(communicationService.id, managedIdentity.id, '09976791-48a7-449e-bb21-39d1a415f350')
  scope: communicationService
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '09976791-48a7-449e-bb21-39d1a415f350')
    principalId: managedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// The Function's own identity sends double opt-in confirmation emails via ACS.
resource communicationServiceFunctionRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (assignRoles) {
  name: guid(communicationService.id, functionApp.id, '09976791-48a7-449e-bb21-39d1a415f350')
  scope: communicationService
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '09976791-48a7-449e-bb21-39d1a415f350')
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// ---- Observability: pipeline metrics -> Log Analytics (all passwordless) ----
// The pipeline POSTs run metrics (ingested / ranked / embedded / delivered / voted / tokens /
// eval scores) to the DCE using its managed identity (Monitoring Metrics Publisher on the DCR);
// the DCR routes them into the AiScoutMetrics_CL custom table. Visualize via Azure Monitor (Logs
// / Workbooks) in the portal — no extra paid resource. (Azure Managed Grafana 'Essential' is not
// ARM-deployable here and 'Standard' is ~$63/mo, so it is intentionally not provisioned.)

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logAnalyticsName
  location: appLocation
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 90
    features: {
      disableLocalAuth: true
    }
  }
}

resource metricsTable 'Microsoft.OperationalInsights/workspaces/tables@2023-09-01' = {
  name: 'AiScoutMetrics_CL'
  parent: logAnalytics
  properties: {
    schema: {
      name: 'AiScoutMetrics_CL'
      columns: [
        { name: 'TimeGenerated', type: 'datetime' }
        { name: 'Run', type: 'string' }
        { name: 'Metric', type: 'string' }
        { name: 'Value', type: 'real' }
        { name: 'Lens', type: 'string' }
        { name: 'Channel', type: 'string' }
      ]
    }
    retentionInDays: 90
    totalRetentionInDays: 90
    plan: 'Analytics'
  }
}

resource metricsDce 'Microsoft.Insights/dataCollectionEndpoints@2023-03-11' = {
  name: metricsDceName
  location: appLocation
  properties: {
    networkAcls: {
      publicNetworkAccess: 'Enabled'
    }
  }
}

resource metricsDcr 'Microsoft.Insights/dataCollectionRules@2023-03-11' = {
  name: metricsDcrName
  location: appLocation
  dependsOn: [
    metricsTable
  ]
  properties: {
    dataCollectionEndpointId: metricsDce.id
    streamDeclarations: {
      'Custom-AiScoutMetrics_CL': {
        columns: [
          { name: 'TimeGenerated', type: 'datetime' }
          { name: 'Run', type: 'string' }
          { name: 'Metric', type: 'string' }
          { name: 'Value', type: 'real' }
          { name: 'Lens', type: 'string' }
          { name: 'Channel', type: 'string' }
        ]
      }
    }
    destinations: {
      logAnalytics: [
        {
          name: 'la'
          workspaceResourceId: logAnalytics.id
        }
      ]
    }
    dataFlows: [
      {
        streams: [
          'Custom-AiScoutMetrics_CL'
        ]
        destinations: [
          'la'
        ]
        transformKql: 'source'
        outputStream: 'Custom-AiScoutMetrics_CL'
      }
    ]
  }
}

// Azure Monitor Workbook — the free, Entra-authed dashboard (For you / Ops), as code.
resource workbook 'Microsoft.Insights/workbooks@2023-06-01' = {
  name: guid(resourceGroup().id, 'ai-scout-pipeline-workbook')
  location: appLocation
  kind: 'shared'
  properties: {
    displayName: 'ai-scout pipeline'
    serializedData: loadTextContent('workbook.json')
    category: 'workbooks'
    sourceId: logAnalytics.id
    version: 'Notebook/1.0'
  }
}

// Basic operational alerts over the metrics table. Opt-in: nothing here deploys unless an
// alertEmail is supplied, so the default template stays free. Email notifications via an
// action group; the three log-search rules cover the heartbeat, source health, and cost.
resource alertActionGroup 'Microsoft.Insights/actionGroups@2023-01-01' = if (!empty(alertEmail)) {
  name: 'ag-ai-scout-alerts'
  location: 'global'
  properties: {
    groupShortName: 'aiscout'
    enabled: true
    emailReceivers: [
      {
        name: 'owner'
        emailAddress: alertEmail
        useCommonAlertSchema: true
      }
    ]
  }
}

// Heartbeat: the daily pipeline must land at least one ingest in the last 36h (allows one
// missed run plus buffer). No data => the pipeline is stuck or its identity broke.
resource noSyncAlert 'Microsoft.Insights/scheduledQueryRules@2023-12-01' = if (!empty(alertEmail)) {
  name: 'ai-scout-no-sync-36h'
  location: appLocation
  properties: {
    displayName: 'ai-scout: no successful sync in 36h'
    description: 'The daily pipeline has not ingested anything in 36 hours.'
    severity: 1
    enabled: true
    scopes: [
      logAnalytics.id
    ]
    evaluationFrequency: 'PT6H'
    windowSize: 'P2D'
    criteria: {
      allOf: [
        {
          query: 'AiScoutMetrics_CL | where Metric == "ingested" | where TimeGenerated > ago(36h) | summarize AggregatedValue = count()'
          timeAggregation: 'Total'
          metricMeasureColumn: 'AggregatedValue'
          operator: 'LessThan'
          threshold: 1
          failingPeriods: {
            numberOfEvaluationPeriods: 1
            minFailingPeriodsToAlert: 1
          }
        }
      ]
    }
    autoMitigate: true
    actions: {
      actionGroups: [
        alertActionGroup.id
      ]
    }
  }
}

// Source health: too many feeds failing in a day signals broken/blocked sources.
resource feedsFailedAlert 'Microsoft.Insights/scheduledQueryRules@2023-12-01' = if (!empty(alertEmail)) {
  name: 'ai-scout-feeds-failed'
  location: appLocation
  properties: {
    displayName: 'ai-scout: source failure rate high'
    description: 'More than the allowed number of feeds failed in the last day.'
    severity: 2
    enabled: true
    scopes: [
      logAnalytics.id
    ]
    evaluationFrequency: 'PT6H'
    windowSize: 'P1D'
    criteria: {
      allOf: [
        {
          query: 'AiScoutMetrics_CL | where Metric == "feeds_failed" | summarize AggregatedValue = max(Value)'
          timeAggregation: 'Maximum'
          metricMeasureColumn: 'AggregatedValue'
          operator: 'GreaterThan'
          threshold: alertFeedsFailedMax
          failingPeriods: {
            numberOfEvaluationPeriods: 1
            minFailingPeriodsToAlert: 1
          }
        }
      ]
    }
    autoMitigate: true
    actions: {
      actionGroups: [
        alertActionGroup.id
      ]
    }
  }
}

// Cost guard: a day of model spend above budget means a runaway prompt/loop.
resource costAlert 'Microsoft.Insights/scheduledQueryRules@2023-12-01' = if (!empty(alertEmail)) {
  name: 'ai-scout-cost-budget'
  location: appLocation
  properties: {
    displayName: 'ai-scout: daily model cost over budget'
    description: 'Model spend in the last day exceeded the configured budget.'
    severity: 2
    enabled: true
    scopes: [
      logAnalytics.id
    ]
    evaluationFrequency: 'PT6H'
    windowSize: 'P1D'
    criteria: {
      allOf: [
        {
          query: 'AiScoutMetrics_CL | where Metric == "cost_usd" | summarize AggregatedValue = sum(Value)'
          timeAggregation: 'Total'
          metricMeasureColumn: 'AggregatedValue'
          operator: 'GreaterThan'
          threshold: alertCostBudgetUsd
          failingPeriods: {
            numberOfEvaluationPeriods: 1
            minFailingPeriodsToAlert: 1
          }
        }
      ]
    }
    autoMitigate: true
    actions: {
      actionGroups: [
        alertActionGroup.id
      ]
    }
  }
}

// RBAC - Monitoring Metrics Publisher on the DCR (pipeline identity + user can ship metrics)
resource dcrPublisherIdentityRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (assignRoles) {
  name: guid(metricsDcr.id, managedIdentity.id, '3913510d-42f4-4e42-8a64-420c390055eb')
  scope: metricsDcr
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '3913510d-42f4-4e42-8a64-420c390055eb')
    principalId: managedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource dcrPublisherUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (assignRoles) {
  name: guid(metricsDcr.id, userPrincipalId, '3913510d-42f4-4e42-8a64-420c390055eb')
  scope: metricsDcr
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '3913510d-42f4-4e42-8a64-420c390055eb')
    principalId: userPrincipalId
    principalType: 'User'
  }
}

// Outputs
output kbStorageId string = kbStorage.id
output fnStorageId string = fnStorage.id
output managedIdentityId string = managedIdentity.id
output managedIdentityPrincipalId string = managedIdentity.properties.principalId
output cognitiveServicesId string = cognitiveServices.id
output foundryProjectId string = foundryProject.id
output emailServiceId string = emailService.id
output communicationServiceId string = communicationService.id
output functionAppId string = functionApp.id
output functionAppPrincipalId string = functionApp.identity.principalId
output staticSiteName string = staticSite.name
output staticSiteHostname string = staticSite.properties.defaultHostname
output appInsightsId string = appInsights.id
output logAnalyticsId string = logAnalytics.id
output metricsDceEndpoint string = metricsDce.properties.logsIngestion.endpoint
output metricsDcrImmutableId string = metricsDcr.properties.immutableId
output metricsStream string = 'Custom-AiScoutMetrics_CL'
output workbookId string = workbook.id
