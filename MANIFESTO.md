# PassagensApp Manifesto

## Proposito

PassagensApp existe para uma unica coisa: encontrar a passagem mais barata possivel para rotas monitoradas, com foco em preco total real, ida, volta e data.

Se uma funcao nao ajuda a reduzir preco, reduzir incerteza ou validar resultado, ela nao pertence ao fluxo principal.

## Verdade operacional

- O sistema nao deve inventar resultado.
- O sistema nao deve esconder falha como sucesso.
- O sistema nao deve mostrar analise decorativa no lugar de preco.
- O sistema nao deve prometer fonte que nao executa.

Se uma fonte nao retornou dados, o app deve dizer isso.
Se uma fonte foi bloqueada, o app deve registrar isso.
Se um preco nao foi confirmado, o app deve tratar como nao confirmado.

## Regra principal

Preco barato vem primeiro.

Ordem de prioridade:

1. Menor preco total encontrado.
2. Data de ida e volta associadas a esse preco.
3. Fonte que gerou o valor.
4. Confirmacao ou rastreio do dado.

Tudo o mais e secundario.

## Como o sistema deve operar

- Rodar busca automatica em intervalo fixo.
- Monitorar rotas ativas.
- Comparar fontes reais, nao hipoteticas.
- Salvar snapshots de precos.
- Notificar no Telegram quando houver oportunidade ou ruptura de teto.
- Manter historico suficiente para comparar meses e batimentos anteriores.

## O que entra no fluxo principal

- Google Flights
- KAYAK
- Booking
- Kiwi
- Trabber
- VoosBaratos
- Skyscanner

Essas fontes sao tratadas como candidatas de preco.

## O que nao entra no fluxo principal

- Tela confusa
- Grafico que nao ajuda a escolher
- Texto redundante
- Fonte de referencia misturada com fonte executavel
- Resultado sem data
- Resultado sem preco
- Resultado sem rota

## Regra de notificacao

O Telegram deve informar somente o necessario:

- rota
- preco
- ida
- volta

Se houver alerta, o motivo deve ser objetivo.
Se houver teto, o sistema deve explicar se o preco ficou abaixo ou acima.

## Regra de fontes

O registry do projeto deve respeitar tres estados:

- executavel: a fonte roda de verdade
- pendente: a fonte e alvo real de implementacao
- catalogo: a fonte serve para referencia, estudo ou expansao futura

Misturar esses estados destrui a clareza do sistema.

## Regra de simplicidade

Se uma tela, modulo ou mensagem nao ajudar a encontrar o menor preco, ela deve ser simplificada ou removida.

O sistema precisa ser util antes de ser bonito.
Precisa ser honesto antes de ser completo.
Precisa ser enxuto antes de ser sofisticado.

## Regra de evolucao

Toda expansao deve obedecer a esta sequencia:

1. Funciona.
2. Pode ser validado.
3. Pode ser repetido.
4. Pode ser mantido.

Se nao passar por esses quatro pontos, fica fora do fluxo principal.

## Compromisso do projeto

PassagensApp nao e um painel para impressionar.
E um robô de busca de preço.

Seu sucesso e definido por tres perguntas:

- Encontrou o menor preco?
- Mostrou a rota certa?
- Avisou na hora certa?

Se a resposta for sim, o sistema esta cumprindo seu papel.

