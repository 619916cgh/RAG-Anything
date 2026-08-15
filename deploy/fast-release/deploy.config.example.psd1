@{
    Host                      = 'example-host'
    Port                      = 22
    User                      = 'deploy-user'
    IdentityFile              = 'C:\\path\\to\\id_ed25519'
    ProjectDirectory          = '/opt/rag-anything'
    RemoteReleaseRoot         = '/opt/rag-anything-releases'
    EligibilityBaselineCommit = '0000000000000000000000000000000000000000'
    AppRuntimeImage           = 'raganything-app-runtime:cpu-REPLACE_ME'
    AppRuntimeImageId         = 'sha256:REPLACE_WITH_64_HEX_IMAGE_ID'
    NginxRuntimeImage         = 'nginx:alpine'
    NginxRuntimeImageId       = 'sha256:REPLACE_WITH_64_HEX_IMAGE_ID'
    MinimumFreeGB             = 12
    HealthWindowSeconds       = 60
    HealthIntervalSeconds     = 5
}
