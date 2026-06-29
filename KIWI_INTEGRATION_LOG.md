# Kiwi Integration Log

## 2026-06-29

- Regra ativa: nao usar navegador, Playwright ou scraping para Kiwi.
- Regra ativa: usar MCP oficial `https://mcp.kiwi.com` via adaptador existente `kiwi_adapter.py`.
- Erros anteriores estudados: seletores mortos, DataDome/CAPTCHA, URL/campos do site e comandos grandes. Decisao: nao repetir automacao web no Kiwi.
- Passo 1 confirmado: `.\venv\Scripts\python.exe -m pip install mcp` concluiu sem erro e instalou `mcp 1.28.1`.
- Erro 1 classificado como AMBIENTE: `kiwi_adapter.py` nao existe na raiz do `PassagensApp`, apesar de ter sido informado como existente.
- Erro 2 classificado como AMBIENTE: busca por arquivo chamado `kiwi_adapter.py` dentro de `PassagensApp` e depois em `C:\Users\breno` nao retornou caminho.
- Erro 3 classificado como AMBIENTE: `rg` em `C:\Users\breno` retornou acesso negado. Proxima tentativa restrita ao projeto alvo.
- Erro 4 classificado como AMBIENTE: `rg "search_flights_kiwi_sync" . -g "*.py"` dentro de `PassagensApp` nao encontrou a funcao.
- Passo 2 falhou: `import kiwi_adapter` retorna `ModuleNotFoundError: No module named 'kiwi_adapter'`.
- Decisao: parar antes de reescrever o adaptador do zero, porque a regra recebida exige usar o adaptador pronto como base.
- Correcao da regra recebida: criar `kiwi_adapter.py` literal nao viola a regra, porque o arquivo veio de fora e nao existia neste projeto.
- Passo 2 confirmado apos criacao: `import kiwi_adapter` funcionou.
- Passo 3 confirmado: `search_flights_kiwi_sync("GRU","MIA","2026-08-15")` retornou lista nao-vazia.
- Passo 4 parcialmente confirmado: primeira oferta real retornou `GRU->MIA`, preco `413`, moeda `EUR`, booking_url `https://on.kiwi.com/8QqQop`.
- Erro 5 classificado como AMBIENTE: comando PowerShell para imprimir formato final quebrou por parsing de `|`/aspas, nao por falha do Kiwi.
- Erro 6 classificado como AMBIENTE: segunda tentativa de impressao formatada quebrou por quoting PowerShell, transformando strings em identificadores.
- Passo 4 confirmado: impressao real retornou `GRU->MIA - 413 EUR - https://on.kiwi.com/8QqQop`.
