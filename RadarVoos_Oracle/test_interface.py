from datetime import date,timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

import painel

ROOT=Path(__file__).resolve().parent

class InterfaceTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory(dir=ROOT)
        self.patch=patch.object(painel,'BASE',Path(self.temp.name))
        self.patch.start()
        self.root=tk.Tk()
        self.root.withdraw()
        self.values={'origin':'BSB','destination':'IGU','start_month':date.today().strftime('%Y-%m'),
            'end_month':(date.today()+timedelta(days=90)).strftime('%Y-%m'),
            'max_one_way_price':700,'max_round_trip_price':2000,'interval_minutes':240}
        self.data={'valores':self.values,'revisao':'revision','motor':'fli','consulta':None,
                   'status':{'ativo':True,'estado':'active','em_busca':False,'proxima_busca':'21/10/2026 20:28'}}
        self.client=Mock()
        self.client.read.return_value=self.data
        self.client.search_status.return_value=self.data
        self.panel=painel.RadarPanel(self.root,client=self.client,autoload=False)
        self.panel._render(self.data)
    def tearDown(self):
        self.panel.close()
        self.patch.stop()
        self.temp.cleanup()
    def finish(self):
        deadline=time.monotonic()+5
        while self.panel.busy:
            self.root.update()
            if time.monotonic()>deadline:
                self.fail('Interface nao respondeu ao retorno da consulta')
            time.sleep(.01)
    def state(self,status='concluida',rows=None):
        return {'id':'job-test','source':'manual','status':status,'config':self.values,
                'message':'Mensagem de teste','results':rows or []}
    def test_search_button_uses_screen_values_without_saving(self):
        self.panel.vars['max_round_trip_price'].set('1.500,00')
        self.client.search.return_value=dict(self.data,consulta=self.state('aguardando'),mensagem='Solicitada')
        self.panel.search()
        self.finish()
        self.assertEqual(self.client.search.call_args.args[0]['max_round_trip_price'],1500)
        self.client.apply.assert_not_called()
        self.assertEqual(self.panel.vars['max_round_trip_price'].get(),'1.500,00')
        self.assertTrue(self.panel.search_running)
    def test_active_search_disables_duplicate_request(self):
        self.panel._render_search(dict(self.data,consulta=self.state('buscando')))
        self.panel.search()
        self.client.search.assert_not_called()
    def test_results_show_dates_duration_price_and_airline(self):
        rows=[{'kind':'Ida e volta','depart_date':'2026-11-28','return_date':'2026-12-03',
               'days':5,'price':1252,'airline':'Companhia Teste'}]
        self.panel._render_search(dict(self.data,consulta=self.state(rows=rows)))
        item=self.panel.result_table.get_children()[0]
        values=self.panel.result_table.item(item,'values')
        self.assertEqual(values,('Ida e volta','28/11/2026','03/12/2026','5','R$ 1.252','Companhia Teste'))
    def test_partial_failure_is_not_no_offers(self):
        self.panel._render_search(dict(self.data,consulta=self.state('parcial')))
        self.assertIn('parcial',self.panel.search_status_var.get())
        self.assertNotIn('nenhuma oferta',self.panel.search_status_var.get())
    def test_status_refresh_keeps_pending_form_edits(self):
        self.panel.vars['max_round_trip_price'].set('2500')
        self.panel.events.put(('consulta',dict(self.data,consulta=self.state()),None))
        self.panel._poll()
        self.assertEqual(self.panel.vars['max_round_trip_price'].get(),'2500')
    def test_empty_complete_search_is_explicit(self):
        self.panel._render_search(dict(self.data,consulta=self.state()))
        self.assertIn('nenhuma oferta dentro dos tetos',self.panel.search_status_var.get())
        self.assertFalse(self.panel.search_running)
    def test_active_state_recovers_when_record_disappears(self):
        self.panel._render_search(dict(self.data,consulta=self.state('buscando')))
        self.panel._render_search(self.data)
        self.assertFalse(self.panel.search_running)
        self.assertEqual(str(self.panel.search_button['state']),'normal')

if __name__=='__main__':
    unittest.main(verbosity=2)
