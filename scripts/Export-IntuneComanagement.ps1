<#
.SYNOPSIS
    Exports Windows devices from Intune with their management agent and co-management workload flags.

.DESCRIPTION
    GET /deviceManagement/managedDevices (Windows only), selecting the fields the tracker needs,
    including configurationManagerClientEnabledFeatures (which workloads Intune manages on that device).
    Writes { "value": [ ... ] } to a JSON file.

    Read-only. Sign in with your own account; the only scope requested is
    DeviceManagementManagedDevices.Read.All.

.EXAMPLE
    .\Export-IntuneComanagement.ps1 -OutputPath .\intune_devices.json
#>
[CmdletBinding()]
param(
    [string]$OutputPath = ".\intune_devices.json"
)

$ErrorActionPreference = "Stop"

if (-not (Get-Module -ListAvailable -Name Microsoft.Graph.Authentication)) {
    throw "Install the Microsoft Graph PowerShell SDK first: Install-Module Microsoft.Graph.Authentication -Scope CurrentUser"
}

Connect-MgGraph -Scopes "DeviceManagementManagedDevices.Read.All" -NoWelcome

$select = "id,deviceName,operatingSystem,osVersion,managementAgent,complianceState,lastSyncDateTime," +
          "serialNumber,configurationManagerClientEnabledFeatures"
$uri = "https://graph.microsoft.com/v1.0/deviceManagement/managedDevices" +
       "?`$filter=operatingSystem eq 'Windows'&`$select=$select&`$top=999"

$devices = @()
while ($uri) {
    $page = Invoke-MgGraphRequest -Method GET -Uri $uri
    $devices += $page.value
    $uri = $page.'@odata.nextLink'
}

@{ value = $devices } | ConvertTo-Json -Depth 6 | Set-Content -Path $OutputPath -Encoding UTF8
Write-Host "Saved $($devices.Count) Windows devices to $OutputPath. It contains device names and serial numbers: keep it inside your organisation."
