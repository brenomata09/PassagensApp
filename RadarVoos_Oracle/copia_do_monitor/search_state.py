"""Estado e pedidos do painel; a busca continua sendo executada pelo monitor."""
from contextlib import contextmanager
from datetime import date,datetime
from dataclasses import replace
import json
import os
from pathlib import Path
import time
from uuid import uuid4

from request_guard import atomic_json, safe_error

CONFIG_FIELDS=('origin','destination','start_month','end_month',
               'max_one_way_price','max_round_trip_price','interval_minutes')
ACTIVE_STATES={'aguardando','iniciando','buscando'}

def public_config(config):
    return {name:getattr(config,name) for name in CONFIG_FIELDS}

def read_json(path):
    try:
        value=json.loads(Path(path).read_text(encoding='utf-8'))
        return value if isinstance(value,dict) else {}
    except (OSError,ValueError):
        return {}

@contextmanager
def dispatch_lock(base):
    import fcntl
    with (Path(base)/'panel_config.lock').open('a') as handle:
        fcntl.flock(handle,fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle,fcntl.LOCK_UN)

def pending_state(request):
    return {'id':request['id'],'source':'manual','status':'aguardando',
            'config':request['values'],'message':'Aguardando o monitor iniciar a consulta.',
            'results':[],'requested_at':request['requested_at'],
            'updated_at':request['requested_at']}

def read_consultation(base, service=None):
    base=Path(base)
    state=read_json(base/'panel_search_state.json')
    request=read_json(base/'panel_manual_request.json')
    if request and not (service and service.get('em_busca')):
        state=pending_state(request)
    if service and service.get('em_busca') and state.get('status') not in ACTIVE_STATES:
        state={'id':'existing-search','source':'external','status':'buscando','config':{},
               'message':'Acompanhando uma consulta já em andamento na Oracle.',
               'results':[],'updated_at':time.time()}
    if not state:
        return None
    if service is not None and state.get('status') in ACTIVE_STATES:
        age=time.time()-float(state.get('updated_at',0))
        interrupted=(not service.get('ativo')) or (
            state.get('status')=='buscando' and not service.get('em_busca')) or (
            state.get('status')=='iniciando' and age>30 and not service.get('em_busca'))
        if interrupted:
            state=dict(state,status='erro',message='A consulta foi interrompida antes de terminar. Os resultados podem estar incompletos.')
    return state

def request_manual(base, values, service, cooldown_until=0):
    base=Path(base)
    with dispatch_lock(base):
        service=service() if callable(service) else service
        state=read_consultation(base,service)
        if service.get('em_busca') or (state and state.get('status') in ACTIVE_STATES):
            return {'iniciada':False,'acompanhando':True,'consulta':state,
                    'mensagem':'Já existe uma consulta em andamento. Acompanhando essa busca.'}
        if not service.get('ativo'):
            raise ValueError('O monitor está parado na Oracle. A consulta não foi iniciada.')
        if cooldown_until>time.time():
            until=datetime.fromtimestamp(cooldown_until).strftime('%d/%m/%Y %H:%M')
            return {'iniciada':False,'acompanhando':False,'consulta':state,
                    'mensagem':'O Google está em pausa até '+until+' (Brasília). A consulta não iniciou.'}
        request={'id':uuid4().hex,'values':values,'requested_at':time.time()}
        atomic_json(base/'panel_manual_request.json',request)
        return {'iniciada':True,'acompanhando':True,'consulta':pending_state(request),
                'mensagem':'Consulta solicitada na Oracle com os valores da tela.'}

def take_manual_request(base):
    base=Path(base)
    if not (base/'panel_manual_request.json').exists():
        return None
    with dispatch_lock(base):
        return _take_request_locked(base)

def _take_request_locked(base):
    path=base/'panel_manual_request.json'
    request=read_json(path)
    if not request:
        return None
    state=pending_state(request)
    state.update(status='iniciando',message='Preparando a consulta na Oracle.',updated_at=time.time())
    atomic_json(base/'panel_search_state.json',state)
    path.unlink()
    return request

def prepare_run(base,config,request=None):
    # Publica a fase de inicio antes de liberar o pedido para outros paineis.
    # Tambem absorve um clique ocorrido exatamente na hora da busca automatica.
    base=Path(base)
    with dispatch_lock(base):
        request=request or _take_request_locked(base)
        if request:
            config=replace(config,**request['values'])
            config.start_month=max(config.start_month,date.today().strftime('%Y-%m'))
            config.validate()
        source='manual' if request else 'automatic'
        identifier=request['id'] if request else uuid4().hex
        job=SearchJob(base,config,source,identifier)
        job.data.update(status='iniciando',message='Preparando a consulta na Oracle.')
        job.save()
        return config,source,identifier

def result_rows(results, one_way=(), top_per_month=3):
    rows=[]
    for item in results:
        if getattr(item,'quote_only',False):
            continue
        days=(datetime.strptime(item.return_date,'%Y-%m-%d')-
              datetime.strptime(item.depart_date,'%Y-%m-%d')).days
        rows.append({'kind':'Ida e volta','depart_date':item.depart_date,
                     'return_date':item.return_date,'days':days,'price':item.price,
                     'airline':item.airlines or 'Não informada'})
    grouped={}
    for item in one_way:
        grouped.setdefault(item.depart_date[:7],[]).append(item)
    for month,items in sorted(grouped.items()):
        for item in sorted(items,key=lambda item:(item.price,item.depart_date))[:top_per_month]:
            rows.append({'kind':'Ida avulsa','depart_date':item.depart_date,
                         'return_date':'','days':None,'price':item.price,
                         'airline':item.airlines or 'Não informada'})
    return sorted(rows,key=lambda row:(row['kind']=='Ida avulsa',row['depart_date'][:7],row['price'],row['depart_date']))

class SearchJob:
    def __init__(self,base,config,source='automatic',request_id=None):
        self.path=Path(base)/'panel_search_state.json'
        self.config=config
        self.data={'id':request_id or uuid4().hex,'source':source,'status':'buscando',
                   'config':public_config(config),'started_at':datetime.now().isoformat(),
                   'worker_pid':os.getpid(),'message':'Buscando na Oracle…','results':[]}

    def save(self):
        self.data['updated_at']=time.time()
        atomic_json(self.path,self.data)

    def start(self):
        self.save()

    def progress(self,current,total,text):
        self.data.update(message=text)
        self.save()

    def finish(self,results,reason=''):
        self.data.update(status='parcial' if reason else 'concluida',
            message=reason or 'Consulta concluída.',finished_at=datetime.now().isoformat(),
            results=result_rows(results,getattr(self.config,'one_way_results',()),self.config.top_per_month),
            coverage=getattr(self.config,'search_coverage',{}))
        self.save()

    def fail(self,error):
        self.data.update(status='erro',message=safe_error(error),finished_at=datetime.now().isoformat())
        self.save()

def fail_pending(base,error):
    path=Path(base)/'panel_search_state.json'
    state=read_json(path)
    if state.get('status')=='iniciando':
        state.update(status='erro',message=safe_error(error),updated_at=time.time(),
                     finished_at=datetime.now().isoformat())
        atomic_json(path,state)
