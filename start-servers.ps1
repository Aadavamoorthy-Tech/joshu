param(
    [ValidateRange(1, 65535)]
    [int]$BackendPort = 8000,
    [ValidateRange(1, 65535)]
    [int]$FrontendPort = 3000
)

$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'Backend virtual environment not found. See README.md for setup.'
}
if ($BackendPort -eq $FrontendPort) {
    throw 'The frontend and backend must use different ports.'
}
$listeners = [System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()
$occupiedPorts = @($listeners | Where-Object {
    $_.Port -eq $BackendPort -or $_.Port -eq $FrontendPort
} | Select-Object -ExpandProperty Port -Unique)
if ($occupiedPorts.Count -gt 0) {
    throw "Port(s) $($occupiedPorts -join ', ') already in use. Stop the existing servers before starting this launcher."
}

# The launcher and its children belong to a job that closes with this process.
Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

public static class ServerJob
{
    [StructLayout(LayoutKind.Sequential)]
    private struct BasicLimitInformation {
        public long PerProcessUserTimeLimit, PerJobUserTimeLimit;
        public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize, MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public UIntPtr Affinity;
        public uint PriorityClass, SchedulingClass;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct IoCounters {
        public ulong ReadOperationCount, WriteOperationCount, OtherOperationCount;
        public ulong ReadTransferCount, WriteTransferCount, OtherTransferCount;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct ExtendedLimitInformation {
        public BasicLimitInformation BasicLimitInformation;
        public IoCounters IoInfo;
        public UIntPtr ProcessMemoryLimit, JobMemoryLimit, PeakProcessMemoryUsed, PeakJobMemoryUsed;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern SafeFileHandle CreateJobObject(IntPtr attributes, string name);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool SetInformationJobObject(SafeFileHandle job, int infoClass,
        ref ExtendedLimitInformation info, uint length);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool AssignProcessToJobObject(SafeFileHandle job, IntPtr process);

    private static SafeFileHandle job;

    public static void AttachLauncher() {
        job = CreateJobObject(IntPtr.Zero, null);
        if (job.IsInvalid) throw new Win32Exception(Marshal.GetLastWin32Error());
        var limits = new ExtendedLimitInformation();
        limits.BasicLimitInformation.LimitFlags = 0x2000;
        if (!SetInformationJobObject(job, 9, ref limits, (uint)Marshal.SizeOf(limits)))
            throw new Win32Exception(Marshal.GetLastWin32Error());
        if (!AssignProcessToJobObject(job, Process.GetCurrentProcess().Handle))
            throw new Win32Exception(Marshal.GetLastWin32Error());
    }
}
'@

[ServerJob]::AttachLauncher()

Write-Host "Starting frontend on port $FrontendPort and backend on port $BackendPort."
Write-Host 'Press Ctrl+C or close this window to stop both servers.'

$frontendScript = Join-Path $PSScriptRoot 'serve_frontend.py'
$frontend = Start-Process -FilePath $python -ArgumentList "`"$frontendScript`" $FrontendPort" `
    -WorkingDirectory $PSScriptRoot -NoNewWindow -PassThru
$backend = Start-Process -FilePath $python -ArgumentList "-m uvicorn main:app --host 0.0.0.0 --port $BackendPort" `
    -WorkingDirectory (Join-Path $PSScriptRoot 'backend') -NoNewWindow -PassThru

while ($true) {
    if ($frontend.WaitForExit(500)) {
        throw 'Frontend server stopped; stopping backend. See the output above for the cause.'
    }
    if ($backend.WaitForExit(500)) {
        throw 'Backend server stopped; stopping frontend. See the output above for the cause.'
    }
}
