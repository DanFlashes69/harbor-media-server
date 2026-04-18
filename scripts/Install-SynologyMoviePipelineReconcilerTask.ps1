[CmdletBinding()]
param(
    [string]$NasHost = 'synology.example.lan',
    [string]$NasUser = 'harboradmin',
    [string]$NasPassword = 'change_me'
)

$ErrorActionPreference = 'Stop'

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$sourceScript = Join-Path $repoRoot 'scripts\movie_pipeline_reconciler.py'
$nasScriptPath = "\\$NasHost\docker\harbor\stacks\harbor-media-server\scripts\movie_pipeline_reconciler.py"
$taskName = 'Harbor Movie Pipeline Reconciler'
$taskCommand = '/usr/bin/python3 /volume1/docker/harbor/stacks/harbor-media-server/scripts/movie_pipeline_reconciler.py'

Copy-Item -LiteralPath $sourceScript -Destination $nasScriptPath -Force

$python = @"
import json
import requests
from synology_api import task_scheduler

host = r'''$NasHost'''
port = '5000'
user = r'''$NasUser'''
password = r'''$NasPassword'''
task_name = r'''$taskName'''
task_command = r'''$taskCommand'''

ts = task_scheduler.TaskScheduler(host, port, user, password, secure=False, cert_verify=False, dsm_version=7, debug=False)
task_list = ts.get_task_list()['data']['tasks']
for task in task_list:
    if task.get('name') == task_name:
        ts.task_delete(task['id'], task['real_owner'])

session = requests.Session()
login = session.get(
    f'http://{host}:5000/webapi/auth.cgi',
    params={
        'api': 'SYNO.API.Auth',
        'version': '7',
        'method': 'login',
        'account': user,
        'passwd': password,
        'session': 'Core',
        'format': 'cookie',
    },
    timeout=20,
)
login.raise_for_status()
login_data = login.json()
if not login_data.get('success'):
    raise SystemExit(f'Login failed: {login.text}')

schedule = {
    'date_type': 0,
    'monthly_week': '[]',
    'hour': 0,
    'minute': 0,
    'repeat_hour': 0,
    'repeat_min': 10,
    'last_work_hour': 23,
    'week_day': '0,1,2,3,4,5,6',
    'repeat_date': 1001,
}
extra = {
    'notify_enable': False,
    'notify_mail': '',
    'notify_if_error': False,
    'script': task_command,
}

create = session.get(
    f'http://{host}:5000/webapi/entry.cgi',
    params={
        'api': 'SYNO.Core.TaskScheduler',
        'version': '4',
        'method': 'create',
        'name': task_name,
        'real_owner': user,
        'owner': user,
        'enable': 'true',
        'schedule': json.dumps(schedule),
        'extra': json.dumps(extra),
        'type': 'script',
    },
    timeout=20,
)
create.raise_for_status()
create_data = create.json()
if not create_data.get('success'):
    raise SystemExit(f'Create failed: {create.text}')

task_id = create_data['data']['id']
task_list = ts.get_task_list()['data']['tasks']
created = next(task for task in task_list if task.get('id') == task_id)
ts.task_run(task_id, created['real_owner'])
print(json.dumps({'task_id': task_id, 'real_owner': created['real_owner']}, indent=2))
"@

$python | python -

