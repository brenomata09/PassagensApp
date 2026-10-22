"""Operacoes enviadas por SSH. Nunca devolve tokens nem altera o servico."""
import base64
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

FIELDS = {
    'origin': 'FLIGHT_ORIGIN', 'destination': 'FLIGHT_DESTINATION',
    'start_month': 'FLIGHT_START_MONTH', 'end_month': 'FLIGHT_END_MONTH',
    'max_one_way_price': 'FLIGHT_MAX_ONE_WAY',
    'max_round_trip_price': 'FLIGHT_MAX_ROUND_TRIP',
    'interval_minutes': 'MONITOR_INTERVAL_MINUTES',
}

class ConfigConflict(ValueError):
    pass

def public_config(config):
    return {key: getattr(config, key) for key in FIELDS}

def revision(values):
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()

def validate_values(values):
    if set(values) != set(FIELDS):
        raise ValueError('Campos de configuracao invalidos.')
    result = dict(values)
    for name in ('origin', 'destination'):
        value = result[name]
        if not isinstance(value, str) or not re.fullmatch('[A-Za-z]{3}', value.strip()):
            raise ValueError('Origem e destino devem ter tres letras, como BSB e IGU.')
        result[name] = value.strip().upper()
    if result['origin'] == result['destination']:
        raise ValueError('Origem e destino devem ser diferentes.')
    for name in ('max_one_way_price','max_round_trip_price','interval_minutes'):
        if type(result[name]) is not int or result[name] <= 0:
            raise ValueError('Tetos e intervalo devem ser numeros inteiros positivos.')
    if result['max_one_way_price'] > result['max_round_trip_price']:
        raise ValueError('O teto de ida nao pode superar o de ida e volta.')
    if result['max_round_trip_price'] > 1000000 or result['interval_minutes'] > 1440:
        raise ValueError('Teto ou intervalo acima do limite permitido pelo painel.')
    for name in ('start_month','end_month'):
        value = result[name]
        if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d{2}',value):
            raise ValueError('Mes deve estar no formato AAAA-MM.')
        datetime.strptime(value,'%Y-%m')
    result['start_month'] = max(result['start_month'],datetime.now().strftime('%Y-%m'))
    if result['end_month'] < result['start_month']:
        raise ValueError('O mes final deve ser igual ou posterior ao mes inicial atual.')
    return result

def updated_env(text, values):
    updates={FIELDS[key]:str(value) for key,value in values.items()}
    lines=[]
    seen=set()
    for line in text.splitlines():
        key=line.split('=',1)[0].strip()
        if key in updates:
            if key not in seen:
                lines.append(key+'='+updates[key])
                seen.add(key)
        else:
            lines.append(line)
    lines.extend(key+'='+value for key,value in updates.items() if key not in seen)
    return '\n'.join(lines)+'\n'

@contextmanager
def configuration_lock(base):
    import fcntl
    with (base/'panel_config.lock').open('a') as handle:
        fcntl.flock(handle,fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle,fcntl.LOCK_UN)

def write_configuration(base, values, expected_revision, get_config, lock=configuration_lock):
    with lock(base):
        current=get_config()
        old_values=public_config(current)
        if expected_revision != revision(old_values):
            raise ConfigConflict('A configuracao mudou na Oracle. Recarregue antes de aplicar.')
        values=validate_values(values)
        # Reutiliza a validacao do programa real, preservando as credenciais.
        candidate=replace(current,**values)
        candidate.validate()
        if values == old_values:
            return current,False,None
        env=base/'.env'
        old=env.read_text(encoding='utf-8')
        backup=base/('.env.painel-backup-'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
        shutil.copy2(env,backup)
        backup.chmod(0o600)
        temp_path=None
        try:
            with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=base,
                                             prefix='.env.painel-',delete=False) as temp:
                temp_path=Path(temp.name)
                temp.write(updated_env(old,values))
                temp.flush()
                os.fsync(temp.fileno())
            temp_path.chmod(0o600)
            os.replace(temp_path,env)
            reread=get_config()
            if public_config(reread) != values:
                raise RuntimeError('O programa nao confirmou os valores gravados.')
        except Exception:
            # Restauracao atomica se a releitura ou a gravacao falhar.
            if temp_path is not None and temp_path.exists():
                temp_path.unlink()
            restore=base/'.env.painel-restaurar'
            shutil.copy2(backup,restore)
            os.replace(restore,env)
            raise
        return reread,True,backup.name

def service_status(base):
    result=subprocess.run(['systemctl','show','passagensapp.service',
        '-p','ActiveState','-p','SubState','-p','MainPID'],capture_output=True,text=True,timeout=10)
    state=dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)
    info={'ativo':state.get('ActiveState')=='active','estado':state.get('ActiveState','desconhecido'),
          'pid':state.get('MainPID',''),'proxima_busca':None,'em_busca':False,'pausa_ate':None}
    for filename,key,field in [('monitor_schedule.json','next_run','proxima_busca'),
                               ('google_request_state.json','cooldown_until','pausa_ate')]:
        try:
            stamp=float(json.loads((base/filename).read_text())[key])
            if stamp > time.time():
                info[field]=datetime.fromtimestamp(stamp).strftime('%d/%m/%Y %H:%M')
        except (OSError,ValueError,TypeError,KeyError):
            pass
    import fcntl
    with (base/'monitor_search.lock').open('a') as handle:
        try:
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            fcntl.flock(handle,fcntl.LOCK_UN)
        except BlockingIOError:
            info['em_busca']=True
    return info

def snapshot(base, config):
    memory=io.BytesIO()
    manifest={}
    names=['app.py','monitor_cli.py','request_guard.py','search_state.py','run_monitor.sh','requirements.txt']
    paths=[base/name for name in names if (base/name).is_file()]
    vendor=base/'vendor'/'fli_881aee5'
    paths.extend(path for path in vendor.rglob('*') if path.is_file()
                 and '__pycache__' not in path.parts and path.suffix not in ('.pyc','.pyo')
                 and path.resolve().is_relative_to(vendor.resolve()))
    with zipfile.ZipFile(memory,'w',zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            relative=str(path.relative_to(base)).replace('\\','/')
            data=path.read_bytes()
            archive.writestr(relative,data)
            manifest[relative]=hashlib.sha256(data).hexdigest()
        example='\n'.join(FIELDS[key]+'='+str(value) for key,value in public_config(config).items())
        example+='\nFLIGHT_ENGINE=fli\nTELEGRAM_BOT_TOKEN=\nTELEGRAM_CHAT_ID=\n'
        archive.writestr('.env.example',example)
        archive.writestr('ORIGEM_DA_COPIA.json',json.dumps({
            'origem':str(base),'data':datetime.now().isoformat(),'arquivos_sha256':manifest,
            'observacao':'Codigo da VPS; credenciais, .env real, cache e historico nao incluidos.'},indent=2))
    return base64.b64encode(memory.getvalue()).decode('ascii'),len(paths)

def execute(payload):
    os.environ['TZ']='America/Sao_Paulo'
    if hasattr(time,'tzset'):
        time.tzset()
    base=Path(payload.get('pasta_oracle','/home/ubuntu/PassagensApp')).resolve()
    if not base.is_absolute() or not (base/'monitor_cli.py').is_file() or not (base/'app.py').is_file():
        raise ValueError('Pasta do monitor nao encontrada na Oracle.')
    os.chdir(base)
    sys.path.insert(0,str(base))
    from monitor_cli import MonitorConfig
    get_config=MonitorConfig.from_env
    config=get_config()
    action=payload.get('acao')
    if action=='baixar':
        archive,count=snapshot(base,config)
        return {'ok':True,'arquivo_base64':archive,'quantidade_arquivos':count}
    changed=False
    backup=None
    request_result={}
    if action in {'aplicar','buscar'}:
        values=validate_values(payload.get('valores',{}))
        from app import FliAirport
        for key in ('origin','destination'):
            if not hasattr(FliAirport,values[key]):
                raise ValueError('Aeroporto nao reconhecido pelo motor: '+values[key])
        if action=='aplicar':
            config,changed,backup=write_configuration(base,values,payload.get('revisao'),get_config)
        else:
            from request_guard import GUARD
            from search_state import request_manual
            candidate=replace(config,**values)
            candidate.validate()
            request_result=request_manual(base,values,lambda:service_status(base),GUARD.paused_until())
    elif action not in {'ler','consulta'}:
        raise ValueError('Operacao nao permitida.')
    values=public_config(config)
    status=service_status(base)
    try:
        from search_state import read_consultation
        consultation=read_consultation(base,status)
    except ImportError:
        consultation=None
    return {'ok':True,'valores':values,'revisao':revision(values),'alterado':changed,
            'backup':backup,'motor':config.engine_mode,'duracoes':[5,7],
            'status':status,'servidor':str(base),'consulta':consultation,**request_result}

def main():
    try:
        result=execute(json.load(sys.stdin))
    except ConfigConflict as error:
        result={'ok':False,'erro':str(error),'tipo':'conflito'}
    except Exception as error:
        # Nao devolve traceback, conteudo do .env ou URLs com token.
        detail=re.sub(r'bot\d+:[A-Za-z0-9_-]+','bot[oculto]',str(error))[:500]
        result={'ok':False,'erro':detail,'tipo':type(error).__name__}
    print(json.dumps(result,ensure_ascii=True))

if __name__=='__main__':
    main()
