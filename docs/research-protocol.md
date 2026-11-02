# Protocolo experimental: envenenamento de CMCD no Content Steering

## Pergunta e escopo

Como a sensibilidade da recompensa usada pelo UCB1 altera a capacidade de
clientes que declaram um `ttlb` falso para a CDN-1 de desviar decisões do CSS,
afetar o rebuffer de clientes honestos e elevar o custo unitário de tráfego?
O estudo usa dez players DASH por execução e três CDNs. A recompensa
`R_lambda = d / (d + lambda × ttlb)` é uma escolha deste simulador, não uma
fórmula prescrita por CMCD ou Content Steering. A unidade de aprendizado é
uma resposta de vídeo elegível, enquanto o eixo de ataque é a **quantidade de
clientes modificados**. Consulte [design.md](design.md) para o fluxo de
telemetria e as condições de aceitação.

## Desenho experimental concluído

| Regime | `lambda` | Clientes modificados (`M`) | `ttlb` declarado para CDN-1 (ms) |
| --- | ---: | --- | --- |
| Baixa sensibilidade (`low`) | 1 | 1–6 | 90, 200, 340, 530, 800, 1200 |
| Média sensibilidade (`medium`) | 10 | 1–6 | 90, 200, 340, 530, 800, 1200 |
| Alta sensibilidade (`high`) | 25 | 1–6 | 90, 200, 340, 530, 800, 1200 |

São três coeficientes da mesma família de recompensa, não categorias
universais de sensibilidade. O atacante controla o `ttlb` declarado e não
precisa conhecer a fórmula para escolher um valor. `d` e `ttlb` são medidos
em milissegundos. A sensibilidade local é
`|∂R/∂ttlb| = lambda × d / (d + lambda × ttlb)^2`; ela depende também do
`ttlb` e não cresce indefinidamente com `lambda` para um `ttlb` fixo.
Alterar `lambda` muda ainda a escala das diferenças de recompensa perante o
bônus de exploração fixo do UCB1. Assim, cada regime representa uma política
operacional completa, e o efeito observado não pode ser atribuído apenas à
derivada.

Cada matriz 6 × 6 contém duas execuções de ataque por célula, em duas ordens
embaralhadas e registradas, e seis controles limpos intercalados após cada
bloco de seis ataques da primeira passagem, inclusive no fim. A segunda
passagem reutiliza os seis controles. Total por regime: **72 ataques e seis
controles válidos**. Cada execução usa um `run_id` novo, dez players, UCB1,
120 s, ataque a partir de 40 s, janela de análise 40–120 s, vídeo 576p e o
mesmo manifesto NetChaos (atrasos configurados de 4/12/9 ms nas CDNs 1/2/3).
Os clientes maliciosos substituem clientes honestos; continuam baixando vídeo
real e alteram apenas o `ttlb` de respostas elegíveis da CDN-1.

O runner aguarda a remoção dos pods de clientes e dos objetos NetChaos antes
da próxima execução e exige três amostras, a cada 5 s, com cada worker Kind
abaixo de 50% de CPU e 1,5 GiB de memória (prazo de 180 s). Esses limites
valem para o cluster usado e precisam de nova calibração em outro ambiente.
A primeira versão dos três regimes foi concluída com seis linhas em
`controls.csv`, 72 em `attack-runs.csv` e 36 em `cells.csv` por regime. Após a
seleção posterior de quatro runs com rebuffer, as matrizes ativas aguardam
reexecução desses runs para voltar a esse total. O procedimento de execução,
retomada e recuperação de cache está em [risk-matrix.md](risk-matrix.md).

## Medidas e cálculo

Em cada **controle**, `mu_j,c` é a recompensa média aceita da CDN `j`.
Registrar `g_13,c = mu_1,c − mu_3,c` e
`g_12,c = mu_1,c − mu_2,c`, além da fração de respostas CSS que põem a
CDN-1 em primeira prioridade entre 40–120 s. Os dois gaps medem a separação
da CDN-1 para cada alternativa; a fração de prioridade mede a distinção
efetivamente praticada pelo UCB1. Relatar média e desvio padrão dos **seis
controles** por regime. Verificar em cada controle a ordem esperada
`CDN-1 > CDN-3 > CDN-2`; os atrasos configurados não garantem essa ordem
nos dados observados.

Para uma célula com `M` clientes modificados, considerar apenas os slots
honestos `M+1..10`, tanto nos ataques quanto em cada controle:

- `P`: média, entre esses clientes, das frações individuais de respostas CSS
  com CDN-2 ou CDN-3 em primeira prioridade.
- `B`: média, entre esses clientes, de
  `rebuffer_seconds / (played_seconds + rebuffer_seconds)`.

```text
D_steer,i  = P_attack,i − mean(P_control,c; c=1..6)
D_viewer,i = B_attack,i − mean(B_control,c; c=1..6)
Efeito da célula = mean(efeito_ataque_1, efeito_ataque_2)
```

`D_steer` é o desfecho primário: mudança na prioridade do CSS para clientes
honestos, não no caminho efetivamente usado após fallback. `D_viewer` é o
desfecho de reprodução; pode ser zero mesmo com mudança de prioridade quando
há buffer suficiente. A execução é a unidade experimental: clientes e
segmentos de uma execução não são réplicas independentes. Os seis controles
formam uma referência **compartilhada** entre células e passagens. A segunda
passagem ocorre depois deles; possível deriva temporal deve ser considerada
na interpretação. Os dois efeitos individuais de cada célula permanecem em
`attack-runs.csv` e `metrics.json`.

Na primeira versão das três matrizes, `D_viewer` era diferente de zero apenas
em quatro células: `low` (`M=6`, `ttlb=340`), `medium` (`M=3`, `ttlb=90` e
`530`) e `high` (`M=2`, `ttlb=1200`). Em cada uma, um dos dois ataques teve
rebuffer medido em clientes honestos; o outro ataque e os seis controles de
referência tiveram `B=0`. O runner mede `rebuffer_seconds` por eventos
`waiting`/`stalled` e `playing` do elemento de vídeo e calcula a diferença
entre snapshots no início e no fim da janela. Esses artefatos comprovam o
evento observado e a aritmética do mapa, mas não isolam a causa dos episódios
nem demonstram um efeito causal do envenenamento sobre o rebuffer.
Esses quatro runs e os plots anteriores foram movidos para
`results/excluded-rebuffer-20261101/`, com caminhos originais e motivo em
`selection.json`. A escolha ocorreu **após inspeção do desfecho**: as
reexecuções substitutas não são confirmações independentes, e a ausência de
rebuffer nelas não apaga os episódios observados. Conservar e relatar os
resultados excluídos ao apresentar a matriz final.

## Custo de tráfego

O modelo aplica tarifas públicas de saída ao usuário na América do Sul,
primeira faixa mensal, consultadas em 2026-10-29. A associação tarifa–CDN é
uma hipótese de cenário, sem identificar operadores reais nem explicar os
atrasos do NetChaos:

| Braço | Referência de tarifa | `p_j` (USD/GB decimal) |
| --- | --- | ---: |
| CDN-1 | [bunny.net Standard](https://bunny.net/pricing/) | 0,045 |
| CDN-3 | [KeyCDN, América Latina](https://www.keycdn.com/pricing) | 0,10 |
| CDN-2 | [Azure Front Door, América do Sul](https://azure.microsoft.com/en-us/pricing/details/frontdoor/) | 0,11 |

Com `B_j` bytes entregues pela CDN `j` entre 40 e 120 s:

```text
C_observado (USD) = Σ_j (B_j / 10^9) × p_j
c (USD/GB)       = Σ_j [B_j / Σ_k B_k] × p_j
Delta_c,i        = c_attack,i − mean(c_control,c; c=1..6)
Delta_c,célula   = mean(Delta_c,1, Delta_c,2)
```

`Delta_c` é a comparação econômica principal, pois o volume baixado pode
variar entre execuções. Para um volume hipotético `V` GB, a diferença
projetada é `V × Delta_c`; declarar `V` como cenário. Tarifas podem mudar.
Logs UDP das CDNs são best effort, de modo que a completude dos bytes limita
a estimativa. Custos fixos e perda de receita por pior QoE ficam fora do
modelo.

## Entrega e limites de interpretação

Cada regime possui `D_steer.png`, `D_viewer.png`, `Delta_c.png`,
`controls.csv`, `controls-summary.csv`, `attack-runs.csv`, `cells.csv`,
`calibration.json` e `metrics.json` em
`results/research-matrices/<regime>/plots/ucb1/`. Os diretórios datados
preservam dados brutos, configuração, verificações de cache e
`idle-check.json`; sementes e ordens estão na raiz de cada regime. Os mapas
mostram a média dos dois ataques; `cells.csv` também inclui o `ttlb`
declarado, a recompensa média aceita e o custo observado das execuções.
Preservar o estado exato do código ao arquivar os resultados.

Pilotos a 1080p apresentaram instabilidade de recursos; controles a 576p
foram estáveis localmente e motivaram a resolução usada nas matrizes. Pilotos
com recompensa-alvo e `lambda=5`/`15` não integram a análise final. Na matriz
`low`, duas células (`M=4` e `M=5`, ambas com `ttlb=1200`) foram escolhidas
para repetição **após inspeção do mapa** e seus quatro diretórios originais
foram removidos. Essa seleção pelo desfecho torna tais células exploratórias;
não atribuir a troca a falha técnica ou tratá-las como confirmação
independente. Outros runs falhos permanecem disponíveis para auditoria e são
excluídos dos mapas pelos critérios de validade.

Não inferir uma fronteira universal de comprometimento ou precisão estatística
que duas execuções por célula não sustentam. Não tratar células que compartilham
os mesmos controles como amostras independentes.
