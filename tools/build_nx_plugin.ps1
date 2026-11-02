[CmdletBinding()]
param([string]$NxRoot=$env:UGII_BASE_DIR)
$ErrorActionPreference='Stop'
if(-not $NxRoot){$NxRoot='D:\Program Files\Siemens\Designcenter2606'}
$pluginRoot=Join-Path (Split-Path -Parent $PSScriptRoot) 'nxdrp\nx_plugin'
$managed=Join-Path $NxRoot 'NXBIN\managed'
$compiler=Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
foreach($required in @($compiler,(Join-Path $managed 'NXOpen.dll'),(Join-Path $managed 'NXOpenUI.dll'),(Join-Path $managed 'NXOpen.UF.dll'))){
 if(-not(Test-Path -LiteralPath $required)){throw ('Missing compiler or NX assembly: '+$required)}
}
$destination=Join-Path $pluginRoot 'startup\HartingNxPlugin.dll'
& $compiler /nologo /target:library /codepage:65001 /optimize+ (('/out:')+$destination) (('/reference:')+(Join-Path $managed 'NXOpen.dll')) (('/reference:')+(Join-Path $managed 'NXOpenUI.dll')) (('/reference:')+(Join-Path $managed 'NXOpen.UF.dll')) (('/reference:')+(Join-Path $managed 'NXOpen.Utilities.dll')) /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Web.Extensions.dll (Join-Path $pluginRoot 'HartingNxPlugin.cs')
if($LASTEXITCODE -ne 0){throw 'NX plugin compilation failed'}
Write-Output ('Built: '+$destination)
