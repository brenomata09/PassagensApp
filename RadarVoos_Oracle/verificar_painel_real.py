"""Teste da propria janela e dos botoes com leitura/gravação real e restauração."""
import json
from pathlib import Path
import time
import tkinter as tk

from cliente_oracle import OracleClient
from painel import RadarPanel

client=OracleClient()
original=client.read()
original_values=original['valores']
root=tk.Tk()
root.withdraw()
panel=RadarPanel(root,client=client,autoload=False)

def finish():
    deadline=time.monotonic()+100
    while panel.busy:
        root.update()
        if time.monotonic()>deadline:
            raise RuntimeError('Tempo limite no teste da interface.')
        time.sleep(0.05)
    root.update()

try:
    panel.load()
    finish()
    assert panel.revision, panel.feedback_var.get()
    assert panel._values()==original_values
    print('JANELA_CARREGOU_ORACLE',panel.service_var.get(),flush=True)
    print('TAMANHO_SOLICITADO',root.winfo_reqwidth(),root.winfo_reqheight(),flush=True)
    # Pequena alteracao reversivel para testar a gravacao efetiva. Nenhuma busca e iniciada.
    test_price=original_values['max_one_way_price']+1
    assert test_price<=original_values['max_round_trip_price']
    panel.vars['max_one_way_price'].set(str(test_price))
    panel.apply()
    finish()
    check=client.read()
    assert check['valores']['max_one_way_price']==test_price,panel.feedback_var.get()
    print('BOTAO_APLICAR_GRAVOU_E_RELEU',test_price,flush=True)
    panel.vars['max_one_way_price'].set(str(original_values['max_one_way_price']))
    panel.apply()
    finish()
    check=client.read()
    assert check['valores']==original_values,panel.feedback_var.get()
    assert check['status']['pid']==original['status']['pid']
    assert check['status']['proxima_busca']==original['status']['proxima_busca']
    print('VALORES_ORIGINAIS_RESTAURADOS',json.dumps(check['valores']),flush=True)
    print('SERVICO_E_AGENDAMENTO_PRESERVADOS',check['status']['pid'],flush=True)
finally:
    try:
        latest=client.read()
        if latest['valores']!=original_values:
            client.apply(original_values,latest['revisao'])
    finally:
        root.destroy()
