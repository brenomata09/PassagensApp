"""Controle compartilhado de consultas Google Flights e bloqueio entre processos."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import threading
import time

BASE = Path(__file__).resolve().parent

class SearchPaused(RuntimeError):
    pass

def safe_error(error):
    return re.sub(r'bot\d+:[A-Za-z0-9_-]+', 'bot[oculto]', str(error))[:600]

def status_code(error):
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        code = getattr(error, 'status_code', None)
        response = getattr(error, 'response', None)
        code = code or getattr(response, 'status_code', None) or getattr(error, 'code', None)
        if code:
            return int(code)
        if '429' in str(error):
            return 429
        error = error.__cause__ or error.__context__
    return None

def atomic_json(path, value):
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    os.replace(temp, path)

class RequestGuard:
    def __init__(self, path=None, interval=15, retries=2, backoff=60,
                 cooldown=14400, clock=time.time, sleep=time.sleep):
        self.path = Path(path) if path else BASE / 'google_request_state.json'
        self.interval, self.retries = interval, retries
        self.backoff, self.cooldown = backoff, cooldown
        self.clock, self.sleep = clock, sleep
        self.lock = threading.RLock()

    def state(self):
        try:
            return json.loads(self.path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            return {}
        except (ValueError, OSError) as error:
            raise SearchPaused('Estado de espera ilegivel; verificar antes de consultar.') from error

    def paused_until(self):
        return float(self.state().get('cooldown_until', 0))

    def defer(self, seconds):
        with self.lock:
            state = self.state()
            state['cooldown_until'] = max(self.clock() + seconds, state.get('cooldown_until', 0))
            atomic_json(self.path, state)

    def call(self, function, *args, **kwargs):
        # O lock tambem serializa as chamadas internas paralelas do fli.
        with self.lock:
            state = self.state()
            if state.get('cooldown_until', 0) > self.clock():
                raise SearchPaused('Google Flights em pausa por limitacao HTTP 429; nenhuma nova chamada realizada.')
            for attempt in range(self.retries + 1):
                wait = state.get('last_request', 0) + self.interval - self.clock()
                if wait > 0:
                    self.sleep(wait)
                state['last_request'] = self.clock()
                atomic_json(self.path, state)
                try:
                    result = function(*args, **kwargs)
                except Exception as error:
                    if status_code(error) != 429:
                        raise
                    wait = self.backoff * 2 ** attempt
                    response = getattr(error, 'response', None)
                    headers = getattr(response, 'headers', {}) or {}
                    try:
                        wait = max(wait, float(headers.get('Retry-After', 0)))
                    except (TypeError, ValueError):
                        pass
                    if attempt == self.retries or wait > self.cooldown:
                        state['cooldown_until'] = self.clock() + max(wait, self.cooldown)
                        atomic_json(self.path, state)
                        raise SearchPaused('HTTP 429 persistente: consultas pausadas por pelo menos quatro horas.') from error
                    state['cooldown_until'] = self.clock() + wait
                    atomic_json(self.path, state)
                    print('HTTP 429: aguardando %.0f segundos antes da tentativa %d.' % (wait, attempt + 2), flush=True)
                    self.sleep(wait)
                    continue
                state.pop('cooldown_until', None)
                atomic_json(self.path, state)
                return result

GUARD = RequestGuard()

def guarded_fli_client(client):
    if not getattr(client, '_radar_guarded', False):
        for method_name in ('get', 'post'):
            original = getattr(client, method_name)
            # O fli usa tenacity com tentativas rapidas internas. Retira apenas
            # esse decorador para que TODAS as tentativas passem pelo controle.
            raw = getattr(original, '__wrapped__', None)
            if raw is not None:
                original = raw.__get__(client, type(client))
            def wrapped(*args, _original=original, **kwargs):
                return GUARD.call(_original, *args, **kwargs)
            setattr(client, method_name, wrapped)
        client._radar_guarded = True
    return client

@contextmanager
def search_lock():
    import fcntl
    with (BASE / 'monitor_search.lock').open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise SearchPaused('Ja existe uma busca em andamento nesta VPS.') from error
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
