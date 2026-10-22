"""Painel Tkinter local para configurar o monitor que roda na Oracle."""
from datetime import datetime
import json
import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from cliente_oracle import BASE, OracleClient, ConfigurationConflict, load_connection, money_value, validate_connection
from operacoes_oracle import validate_values

class RadarPanel:
    def __init__(self, root, client=None, autoload=True):
        self.root=root
        self.client=client or OracleClient()
        self.events=queue.Queue()
        self.revision=None
        self.busy=False
        self.search_running=False
        self.search_poll_busy=False
        self.search_timer=None
        self.results_signature=None
        self.controls=[]
        self.vars={}
        self.root.title('Radar de Voos — Controle da Oracle')
        self.root.geometry('1000x900')
        self.root.minsize(900,840)
        icon=BASE/'radar.ico'
        if icon.exists():
            self.root.iconbitmap(str(icon))
        self._style()
        self._build()
        self.poll_timer=self.root.after(100,self._poll)
        self.root.protocol('WM_DELETE_WINDOW',self.close)
        if autoload:
            self.root.after(250,self.load)

    def _style(self):
        style=ttk.Style(self.root)
        if 'vista' in style.theme_names():
            style.theme_use('vista')
        self.root.configure(bg='#F2F5FA')
        style.configure('TFrame',background='#F2F5FA')
        style.configure('TLabel',background='#F2F5FA',font=('Segoe UI',10))
        style.configure('Title.TLabel',font=('Segoe UI',21,'bold'),foreground='#16345B')
        style.configure('Hint.TLabel',foreground='#52647A',font=('Segoe UI',10))
        style.configure('Status.TLabel',font=('Segoe UI',11,'bold'),foreground='#16345B')
        style.configure('TLabelframe',background='#F2F5FA')
        style.configure('TLabelframe.Label',background='#F2F5FA',foreground='#16345B',font=('Segoe UI',11,'bold'))
        style.configure('TButton',font=('Segoe UI',10),padding=(10,7))
        style.configure('Primary.TButton',font=('Segoe UI',11,'bold'),padding=(14,8))
        style.configure('Treeview',font=('Segoe UI',10),rowheight=25)
        style.configure('Treeview.Heading',font=('Segoe UI',10,'bold'))

    def _build(self):
        outer=ttk.Frame(self.root,padding=16)
        outer.pack(fill='both',expand=True)
        ttk.Label(outer,text='Radar de Voos · Oracle',style='Title.TLabel').pack(anchor='w')
        ttk.Label(outer,text='Consulte passagens e configure o monitor da Oracle.',style='Hint.TLabel').pack(anchor='w',pady=(3,10))
        status=ttk.LabelFrame(outer,text='Monitor na Oracle',padding=10)
        status.pack(fill='x',pady=(0,12))
        self.service_var=tk.StringVar(value='Conectando à Oracle…')
        self.schedule_var=tk.StringVar(value='Aguardando leitura da configuração.')
        self.confirmed_var=tk.StringVar(value='')
        ttk.Label(status,textvariable=self.service_var,style='Status.TLabel').pack(anchor='w')
        ttk.Label(status,textvariable=self.schedule_var,wraplength=820).pack(anchor='w',pady=(3,0))
        ttk.Label(status,textvariable=self.confirmed_var,style='Hint.TLabel').pack(anchor='w',pady=(3,0))

        settings=ttk.LabelFrame(outer,text='Consulta e busca automática',padding=10)
        settings.pack(fill='x',pady=(0,12))
        for col in range(4):
            settings.columnconfigure(col,weight=1)
        self._field(settings,'Ida avulsa (R$)','max_one_way_price',0,0,width=18)
        self._field(settings,'Ida e volta (R$)','max_round_trip_price',0,1,width=18)
        self._field(settings,'Intervalo em horas','interval_hours',0,2,width=12)
        ttk.Label(settings,text='Duração da viagem').grid(row=0,column=3,sticky='w',pady=(0,4))
        ttk.Label(settings,text='5 e 7 dias',style='Status.TLabel').grid(row=1,column=3,sticky='w')
        self._field(settings,'Origem','origin',2,0,width=12)
        self._field(settings,'Destino','destination',2,1,width=12)
        self._field(settings,'Mês inicial (AAAA-MM)','start_month',2,2,width=16)
        self._field(settings,'Mês final (AAAA-MM)','end_month',2,3,width=16)
        ttk.Label(settings,text='Tetos independentes para ida e ida e volta · Somente datas de hoje em diante',style='Hint.TLabel').grid(row=4,column=0,columnspan=4,sticky='w',pady=(10,0))

        actions=ttk.Frame(outer)
        actions.pack(fill='x',pady=(0,8))
        self.load_button=ttk.Button(actions,text='Carregar da Oracle',command=self.load)
        self.load_button.pack(side='left')
        self.apply_button=ttk.Button(actions,text='Aplicar na Oracle',command=self.apply,style='Primary.TButton',state='disabled')
        self.apply_button.pack(side='left',padx=8)
        self.search_button=ttk.Button(actions,text='Buscar agora',command=self.search,style='Primary.TButton',state='disabled')
        self.search_button.pack(side='left')
        self.connection_button=ttk.Button(actions,text='Conexão',command=self.connection_dialog)
        self.connection_button.pack(side='right')
        ttk.Label(outer,text='Buscar agora usa os valores da tela. Aplicar na Oracle altera a busca automática.',style='Hint.TLabel').pack(anchor='w')
        self.feedback_var=tk.StringVar(value='')
        ttk.Label(outer,textvariable=self.feedback_var,wraplength=820,style='Status.TLabel').pack(anchor='w',pady=(10,5))
        results=ttk.LabelFrame(outer,text='Resultado da consulta',padding=8)
        results.pack(fill='both',expand=True,pady=(4,0))
        self.search_status_var=tk.StringVar(value='Nenhuma consulta registrada.')
        self.search_detail_var=tk.StringVar(value='Clique em Buscar agora para consultar na Oracle.')
        ttk.Label(results,textvariable=self.search_status_var,style='Status.TLabel').pack(anchor='w')
        ttk.Label(results,textvariable=self.search_detail_var,wraplength=920,style='Hint.TLabel').pack(anchor='w',pady=(3,5))
        self.search_progress=ttk.Progressbar(results,mode='indeterminate')
        self.search_progress.pack(fill='x',pady=(0,6))
        table_frame=ttk.Frame(results)
        table_frame.pack(fill='both',expand=True)
        columns=('kind','depart','return','days','price','airline')
        self.result_table=ttk.Treeview(table_frame,columns=columns,show='headings',height=6)
        for name,label,width in [('kind','Tipo',110),('depart','Ida',100),('return','Volta',100),
                                  ('days','Dias',50),('price','Preço',100),('airline','Companhia',270)]:
            self.result_table.heading(name,text=label)
            self.result_table.column(name,width=width,minwidth=45,anchor='w' if name in {'kind','airline'} else 'center')
        self.result_table.pack(side='left',fill='both',expand=True)
        scroll=ttk.Scrollbar(table_frame,command=self.result_table.yview)
        scroll.pack(side='right',fill='y')
        self.result_table.configure(yscrollcommand=scroll.set)
        bottom=ttk.Frame(outer)
        bottom.pack(fill='x',pady=(8,0))
        ttk.Button(bottom,text='Abrir cópia baixada',command=self.open_snapshot).pack(side='left')
        ttk.Label(bottom,text='RadarVoos_Oracle',style='Hint.TLabel').pack(side='right')

    def _field(self,parent,label,key,row,col,width=16):
        ttk.Label(parent,text=label).grid(row=row,column=col,sticky='w',padx=(0,12),pady=(8 if row else 0,4))
        variable=tk.StringVar()
        self.vars[key]=variable
        entry=ttk.Entry(parent,textvariable=variable,width=width,font=('Segoe UI',12))
        entry.grid(row=row+1,column=col,sticky='ew',padx=(0,12))
        self.controls.append(entry)

    def _set_busy(self,busy,text=''):
        self.busy=busy
        for item in self.controls:
            item.configure(state='disabled' if busy else 'normal')
        for button in (self.load_button,self.connection_button):
            button.configure(state='disabled' if busy else 'normal')
        self.apply_button.configure(state='disabled' if busy or not self.revision else 'normal')
        self.search_button.configure(state='disabled' if busy or not self.revision or self.search_running else 'normal')
        self.root.configure(cursor='watch' if busy else '')
        if text:
            self.feedback_var.set(text)

    def _log(self,text):
        self.feedback_var.set(text)

    def _start(self,action,operation):
        if self.busy:
            return
        messages={'ler':'Carregando da Oracle…','aplicar':'Salvando e conferindo na Oracle…',
                  'buscar':'Solicitando a consulta na Oracle…'}
        self._set_busy(True,messages[action])
        def worker():
            try:
                self.events.put((action,operation(),None))
            except Exception as error:
                self.events.put((action,None,error))
        threading.Thread(target=worker,daemon=True).start()

    def load(self):
        self._start('ler',self.client.read)

    def _values(self):
        hours=self.vars['interval_hours'].get().strip()
        if not hours.isdigit() or not 1<=int(hours)<=24:
            raise ValueError('Informe um intervalo inteiro de 1 a 24 horas.')
        values={name:self.vars[name].get().strip() for name in ('origin','destination','start_month','end_month')}
        values.update(max_one_way_price=money_value(self.vars['max_one_way_price'].get()),
                      max_round_trip_price=money_value(self.vars['max_round_trip_price'].get()),
                      interval_minutes=int(hours)*60)
        return validate_values(values)

    def apply(self):
        if self.busy or not self.revision:
            return
        try:
            values=self._values()
        except ValueError as error:
            messagebox.showerror('Confira os valores',str(error),parent=self.root)
            return
        revision=self.revision
        self._start('aplicar',lambda:self.client.apply(values,revision))

    def search(self):
        if self.busy or not self.revision or self.search_running:
            return
        try:
            values=self._values()
        except ValueError as error:
            messagebox.showerror('Confira os valores',str(error),parent=self.root)
            return
        self._start('buscar',lambda:self.client.search(values))

    def _schedule_search_poll(self,delay=5000):
        if self.search_timer:
            self.root.after_cancel(self.search_timer)
        self.search_timer=self.root.after(delay,self._refresh_search)

    def _refresh_search(self):
        self.search_timer=None
        if self.busy or self.search_poll_busy:
            self._schedule_search_poll(1000)
            return
        self.search_poll_busy=True
        client=self.client
        def worker():
            try:
                self.events.put(('consulta',client.search_status(),None))
            except Exception as error:
                self.events.put(('consulta',None,error))
        threading.Thread(target=worker,daemon=True).start()

    def _render_search(self,data):
        state=data.get('consulta')
        if not state:
            self.search_running=False
            self.search_status_var.set('Nenhuma consulta registrada.')
            self.search_detail_var.set('Clique em Buscar agora para consultar na Oracle.')
            self.search_progress.stop()
            self.result_table.delete(*self.result_table.get_children())
            self.results_signature=None
            self.search_button.configure(state='disabled' if self.busy or not self.revision else 'normal')
            return
        status=state.get('status','erro')
        was_running=self.search_running
        self.search_running=status in {'aguardando','iniciando','buscando'}
        labels={'aguardando':'Aguardando início','iniciando':'Iniciando','buscando':'Buscando',
                'concluida':'Concluída','parcial':'Resultado parcial','erro':'Consulta não concluída'}
        config=state.get('config',{})
        source={'manual':'Manual','automatic':'Automática','external':'Oracle'}.get(state.get('source'),'Oracle')
        title=labels.get(status,status)+' · '+source
        if config:
            title+=' · '+config.get('origin','')+' → '+config.get('destination','')
        rows=state.get('results',[])
        if status=='concluida':
            title+=' · '+(str(len(rows))+' opções' if rows else 'nenhuma oferta dentro dos tetos')
        self.search_status_var.set(title)
        detail=state.get('message','')
        finished=state.get('finished_at')
        if finished:
            try:
                detail+=' Finalizada em '+datetime.fromisoformat(finished).strftime('%d/%m às %H:%M')+'.'
            except ValueError:
                pass
        self.search_detail_var.set(detail)
        if self.search_running and not was_running:
            self.search_progress.start(20)
        elif not self.search_running:
            self.search_progress.stop()
        signature=json.dumps((state.get('id'),rows),sort_keys=True)
        if signature!=self.results_signature:
            self.result_table.delete(*self.result_table.get_children())
            def br(value):
                if not value:
                    return '—'
                try:
                    return datetime.strptime(value,'%Y-%m-%d').strftime('%d/%m/%Y')
                except ValueError:
                    return value
            for row in rows:
                price=f"R$ {row['price']:,.0f}".replace(',','.')
                self.result_table.insert('', 'end',values=(row['kind'],br(row['depart_date']),
                    br(row.get('return_date')),row.get('days') or '—',price,row.get('airline','')))
            self.results_signature=signature
        self.search_button.configure(state='disabled' if self.busy or not self.revision or self.search_running else 'normal')

    def _render(self,data):
        values=data['valores']
        for key in ('origin','destination','start_month','end_month'):
            self.vars[key].set(str(values[key]))
        for key in ('max_one_way_price','max_round_trip_price'):
            self.vars[key].set(f'{values[key]:,}'.replace(',','.'))
        minutes=values['interval_minutes']
        self.vars['interval_hours'].set(str(minutes//60) if minutes%60==0 else str(minutes/60))
        self.revision=data['revisao']
        self._render_monitor_status(data)
        self._render_search(data)
        self.confirmed_var.set('Valores conferidos na Oracle em '+datetime.now().strftime('%d/%m/%Y às %H:%M:%S'))
        try:
            (BASE/'ultimo_estado.json').write_text(json.dumps({
                'pid_painel':os.getpid(),'conferido_em':datetime.now().isoformat(),
                'valores':values,'status_oracle':data['status'],
                'versao_painel':2,'botao_consulta':str(self.search_button['text']),
                'colunas_resultados':list(self.result_table['columns'])},ensure_ascii=False,indent=2),encoding='utf-8')
        except OSError:
            pass

    def _render_monitor_status(self,data):
        status=data['status']
        state='Monitor ativo na Oracle' if status['ativo'] else 'Monitor parado na Oracle: '+status['estado']
        self.service_var.set(state)
        next_run=status.get('proxima_busca')
        if status.get('em_busca'):
            schedule='Busca em andamento. Novos valores valem a partir da próxima busca.'
        elif next_run:
            schedule='Próxima busca agendada: '+next_run+' (Brasília)'
        else:
            schedule='Próximo horário não informado pela VPS.'
        if status.get('pausa_ate'):
            schedule+=' · Pausa do Google até '+status['pausa_ate']
        self.schedule_var.set(schedule)

    def _poll(self):
        try:
            while True:
                action,data,error=self.events.get_nowait()
                if action=='consulta':
                    self.search_poll_busy=False
                    if error:
                        self.search_detail_var.set('Não foi possível atualizar a consulta: '+str(error))
                    else:
                        self._render_monitor_status(data)
                        self._render_search(data)
                    self._schedule_search_poll(10000 if error else (5000 if self.search_running else 30000))
                    continue
                if error:
                    text=str(error)
                    if isinstance(error,ConfigurationConflict):
                        self.revision=None
                    self.feedback_var.set('Não foi possível concluir: '+text)
                    self._log('Operação não confirmada. '+text)
                else:
                    if action=='buscar':
                        self._render_monitor_status(data)
                        self._render_search(data)
                        text=data.get('mensagem','Consulta solicitada na Oracle.')
                    else:
                        self._render(data)
                    if action=='aplicar':
                        text=('Valores salvos e confirmados na Oracle.' if data.get('alterado')
                              else 'A Oracle já está com esses valores. Configuração conferida.')
                        self._log(text+' Ida: R$ '+str(data['valores']['max_one_way_price'])+
                                  '; ida e volta: R$ '+str(data['valores']['max_round_trip_price'])+'.')
                    elif action=='ler':
                        text='Configuração carregada diretamente da Oracle.'
                        self._log(text)
                    self.feedback_var.set(text)
                self._set_busy(False)
                self._schedule_search_poll(1200)
        except queue.Empty:
            pass
        self.poll_timer=self.root.after(100,self._poll)

    def close(self):
        for timer in (self.poll_timer,self.search_timer):
            if timer:
                try:
                    self.root.after_cancel(timer)
                except tk.TclError:
                    pass
        self.root.destroy()

    def connection_dialog(self):
        dialog=tk.Toplevel(self.root)
        dialog.title('Conexão com a Oracle')
        dialog.transient(self.root)
        dialog.grab_set()
        frame=ttk.Frame(dialog,padding=18)
        frame.pack(fill='both',expand=True)
        connection=dict(self.client.connection)
        variables={}
        labels={'host':'Endereço da VPS','usuario':'Usuário','porta':'Porta SSH',
                'chave':'Arquivo da chave de acesso','pasta_oracle':'Pasta do programa na Oracle'}
        for row,(key,label) in enumerate(labels.items()):
            ttk.Label(frame,text=label).grid(row=row*2,column=0,sticky='w',pady=(7,3))
            variable=tk.StringVar(value=str(connection.get(key,'')))
            variables[key]=variable
            ttk.Entry(frame,textvariable=variable,width=68).grid(row=row*2+1,column=0,sticky='ew')
            if key=='chave':
                def choose():
                    path=filedialog.askopenfilename(parent=dialog,title='Escolha a chave SSH',
                        filetypes=[('Chaves SSH','*.key *.pem'),('Todos os arquivos','*.*')])
                    if path:
                        variables['chave'].set(path)
                ttk.Button(frame,text='Procurar…',command=choose).grid(row=row*2+1,column=1,padx=(8,0))
        def save():
            try:
                result=validate_connection({key:var.get().strip() for key,var in variables.items()})
            except ValueError as error:
                messagebox.showerror('Confira a conexão',str(error),parent=dialog)
                return
            path=BASE/'conexao.json'
            temp=path.with_suffix('.tmp')
            temp.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            os.replace(temp,path)
            self.client=OracleClient(result)
            self.revision=None
            dialog.destroy()
            self.load()
        ttk.Button(frame,text='Salvar conexão e carregar',command=save).grid(row=12,column=0,sticky='e',pady=(16,0))

    def open_snapshot(self):
        path=BASE/'copia_do_monitor'
        if path.exists():
            os.startfile(path)
        else:
            messagebox.showinfo('Cópia local','A cópia do monitor ainda não foi baixada.',parent=self.root)

def main():
    root=tk.Tk()
    try:
        RadarPanel(root)
    except Exception as error:
        messagebox.showerror('Radar de Voos','Não foi possível abrir o painel: '+str(error),parent=root)
        root.destroy()
        return
    root.mainloop()

if __name__=='__main__':
    main()
