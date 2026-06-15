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

@description('Base name for App Service Plan')
param appServicePlanName string = 'ASP-rgaiscout-0373'

@description('User principal ID for role assignments')
param userPrincipalId string = 'b180b691-ddd2-4365-a356-0e16bf5fd93e'

@description('GitHub repository for federated credential')
param githubRepository string = 'Chugh3012/ai-learning'

@description('GitHub branch for federated credential')
param githubBranch string = 'main'

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
  name: '${kbStorage.name}/default/knowledge'
  properties: {
    publicAccess: 'None'
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
            type: 'StorageAccountConnectionString'
            storageAccountConnectionStringName: 'DEPLOYMENT_STORAGE_CONNECTION_STRING'
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
      appSettings: [
        {
          name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
          value: appInsights.properties.ConnectionString
        }
        {
          name: 'AzureWebJobsStorage__accountName'
          value: fnStorage.name
        }
      ]
    }
  }
}

// Role Assignments - Storage Blob Data Contributor on KB Storage
resource kbStorageBlobUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(kbStorage.id, userPrincipalId, 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
  scope: kbStorage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
    principalId: userPrincipalId
    principalType: 'User'
  }
}

resource kbStorageBlobIdentityRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(kbStorage.id, managedIdentity.id, 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
  scope: kbStorage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
    principalId: managedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// Role Assignments - Storage Table Data Contributor on Function Storage
resource fnStorageTableFunctionRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(fnStorage.id, functionApp.id, '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3')
  scope: fnStorage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3')
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource fnStorageTableUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(fnStorage.id, userPrincipalId, '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3')
  scope: fnStorage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3')
    principalId: userPrincipalId
    principalType: 'User'
  }
}

resource fnStorageTableIdentityRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(fnStorage.id, managedIdentity.id, '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3')
  scope: fnStorage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3')
    principalId: managedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// Role Assignments - Cognitive Services OpenAI User
resource cognitiveServicesUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(cognitiveServices.id, userPrincipalId, '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd')
  scope: cognitiveServices
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd')
    principalId: userPrincipalId
    principalType: 'User'
  }
}

resource cognitiveServicesIdentityRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(cognitiveServices.id, managedIdentity.id, '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd')
  scope: cognitiveServices
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd')
    principalId: managedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// Role Assignments - Communication and Email Service Owner
resource communicationServiceUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(communicationService.id, userPrincipalId, '20e02c0b-1f9c-4c53-81c4-f8bf1f8e9766')
  scope: communicationService
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '20e02c0b-1f9c-4c53-81c4-f8bf1f8e9766')
    principalId: userPrincipalId
    principalType: 'User'
  }
}

resource communicationServiceIdentityRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(communicationService.id, managedIdentity.id, '20e02c0b-1f9c-4c53-81c4-f8bf1f8e9766')
  scope: communicationService
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '20e02c0b-1f9c-4c53-81c4-f8bf1f8e9766')
    principalId: managedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
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
output appInsightsId string = appInsights.id
