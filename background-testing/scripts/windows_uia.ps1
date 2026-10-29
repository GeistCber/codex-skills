param(
    [Parameter(Mandatory=$true)][ValidateSet('Inspect','Locate','History','Click','Type','Key','Command','Capture','Arrange','Acquire')][string]$Action,
    [Parameter(Mandatory=$true)][string]$Manifest,
    [Parameter(Mandatory=$true)][string]$State,
    [string]$PanelTitle,
    [string]$Value,
    [string]$ValueBase64,
    [string]$Python='python',
    [switch]$AllowDesktopInput
)
$ErrorActionPreference='Stop'
if($PSBoundParameters.ContainsKey('ValueBase64')){$Value=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($ValueBase64))}
if(-not $AllowDesktopInput -and $Action -notin @('Inspect','Locate','History')){throw 'Use the explicit desktop entry and -AllowDesktopInput.'}
Add-Type -AssemblyName UIAutomationClient,UIAutomationTypes,System.Drawing,System.Windows.Forms
if(-not ('SkillWindowNative' -as [type])){Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class SkillWindowNative {
    [StructLayout(LayoutKind.Sequential)]public struct Rect{public int Left,Top,Right,Bottom;}
    [DllImport("user32.dll")]public static extern bool GetWindowRect(IntPtr h,out Rect r);
    [DllImport("user32.dll")]public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")]public static extern bool MoveWindow(IntPtr h,int x,int y,int w,int height,bool repaint);
    [DllImport("user32.dll")]public static extern bool ShowWindow(IntPtr h,int s);
    [DllImport("user32.dll")]public static extern bool SetProcessDPIAware();
}
'@}
[void][SkillWindowNative]::SetProcessDPIAware()
$m=Get-Content -LiteralPath $Manifest -Raw -Encoding UTF8|ConvertFrom-Json
$process=Get-Process -Id $m.pid
if($process.StartTime.ToUniversalTime().Ticks -ne $m.start_ticks){throw 'Process identity changed'}
$guard=Join-Path $PSScriptRoot 'desktop_guard.py'
function Input([string]$action,[string]$value=''){
    $payload=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($value))
    $result=& $Python $guard $Manifest $State $action ('--value-base64='+$payload)
    if($LASTEXITCODE -ne 0){throw ('Input '+$action+' refused: '+($result -join "`n"))}
}
function Panel {
    if(-not $PanelTitle){throw 'PanelTitle is required for control operations'}
    $name=New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty,$PanelTitle)
    $pidCondition=New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty,[int]$m.pid)
    $both=New-Object System.Windows.Automation.AndCondition($name,$pidCondition)
    $element=[System.Windows.Automation.AutomationElement]::RootElement.FindFirst([System.Windows.Automation.TreeScope]::Descendants,$both)
    if($null -eq $element){throw 'Expected panel is absent'}
    return $element
}
function TargetControl {
    $panel=Panel
    if($Value -match '^(name|checkbox):(.*):(\d+)$'){
        $kind=$Matches[1];$targetName=$Matches[2];$targetIndex=[int]$Matches[3]
        $condition=New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty,$targetName)
        if($kind -eq 'checkbox'){
            $typeCondition=New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty,[System.Windows.Automation.ControlType]::CheckBox)
            $condition=New-Object System.Windows.Automation.AndCondition($condition,$typeCondition)
        }
        $items=$panel.FindAll([System.Windows.Automation.TreeScope]::Descendants,$condition)
        if($targetIndex -ge $items.Count){throw 'Named control index does not exist'}
        return $items[$targetIndex]
    }
    $condition=New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::AutomationIdProperty,$Value)
    $item=$panel.FindFirst([System.Windows.Automation.TreeScope]::Descendants,$condition)
    if($null -eq $item){throw ('Expected control is absent: '+$Value)}
    return $item
}
function GlobalInput([string]$id){
    $identity=New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::AutomationIdProperty,$id)
    $pidCondition=New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty,[int]$m.pid)
    $condition=New-Object System.Windows.Automation.AndCondition($identity,$pidCondition)
    $items=[System.Windows.Automation.AutomationElement]::RootElement.FindAll([System.Windows.Automation.TreeScope]::Descendants,$condition)
    if($items.Count -ne 1){throw 'Expected one explicitly configured input control'}
    return $items[0]
}
switch($Action){
    History {
        $item=GlobalInput 'FlowDocumentScrollViewer_1'
        $item.GetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern).DocumentRange.GetText(-1)
        return
    }
    Locate {
        $item=GlobalInput $Value;$r=$item.Current.BoundingRectangle
        [pscustomobject]@{Id=$item.Current.AutomationId;Type=$item.Current.ControlType.ProgrammaticName;Offscreen=$item.Current.IsOffscreen;X=($r.Left+$r.Width/2);Y=($r.Top+$r.Height/2)}|ConvertTo-Json
        return
    }
    Inspect {
        $panel=Panel
        $rows=New-Object System.Collections.Generic.List[object]
        $rows.Add([pscustomobject]@{Id='__panel__';Name=$PanelTitle;Handle=$panel.Current.NativeWindowHandle})
        foreach($item in $panel.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)){
            if($item.Current.AutomationId -or $item.Current.ControlType -eq [System.Windows.Automation.ControlType]::CheckBox){
                $valueText=$null;$toggle=$null
                try{$valueText=$item.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).Current.Value}catch{}
                try{$toggle=[string]$item.GetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern).Current.ToggleState}catch{}
                $rows.Add([pscustomobject]@{Id=$item.Current.AutomationId;Name=$item.Current.Name;Type=$item.Current.ControlType.ProgrammaticName;Rect=$item.Current.BoundingRectangle.ToString();Offscreen=$item.Current.IsOffscreen;Value=$valueText;Toggle=$toggle})
            }
        }
        $rows|ConvertTo-Json -Depth 4
        return
    }
    Acquire {Input acquire;return}
}
Input check
switch($Action){
    Click {
        if($Value -match '^\d+,\d+$'){Input click $Value}
        else{
            $panel=Panel;$item=TargetControl
            if($item.Current.IsOffscreen -or -not $item.Current.IsEnabled){throw 'Control is hidden or disabled'}
            [void][SkillWindowNative]::SetForegroundWindow([IntPtr]$panel.Current.NativeWindowHandle)
            Start-Sleep -Milliseconds 100
            $r=$item.Current.BoundingRectangle
            Input click (([int]($r.Left+$r.Width/2)).ToString()+','+([int]($r.Top+$r.Height/2)))
        }
    }
    Type {Input text $Value}
    Key {if($Value -eq 'SelectAll'){Input select-all}else{Input key $Value}}
    Command {
        if(-not $m.command_input_id){throw 'Configure the observed command input AutomationId; fixed screen offsets are not supported'}
        Input acquire
        Input key '27';Input key '27'
        $item=GlobalInput $m.command_input_id
        if($item.Current.IsOffscreen -or -not $item.Current.IsEnabled){throw 'Configured command input is not usable'}
        $r=$item.Current.BoundingRectangle
        Input click (([int]($r.Left+$r.Width/2)).ToString()+','+([int]($r.Top+$r.Height/2)))
        Input text ($Value+"`n")
    }
    Arrange {
        [void][SkillWindowNative]::ShowWindow([IntPtr]$m.root_hwnd,9)
        [void][SkillWindowNative]::MoveWindow([IntPtr]$m.root_hwnd,0,0,1200,1000,$true)
        $panel=Panel
        $transform=$panel.GetCurrentPattern([System.Windows.Automation.TransformPattern]::Pattern)
        $transform.Resize(680,880);$transform.Move(1200,90)
    }
    Capture {
        Start-Sleep -Milliseconds 450
        $r=New-Object SkillWindowNative+Rect
        [void][SkillWindowNative]::GetWindowRect([IntPtr]$m.root_hwnd,[ref]$r)
        if($PanelTitle){
            $panel=Panel;$p=$panel.Current.BoundingRectangle
            $r.Left=[Math]::Min($r.Left,$p.Left);$r.Top=[Math]::Min($r.Top,$p.Top)
            $r.Right=[Math]::Max($r.Right,$p.Right);$r.Bottom=[Math]::Max($r.Bottom,$p.Bottom)
        }
        $screen=[Windows.Forms.SystemInformation]::VirtualScreen
        $left=[Math]::Max($r.Left,$screen.Left);$top=[Math]::Max($r.Top,$screen.Top)
        $width=[Math]::Min($r.Right,$screen.Right)-$left;$height=[Math]::Min($r.Bottom,$screen.Bottom)-$top
        $image=New-Object Drawing.Bitmap($width,$height);$graphics=[Drawing.Graphics]::FromImage($image)
        try{$graphics.CopyFromScreen($left,$top,0,0,$image.Size);$image.Save($Value,[Drawing.Imaging.ImageFormat]::Png)}finally{$graphics.Dispose();$image.Dispose()}
    }
}
Start-Sleep -Milliseconds 350
