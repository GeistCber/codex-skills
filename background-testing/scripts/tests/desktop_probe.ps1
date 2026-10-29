param([Parameter(Mandatory=$true)][string]$OutputDirectory)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms,System.Drawing
$form=New-Object Windows.Forms.Form
$form.Text='Controlled testing probe'
$form.Size=New-Object Drawing.Size(620,240)
$form.StartPosition='CenterScreen'
$box=New-Object Windows.Forms.TextBox
$box.Multiline=$true
$box.Dock='Fill'
$form.Controls.Add($box)
$other=New-Object Windows.Forms.Form
$other.Text='Unexpected probe window'
$other.Size=New-Object Drawing.Size(400,180)
$script:modal=$null
$script:last=''
$script:started=[DateTime]::UtcNow
function Save-State {
    $state=@{Text=$box.Text;Root=$form.Handle.ToInt64();Other=$other.Handle.ToInt64();Enabled=$form.Enabled;ProcessId=$PID}
    [IO.File]::WriteAllText((Join-Path $OutputDirectory 'probe-state.json'),($state|ConvertTo-Json),[Text.Encoding]::UTF8)
}
$box.Add_TextChanged({Save-State})
$timer=New-Object Windows.Forms.Timer
$timer.Interval=70
$timer.Add_Tick({
    if(([DateTime]::UtcNow-$script:started).TotalMinutes -gt 5){$form.Close();return}
    $path=Join-Path $OutputDirectory 'probe-command.json'
    if(Test-Path -LiteralPath $path){
        try{$command=[IO.File]::ReadAllText($path)|ConvertFrom-Json}catch{return}
        if($command.id -ne $script:last){
            $script:last=$command.id
            switch($command.action){
                clear-text {$box.Clear();$box.Focus()}
                focus-other {$other.Show();$other.Activate()}
                modal {
                    $script:modal=New-Object Windows.Forms.Form
                    $script:modal.Text='Unknown modal probe'
                    $script:modal.Size=New-Object Drawing.Size(380,160)
                    $script:modal.Show($form)
                    $form.Enabled=$false
                    $script:modal.Activate()
                }
                restore {
                    if($script:modal){$script:modal.Close();$script:modal=$null}
                    $form.Enabled=$true
                    $other.Hide()
                    $form.Activate();$box.Focus()
                }
                close {$form.Close()}
            }
            Save-State
            [IO.File]::WriteAllText((Join-Path $OutputDirectory 'probe-ack.txt'),[string]$command.id)
        }
    }
})
$form.Add_Shown({$box.Focus();Save-State;$timer.Start()})
try{[Windows.Forms.Application]::Run($form)}finally{$timer.Stop();$timer.Dispose();$other.Dispose();$form.Dispose()}
