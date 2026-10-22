"""Instalacao da integracao de consultas, validada em staging e com backup."""
from datetime import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import py_compile
import shutil
import subprocess
import sys
import time

root=Path('/home/ubuntu/PassagensApp')
payload=json.load(sys.stdin)
expected=payload.pop('expected_monitor_sha')
assert set(payload)=={'monitor_cli.py','search_state.py','test_consultas.py','test_regressoes.py'}
stamp=datetime.now().strftime('%Y%m%d_%H%M%S')
stage=root/('validacao_consultas_'+stamp)
copy=stage/'copia_do_monitor'
copy.mkdir(parents=True,mode=0o700)
for name in ('app.py','request_guard.py'):
    shutil.copy2(root/name,copy/name)
for name,text in payload.items():
    folder=stage if name.startswith('test_') else copy
    (folder/name).write_text(text,encoding='utf-8')
    py_compile.compile(str(folder/name),doraise=True)
python=str(root/'.venv/bin/python')
env=os.environ.copy()
env['PYTHONPATH']=os.pathsep.join([str(copy),str(root/'vendor'/'fli_881aee5')])
for test in ('test_consultas.py','test_regressoes.py'):
    subprocess.run([python,test,'-q'],cwd=stage,env=env,check=True)
assert hashlib.sha256((root/'monitor_cli.py').read_bytes()).hexdigest()==expected,'O monitor remoto mudou durante a preparacao.'
backup=root/('backup_consultas_painel_'+stamp)
backup.mkdir(mode=0o700)
old_search_state=(root/'search_state.py').exists()
for name in ('monitor_cli.py','search_state.py'):
    if (root/name).exists():
        shutil.copy2(root/name,backup/name)

with (root/'monitor_search.lock').open('a') as handle:
    try:
        fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        raise RuntimeError('Existe uma busca ativa. Atualizacao nao aplicada para preserva-la.')
    subprocess.run(['sudo','-n','systemctl','stop','passagensapp.service'],check=True)
    try:
        for name in ('monitor_cli.py','search_state.py'):
            shutil.copy2(copy/name,root/name)
            py_compile.compile(str(root/name),doraise=True)
        subprocess.run([python,'-c',
            'import monitor_cli,search_state; '
            'assert "on_status" in __import__("inspect").signature(monitor_cli._run_search).parameters; '
            'print("INTEGRACAO_CONSULTAS_OK_SEM_BUSCAR_VOOS")'],cwd=root,check=True)
    except Exception:
        shutil.copy2(backup/'monitor_cli.py',root/'monitor_cli.py')
        if old_search_state:
            shutil.copy2(backup/'search_state.py',root/'search_state.py')
        elif (root/'search_state.py').exists():
            (root/'search_state.py').unlink()
        raise
    finally:
        fcntl.flock(handle,fcntl.LOCK_UN)

subprocess.run(['sudo','-n','systemctl','start','passagensapp.service'],check=True)
time.sleep(2)
subprocess.run(['systemctl','is-active','passagensapp.service'],check=True)
print('BACKUP',backup)
print('CONSULTAS_PAINEL_INSTALADAS')
