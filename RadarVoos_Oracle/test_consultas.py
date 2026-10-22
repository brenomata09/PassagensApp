from contextlib import nullcontext
from dataclasses import replace
from datetime import date,timedelta
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'copia_do_monitor'))
if sys.platform=='win32':
    sys.modules['fcntl']=SimpleNamespace()
import search_state as state
import monitor_cli as monitor
import request_guard
from app import FareCandidate,OneWayCandidate

class SearchTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory(dir=ROOT)
        self.base=Path(self.temp.name)
        self.config=monitor.MonitorConfig('BSB','IGU',date.today().strftime('%Y-%m'),
            (date.today()+timedelta(days=90)).strftime('%Y-%m'),3,700,2000,'fli',240,'fake','fake')
        self.values=state.public_config(self.config)
        self.service={'ativo':True,'em_busca':False}
        self.lock=patch.object(state,'dispatch_lock',lambda base:nullcontext())
        self.lock.start()
        out=date.today()+timedelta(days=30)
        self.fare=FareCandidate(out.strftime('%Y-%m'),str(out),str(out+timedelta(days=5)),1200,'Teste','Direto')
    def tearDown(self):
        self.lock.stop()
        self.temp.cleanup()
    def test_manual_request_is_queued_once(self):
        first=state.request_manual(self.base,self.values,self.service)
        second=state.request_manual(self.base,self.values,self.service)
        self.assertTrue(first['iniciada'])
        self.assertFalse(second['iniciada'])
        self.assertEqual(first['consulta']['id'],second['consulta']['id'])
    def test_active_automatic_search_is_followed(self):
        job=state.SearchJob(self.base,self.config)
        job.start()
        response=state.request_manual(self.base,self.values,dict(self.service,em_busca=True))
        self.assertFalse(response['iniciada'])
        self.assertEqual(response['consulta']['id'],job.data['id'])
        self.assertFalse((self.base/'panel_manual_request.json').exists())
    def test_request_claim_is_atomic_and_not_duplicated_during_start(self):
        state.request_manual(self.base,self.values,self.service)
        request=state.take_manual_request(self.base)
        self.assertEqual(request['values'],self.values)
        self.assertIsNone(state.take_manual_request(self.base))
        self.assertFalse(state.request_manual(self.base,self.values,self.service)['iniciada'])
    def test_stopped_monitor_never_queues(self):
        with self.assertRaises(ValueError):
            state.request_manual(self.base,self.values,dict(self.service,ativo=False))
        self.assertFalse((self.base/'panel_manual_request.json').exists())
    def test_cooldown_is_not_bypassed(self):
        result=state.request_manual(self.base,self.values,self.service,time.time()+600)
        self.assertFalse(result['iniciada'])
        self.assertIn('pausa',result['mensagem'])
        self.assertFalse((self.base/'panel_manual_request.json').exists())
    def test_requested_values_do_not_change_automatic_settings(self):
        (self.base/'.env').write_text('configuracao original')
        values=dict(self.values,max_round_trip_price=1500)
        result=state.request_manual(self.base,values,self.service)
        self.assertEqual(result['consulta']['config']['max_round_trip_price'],1500)
        self.assertEqual((self.base/'.env').read_text(),'configuracao original')
    def test_automatic_start_absorbs_click_instead_of_queuing_another_search(self):
        changed=dict(self.values,max_round_trip_price=1500)
        request=state.request_manual(self.base,changed,self.service)
        config,source,identifier=state.prepare_run(self.base,self.config)
        self.assertEqual(source,'manual')
        self.assertEqual(identifier,request['consulta']['id'])
        self.assertEqual(config.max_round_trip_price,1500)
        self.assertFalse((self.base/'panel_manual_request.json').exists())
        self.assertFalse(state.request_manual(self.base,changed,self.service)['iniciada'])
    def test_new_request_recovers_from_stale_job(self):
        state.SearchJob(self.base,self.config).start()
        first=state.request_manual(self.base,self.values,self.service)
        second=state.request_manual(self.base,self.values,self.service)
        self.assertTrue(first['iniciada'])
        self.assertFalse(second['iniciada'])
        self.assertEqual(first['consulta']['id'],second['consulta']['id'])
    def test_service_is_rechecked_inside_request_lock(self):
        probe=lambda:dict(self.service,em_busca=True)
        response=state.request_manual(self.base,self.values,probe)
        self.assertFalse(response['iniciada'])
        self.assertEqual(response['consulta']['status'],'buscando')
    def test_results_are_persisted_and_quotes_excluded(self):
        quote=replace(self.fare,quote_only=True)
        job=state.SearchJob(self.base,self.config,'manual','request-id')
        job.start()
        job.progress(1,2,'Calendário de teste')
        self.assertEqual(state.read_consultation(self.base)['message'],'Calendário de teste')
        job.finish([self.fare,quote])
        result=state.read_consultation(self.base)
        self.assertEqual(result['status'],'concluida')
        self.assertEqual(len(result['results']),1)
        self.assertEqual(result['results'][0]['days'],5)
        self.assertNotIn('telegram_token',result['config'])
    def test_partial_is_not_reported_as_no_offers(self):
        job=state.SearchJob(self.base,self.config)
        job.start()
        job.finish([],'HTTP 429')
        result=state.read_consultation(self.base)
        self.assertEqual(result['status'],'parcial')
        self.assertEqual(result['message'],'HTTP 429')
    def test_failure_preserves_error_state(self):
        job=state.SearchJob(self.base,self.config)
        job.start()
        job.fail(RuntimeError('rede indisponível'))
        self.assertEqual(state.read_consultation(self.base)['status'],'erro')
    def test_crashed_search_is_not_followed_forever(self):
        job=state.SearchJob(self.base,self.config)
        job.start()
        result=state.read_consultation(self.base,self.service)
        self.assertEqual(result['status'],'erro')
    def test_one_way_rows_have_no_invented_return(self):
        rows=state.result_rows([], [OneWayCandidate(self.fare.depart_date,650,'Teste')])
        self.assertEqual(rows[0]['return_date'],'')
        self.assertIsNone(rows[0]['days'])
    def test_same_search_engine_publishes_results(self):
        def fake_search(config,on_status=None):
            on_status(1,2,'Consultando teste')
            return [self.fare],''
        with patch.object(monitor,'BASE_DIR',self.base),patch.object(monitor,'search_lock',lambda:nullcontext()), \
             patch.object(monitor,'_run_search',fake_search),patch.object(monitor.GUARD,'paused_until',return_value=0):
            rows,reason=monitor.run_search(self.config,'manual','same-engine')
        result=state.read_consultation(self.base)
        self.assertEqual(result['id'],'same-engine')
        self.assertEqual(result['status'],'concluida')
        self.assertEqual(rows[0].price,result['results'][0]['price'])
    def test_wait_checks_manual_request_before_sleep(self):
        request={'id':'test'}
        with patch.object(monitor,'take_manual_request',return_value=request),patch.object(monitor.time,'sleep') as sleep:
            self.assertEqual(monitor.wait_until(time.time()+100),request)
            sleep.assert_not_called()
    @unittest.skipIf(sys.platform=='win32','Bloqueio nativo validado na VPS Linux')
    def test_real_lock_preserves_current_job(self):
        job=state.SearchJob(self.base,self.config)
        job.start()
        before=(self.base/'panel_search_state.json').read_text()
        with patch.object(request_guard,'BASE',self.base),patch.object(monitor,'BASE_DIR',self.base):
            with request_guard.search_lock():
                with self.assertRaises(request_guard.SearchPaused):
                    monitor.run_search(self.config)
        self.assertEqual((self.base/'panel_search_state.json').read_text(),before)
    @unittest.skipIf(sys.platform=='win32','Ciclo do servico validado na VPS Linux')
    def test_manual_cycle_preserves_schedule_and_uses_screen_values(self):
        next_run=time.time()+14400
        (self.base/'monitor_schedule.json').write_text(json.dumps({'next_run':next_run}))
        request={'id':'manual-cycle','values':dict(self.values,max_round_trip_price=1500)}
        observed=[]
        def fake_search(config,on_status=None):
            observed.append(config.max_round_trip_price)
            return [self.fare],''
        with patch.object(monitor,'BASE_DIR',self.base), \
             patch.object(monitor.MonitorConfig,'from_env',side_effect=lambda:self.config), \
             patch.object(monitor,'wait_until',side_effect=[request,KeyboardInterrupt]), \
             patch.object(monitor,'search_lock',lambda:nullcontext()), \
             patch.object(monitor,'_run_search',fake_search), \
             patch.object(monitor.GUARD,'paused_until',return_value=0), \
             patch.object(monitor,'send_reliably',return_value=True):
            with self.assertRaises(KeyboardInterrupt):
                monitor.main()
        self.assertEqual(observed,[1500])
        self.assertEqual(json.loads((self.base/'monitor_schedule.json').read_text())['next_run'],next_run)
        self.assertEqual(state.read_consultation(self.base)['source'],'manual')

if __name__=='__main__':
    unittest.main(verbosity=2)
