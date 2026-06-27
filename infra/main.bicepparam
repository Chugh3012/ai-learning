using './main.bicep'

// Location parameters
param kbLocation = 'centralindia'
param appLocation = 'eastus2'
param communicationDataLocation = 'India'

// Resource name parameters
param kbStorageBaseName = 'staiscoutv9uothke'
param fnStorageBaseName = 'stscoutfb764mah9s'
param identityName = 'id-ai-scout-gh'
param cognitiveServicesName = 'aiscoutageony'
param projectName = 'scout'
param emailServiceName = 'email-ai-scout'
param communicationServiceName = 'acs-ai-scout'
param functionAppName = 'fn-ai-scout-fb'
param appServicePlanName = 'ASP-rgaiscout-0373'

// Identity parameters
param userPrincipalId = 'b180b691-ddd2-4365-a356-0e16bf5fd93e'

// GitHub parameters
param githubRepository = 'Chugh3012/ai-learning'
param githubBranch = 'main'

// Feature parameters
param deploySora = true   // Sora 2 video deployment for AI reel visuals (hybrid mode); billed per second
