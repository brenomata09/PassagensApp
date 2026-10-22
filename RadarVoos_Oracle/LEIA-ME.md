# Radar de Voos — Controle da Oracle

Abra o atalho **Radar de Voos - Oracle** na Área de Trabalho.

1. O painel carrega os valores atuais diretamente da VPS.
2. Altere os tetos, a rota, os meses ou o intervalo.
3. Para consultar, clique em **Buscar agora**. A consulta manual usa os valores da tela sem alterar a configuração automática.
4. Acompanhe o andamento e os resultados na mesma janela: tipo, ida, volta, dias, preço e companhia.
5. Para salvar permanentemente os valores, clique em **Aplicar na Oracle** e aguarde a confirmação de gravação e releitura.

Se uma consulta já estiver em andamento, o painel acompanha essa consulta e não inicia outra. Você pode fechar a janela: a busca continua na Oracle e seus resultados ficam disponíveis quando o painel for reaberto. Buscas automáticas também aparecem na tabela.

A tabela distingue consulta concluída, resultado parcial e erro. Uma busca que falhou não é apresentada como ausência de ofertas. Só preços confirmados entram nos resultados; a cotação inicial do calendário não é uma confirmação de tarifa.

O painel atualiza o andamento automaticamente. Os avisos pelo Telegram continuam no monitor, como antes. O botão Buscar agora não contorna uma pausa ativa do Google após HTTP 429.

As alterações valem para a próxima busca. Uma busca já em andamento continua com os valores com que começou. O horário já agendado é preservado; o novo intervalo passa a contar depois da próxima busca. O monitor não é reiniciado ao salvar valores.

O teto de ida avulsa é independente do teto de ida e volta. As viagens de ida e volta consideram 5 e 7 dias. A busca consulta os preços de calendário e confirma os menores pares antes de apresentar as ofertas.

## Arquivos

- `painel.py` e `ABRIR_RADAR_ORACLE.pyw`: interface local em Tkinter.
- `cliente_oracle.py`: conexão com a VPS pelo SSH já instalado no Windows.
- `operacoes_oracle.py`: leitura e atualização validada da configuração remota.
- `conexao.json`: endereço e caminho da chave, sem copiar a chave para esta pasta.
- `copia_do_monitor/`: cópia do código que roda na Oracle, incluindo a biblioteca usada pelo motor.
- `copia_do_monitor/search_state.py`: integração entre o monitor e o painel para pedidos, andamento e resultados.

A cópia do monitor contém código de Linux e serve como espelho do programa da VPS. O painel Windows controla a VPS; abrir o atalho não inicia um segundo monitor no PC.

Os tokens do Telegram e o `.env` real permanecem na Oracle. A cópia contém `.env.example`, sem credenciais, sem incluir o registro local dos arquivos baixados.

O botão **Conexão** permite corrigir o endereço ou o caminho da chave caso eles mudem. Use o endereço da sua VPS, o usuário SSH e o caminho remoto do programa.

Cada alteração efetiva cria um backup privado do `.env` na própria Oracle. Se outro painel alterar os valores enquanto a janela estiver aberta, recarregue antes de aplicar novamente.

## Configuração após baixar do GitHub

Copie `conexao.example.json` para `conexao.json` e preencha os dados da sua VPS e o caminho da sua chave SSH. Execute `ABRIR_RADAR_ORACLE.pyw` com Python e Tkinter instalados. O atalho da Área de Trabalho pertence à instalação local e não é incluído no repositório.
