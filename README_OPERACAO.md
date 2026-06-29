# PassagensApp

Robo de monitoramento de passagens.

## Rodar painel

```powershell
.\venv\Scripts\python.exe -m streamlit run web\streamlit_app.py
```

## Rodar busca agora

```powershell
.\venv\Scripts\python.exe run_sweep.py
```

## Rodar monitoramento continuo

```powershell
.\venv\Scripts\python.exe run_scheduler.py
```

Esse processo executa a busca a cada 4 horas e cobre todas as rotas ativas usando apenas `Google Flights` via `fli`.

Por padrao, a fonte `google_flights` fica protegida. Fontes novas registradas em runtime nao entram no sweep enquanto `ALLOW_EXPERIMENTAL_SOURCES` nao estiver definido como `1`. Para recolocar uma segunda fonte, ative essa variavel apenas durante o teste dessa fonte.

## Logica atual

- Fonte ativa: Google Flights via `fli` / `fast-flights`.
- Janela: proximos 245 dias.
- Usa cotacao total ida+volta retornada pelo `fli`.
- Aceita viagens com intervalo de 4 a 15 dias.
- Salva as melhores combinacoes globais e por mes.
- Envia alertas Telegram para:
  - preco abaixo do teto;
  - novo menor preco;
  - preco que superou o teto.

## Regra de teto

O teto mensal calculado e:

```text
teto = preco medio mensal das fontes confiaveis - 30%
```

O teto so e marcado como calculado quando houver pelo menos 5 fontes para a mesma rota e mes. Com menos de 5 fontes, o status fica pendente.

## Regra para fontes de promocao

Fontes de promocao nao entram na media do teto mensal. Elas geram alerta sempre que uma promocao for capturada, inclusive voos internacionais.

Fontes previstas:

- Melhores Destinos
- CVC
- 123Milhas
- Eurodicas
- Buenas Dicas
- Viagem Caribe

## Fontes de preco planejadas

Estas permanecem fora do fluxo ativo por enquanto:

- KAYAK
- Skyscanner
- Momondo
- Mundi
- VoosBaratos
- Trabber
- Decolar
- ViajaNet
- Booking Flights
- Expedia
- Kiwi
- CVC
- 123Milhas
- LATAM
- GOL
- Azul
- Skiplagged

Fonte informativa planejada:

- SeatGuru

## VPS

1. Criar `.env` a partir de `.env.example`.
2. Instalar dependencias com `pip install -r requirements.txt`.
3. Rodar uma busca manual para validar.
4. Para execucao automatica, subir `python run_scheduler.py` como servico no VPS ou agendar `python run_sweep.py` no cron/systemd.
