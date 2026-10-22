"""Cliente SSH usado pelo painel Windows, somente com a biblioteca padrao."""
import base64
from datetime import datetime
from decimal import Decimal, InvalidOperation
import io
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import zipfile

BASE=Path(__file__).resolve().parent

class OracleError(RuntimeError):
    pass

class ConfigurationConflict(OracleError):
    pass

def money_value(text):
    value=str(text).replace('R$','').replace(' ','').strip()
    if re.fullmatch(r'\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?',value):
        value=value.replace('.','').replace(',','.')
    elif re.fullmatch(r'\d+(?:[.,]\d{1,2})?',value):
        value=value.replace(',','.')
    else:
        raise ValueError('Use um valor como 700, 2.000 ou 2.000,00.')
    try:
        number=Decimal(value)
    except InvalidOperation as error:
        raise ValueError('Preco invalido.') from error
    if not number.is_finite() or number<=0 or number != number.to_integral_value() or number>1000000:
        raise ValueError('Informe um teto positivo em reais inteiros, sem centavos.')
    return int(number)

def friendly_ssh_error(text):
    if 'UNPROTECTED PRIVATE KEY' in text or 'bad permissions' in text.lower():
        return 'O Windows recusou as permissoes da chave SSH. Verifique a chave configurada em Conexao.'
    if 'Permission denied (publickey)' in text:
        return 'A Oracle recusou a chave SSH. Confira o usuario e o arquivo de chave em Conexao.'
    if 'Host key verification failed' in text or 'REMOTE HOST IDENTIFICATION HAS CHANGED' in text:
        return 'A identidade SSH da VPS nao foi confirmada. Confira a identidade do servidor antes de conectar.'
    if 'timed out' in text.lower() or 'Connection refused' in text:
        return 'A VPS nao respondeu. Confira a conexao com a internet, o endereco e a porta SSH.'
    return text.strip()[-800:] or 'Nao foi possivel conectar a Oracle.'

def load_connection(path=BASE/'conexao.json'):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def validate_connection(connection):
    c=dict(connection)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]*',str(c.get('host',''))):
        raise ValueError('Endereco da VPS invalido.')
    if not re.fullmatch(r'[a-z_][a-z0-9_-]*',str(c.get('usuario',''))):
        raise ValueError('Usuario SSH invalido.')
    try:
        c['porta']=int(c.get('porta',22))
    except (ValueError,TypeError) as error:
        raise ValueError('Porta SSH invalida.') from error
    if not 1<=c['porta']<=65535:
        raise ValueError('Porta SSH invalida.')
    c['chave']=str(Path(str(c.get('chave',''))).expanduser())
    if not Path(c['chave']).is_file():
        raise ValueError('Arquivo de chave SSH nao encontrado.')
    root=str(c.get('pasta_oracle',''))
    if not re.fullmatch(r'/[A-Za-z0-9_./-]+',root) or '..' in root.split('/'):
        raise ValueError('Pasta do programa na Oracle invalida.')
    c['pasta_oracle']=root.rstrip('/')
    return c

def build_command(connection, helper=None, ssh_executable=None):
    c=validate_connection(connection)
    helper=helper if helper is not None else (BASE/'operacoes_oracle.py').read_text(encoding='utf-8')
    encoded=base64.b64encode(helper.encode('utf-8')).decode('ascii')
    code="import base64;exec(compile(base64.b64decode(%r),'<painel-oracle>','exec'))"%encoded
    python=c['pasta_oracle']+'/.venv/bin/python'
    remote='exec '+shlex.quote(python)+' -c '+shlex.quote(code)
    ssh=ssh_executable or shutil.which('ssh.exe') or shutil.which('ssh')
    if not ssh:
        raise OracleError('O cliente SSH do Windows nao foi encontrado.')
    return [ssh,'-o','BatchMode=yes','-o','StrictHostKeyChecking=yes',
            '-o','ConnectTimeout=12','-o','ServerAliveInterval=10','-o','ServerAliveCountMax=2',
            '-p',str(c['porta']),'-i',c['chave'],c['usuario']+'@'+c['host'],remote]

class OracleClient:
    def __init__(self,connection=None):
        self.connection=connection if connection is not None else load_connection()

    def call(self,action,**extra):
        command=build_command(self.connection)
        payload={'acao':action,'pasta_oracle':self.connection['pasta_oracle'],**extra}
        try:
            result=subprocess.run(command,input=json.dumps(payload),capture_output=True,
                text=True,encoding='utf-8',errors='replace',timeout=90,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        except subprocess.TimeoutExpired as error:
            raise OracleError('A Oracle demorou para responder. Recarregue para conferir o resultado antes de aplicar novamente.') from error
        if result.returncode:
            raise OracleError(friendly_ssh_error(result.stderr))
        try:
            data=json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise OracleError('A VPS respondeu em um formato inesperado. Nenhuma confirmacao de gravacao foi recebida.') from error
        if not data.get('ok'):
            exception=ConfigurationConflict if data.get('tipo')=='conflito' else OracleError
            raise exception(data.get('erro','Operacao nao concluida na Oracle.'))
        return data

    def read(self):
        return self.call('ler')

    def apply(self,values,revision):
        return self.call('aplicar',valores=values,revisao=revision)

    def search(self,values):
        return self.call('buscar',valores=values)

    def search_status(self):
        return self.call('consulta')

    def download(self,destination):
        data=self.call('baixar')
        destination=Path(destination).resolve()
        destination.mkdir(parents=True,exist_ok=True)
        archive=base64.b64decode(data['arquivo_base64'],validate=True)
        with zipfile.ZipFile(io.BytesIO(archive)) as snapshot:
            for entry in snapshot.infolist():
                path=(destination/entry.filename).resolve()
                if not path.is_relative_to(destination):
                    raise OracleError('Arquivo com caminho invalido recebido da VPS.')
                if entry.is_dir():
                    path.mkdir(parents=True,exist_ok=True)
                else:
                    path.parent.mkdir(parents=True,exist_ok=True)
                    path.write_bytes(snapshot.read(entry))
        return data['quantidade_arquivos']
