from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime,timedelta
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import cliente_oracle as client
import operacoes_oracle as remote

ROOT=Path(__file__).resolve().parent

@dataclass
class Config:
    origin:str='BSB'
    destination:str='IGU'
    start_month:str=datetime.now().strftime('%Y-%m')
    end_month:str=(datetime.now()+timedelta(days=180)).strftime('%Y-%m')
    max_one_way_price:int=700
    max_round_trip_price:int=2000
    interval_minutes:int=240
    telegram_token:str='segredo-preservado'
    def validate(self):
        remote.validate_values(remote.public_config(self))

class PanelTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory(dir=ROOT)
        self.base=Path(self.tmp.name)
        self.config=Config()
        self.values=remote.public_config(self.config)
        self.key=self.base/'test.key'
        self.key.write_text('teste')
    def tearDown(self):
        self.tmp.cleanup()
    def test_brazilian_money(self):
        for text,expected in [('700',700),('2.000',2000),('R$ 2.000,00',2000),('1.500,00',1500),('2000.00',2000)]:
            with self.subTest(text=text):
                self.assertEqual(client.money_value(text),expected)
    def test_invalid_money(self):
        for text in ['-700','0','1,50','2.00,00','NaN','700;echo x']:
            with self.subTest(text=text),self.assertRaises(ValueError):
                client.money_value(text)
    def test_route_validation(self):
        self.values['destination']='BSB'
        with self.assertRaises(ValueError):
            remote.validate_values(self.values)
    def test_reject_extra_fields(self):
        self.values['telegram_token']='nao pode alterar'
        with self.assertRaises(ValueError):
            remote.validate_values(self.values)
    def test_price_ceiling_order(self):
        self.values['max_one_way_price']=2500
        with self.assertRaises(ValueError):
            remote.validate_values(self.values)
    def test_month_validation(self):
        self.values['end_month']='2026-99'
        with self.assertRaises(ValueError):
            remote.validate_values(self.values)
    def test_env_preserves_secrets_and_removes_duplicate_fields(self):
        text='# configuracao\nTELEGRAM_BOT_TOKEN=segredo\nFLIGHT_MAX_ONE_WAY=500\nFLIGHT_MAX_ONE_WAY=600\nTELEGRAM_CHAT_ID=123\n'
        result=remote.updated_env(text,self.values)
        self.assertIn('TELEGRAM_BOT_TOKEN=segredo\n',result)
        self.assertIn('TELEGRAM_CHAT_ID=123\n',result)
        self.assertEqual(result.count('FLIGHT_MAX_ONE_WAY='),1)
        self.assertIn('FLIGHT_MAX_ONE_WAY=700',result)
    def test_conflict_never_writes(self):
        env=self.base/'.env'
        env.write_text('original')
        with self.assertRaises(remote.ConfigConflict):
            remote.write_configuration(self.base,self.values,'old',lambda:self.config,lock=lambda _:nullcontext())
        self.assertEqual(env.read_text(),'original')
    def test_same_values_do_not_rewrite(self):
        config,changed,backup=remote.write_configuration(self.base,self.values,remote.revision(self.values),
            lambda:self.config,lock=lambda _:nullcontext())
        self.assertFalse(changed)
        self.assertIsNone(backup)
    def test_write_and_readback_preserve_token(self):
        env=self.base/'.env'
        env.write_text(remote.updated_env('TELEGRAM_BOT_TOKEN=segredo\n',self.values))
        new=dict(self.values,max_one_way_price=800)
        calls=[0]
        def read():
            calls[0]+=1
            return Config(max_one_way_price=700 if calls[0]==1 else 800)
        config,changed,backup=remote.write_configuration(self.base,new,remote.revision(self.values),read,lock=lambda _:nullcontext())
        self.assertTrue(changed)
        self.assertEqual(config.max_one_way_price,800)
        self.assertTrue((self.base/backup).exists())
        self.assertIn('TELEGRAM_BOT_TOKEN=segredo',env.read_text())
    def test_failed_readback_restores_original(self):
        env=self.base/'.env'
        env.write_text('conteudo original')
        with self.assertRaises(RuntimeError):
            remote.write_configuration(self.base,dict(self.values,max_one_way_price=800),remote.revision(self.values),
                lambda:self.config,lock=lambda _:nullcontext())
        self.assertEqual(env.read_text(),'conteudo original')
    def test_ssh_options_and_no_shell(self):
        c={'host':'147.15.100.254','usuario':'ubuntu','porta':22,'chave':str(self.key),'pasta_oracle':'/home/ubuntu/PassagensApp'}
        command=client.build_command(c,helper='print(1)',ssh_executable='ssh')
        self.assertIn('BatchMode=yes',command)
        self.assertIn('StrictHostKeyChecking=yes',command)
        self.assertTrue(command[-1].startswith('exec /home/ubuntu/PassagensApp/.venv/bin/python -c '))
    def test_connection_injection_rejected(self):
        c={'host':'-oProxyCommand=bad','usuario':'ubuntu','porta':22,'chave':str(self.key),'pasta_oracle':'/home/ubuntu/PassagensApp'}
        with self.assertRaises(ValueError):
            client.build_command(c,helper='print(1)',ssh_executable='ssh')
    def test_download_manifest_and_no_secret_env(self):
        base=ROOT/'copia_do_monitor'
        self.assertFalse((base/'.env').exists())
        manifest=json.loads((base/'ORIGEM_DA_COPIA.json').read_text())
        for relative,digest in manifest['arquivos_sha256'].items():
            self.assertEqual(hashlib.sha256((base/relative).read_bytes()).hexdigest(),digest,relative)

if __name__=='__main__':
    unittest.main(verbosity=2)
