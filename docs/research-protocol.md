# Protocolo do TCC: envenenamento de telemetria no Content Steering

## Problema e perguntas

O Content Steering sinaliza prioridades entre caminhos; não determina como o CSS as
calcula. Neste simulador, relatos CMCD aceitos de clientes do mesmo `run_id` alimentam
um modelo compartilhado. Um cliente que baixa mídia real pode falsear seu relato e
influenciar decisões futuras para clientes honestos. O limite de confiança está na
passagem do relato do cliente para esse estado compartilhado, não no protocolo de
sinalização em si. Consulte [design.md](design.md).

**Pergunta central:** em um CSS adaptativo alimentado por telemetria compartilhada, em
que condições relatos falsos de parte dos clientes alteram decisões para clientes
honestos, custo de tráfego e experiência de reprodução? Em etapa posterior, quanto uma
camada de proteção reduz esses efeitos sob as mesmas condições?

Separar três perguntas no texto e na análise:

1. **Aprendizado e decisão:** o CSS aceita relatos falsos e possui seu aprendizado alterado com isso?
2. **Entrega e custo:** o player passa a usar outras CDNs e muda o custo unitário? Prioridade, caminho efetivo e bytes entregues são medidas.
3. **Experiência:** a entrega alterada reduz QoE dos clientes honestos? Buffer, ABR, exploração e retorno à rota rápida podem amortecer uma mudança de prioridade.

O problema não é exclusivo de TTLB, UCB1 ou da fórmula usada aqui. A magnitude do efeito
depende da capacidade de envenenamento de telemetria, da fração de feedback contaminado, da rede
e do player. UCB1, epsilon-greedy e LinUCB são as políticas de bandit disponíveis; LinUCB é um
bandit contextual, não uma representação de todo aprendizado de máquina. Não extrapolar um
resultado do simulador a todo CSS.

## Desenho prospectivo

**1. Dose na rede rápida.** Fixar dez players, `M=3` clientes modificados,
CDN-1 como alvo, UCB1, `lambda=10`, teto ABR de 720p/3.000 kb/s, 120 s de
reprodução e ataque após 40 s. Os players iniciam em sequência; registrar a
posição de reprodução e o buffer no início da janela para interpretar diferenças
entre slots. Usar NetChaos 4/12/9 ms nas CDNs 1/2/3 e TTLB
falso declarado de 90, 200, 340, 530, 800 ou 1.200 ms. Antes da série final,
verificar em 720p a ordem honesta das recompensas, TTLB percebido, cache e
recursos do cluster: atraso NetChaos não é RTT nem TTLB. Fazer seis controles
compartilhados e dois ataques independentes por dose, intercalados, cada qual
com `run_id` novo. Gráficos de prioridade da CDN-1, bitrate exibido e índice
operacional de QoE dos honestos cobrem **0–120 s**; gráficos de avanço mostram
cada cliente honesto de cada run, com tempo sem progresso, rebuffer e falha
terminal. Calcular `D_steer` e `Delta_egress_cost` apenas em **40–120 s**.
Mostrar valores individuais dos runs junto às médias. Dois ataques por
condição atendem ao escopo descritivo deste TCC, sem estimar um limiar preciso.

**2. Proporção maliciosa na mesma rede.** Fixar TTLB falso em 530/800 ms e
variar `M=1/3/5`, com seis controles compartilhados e dois ataques por célula.
Reutilizar os controles e ataques `M=3` da etapa 1. Os clientes modificados
substituem clientes honestos, baixam vídeo real e alteram somente relatos
elegíveis. Comparar slots honestos `M+1..10` nos ataques e respectivos
controles. Registrar a fração de feedback **aceito e falsificado** na CDN-alvo:
`M/10` não é necessariamente essa fração. O run é a réplica, nunca o cliente
ou o segmento. Mostrar prioridade temporal em 0–120 s e
`D_steer`/`Delta_egress_cost` em 40–120 s.

**3. Condições de degradação de QoE.** Avaliar em pilotos separados NetChaos
12/900/900 ms com TTLB falso de 9.000 ms e 240/500/500 ms com TTLB falso de
5.000 ms. Usar primeiro pilotos de 60 s com ataque após 20 s; os runs finais
mantêm 120 s e ataque após 40 s. Para evitar que a preparação sequencial
consuma parte grande do vídeo de 182,8 s antes do início do run, preparar
os players e iniciar a reprodução com intervalo de 1 s entre eles. Validar
essa opção quanto a erros do browser antes da amostra final. Manter os demais
parâmetros da etapa 1. Calibrar controle estável,
desvio de prioridade e de rota efetiva sob ataque, e queda de QoE dos honestos.
Se um candidato não produzir o efeito, testar outros valores de latência em
pilotos identificados e registrar a seleção; congelar os cenários escolhidos
antes dos runs finais. Para cada cenário selecionado, fazer seis controles e
dois ataques independentes. Exibir bitrate, índice de QoE e avanço por cliente
honesto em 0–120 s, incluindo tempo sem progresso, rebuffer e falhas
terminais. A escolha adaptativa ilustra **quando e como** a queda pode ocorrer;
não estima sua frequência em redes não selecionadas.

**Trabalhos complementares.** Comparações com epsilon-greedy, LinUCB e
`random`, falsificação de outros campos CMCD e outras funções de recompensa
ficam fora da amostra principal. Uma camada de proteção será definida e
avaliada posteriormente, com controles próprios para cada modo.

## Medidas e raciocínio causal

Em cada controle, registrar `mu_j` (recompensa média aceita por CDN), `g_12 = mu_1 −
mu_2`, `g_13 = mu_1 − mu_3`, fração de prioridade da CDN-1, TTLB observado, cache e
recursos. Esses gaps descrevem a separação **honesta** das recompensas. Registrar também
a recompensa falsa aceita, a fração contaminada no aprendizado da CDN-alvo e a evolução
temporal das prioridades. No UCB1, média e bônus de exploração formam juntos o escore de
decisão.

```text
P = média, entre clientes honestos, da fração individual de respostas CSS
    com CDN-2 ou CDN-3 em primeira prioridade na janela
D_steer = P_ataque − média(P_controles)

c (USD/GB) = Σ_j [B_j / Σ_k B_k] × p_j
Delta_egress_cost = c_ataque − média(c_controles)
```

`B_j` são bytes servidos pela CDN `j` na janela. A fração de **segmentos efetivamente
servidos** por cada CDN complementa `D_steer`: a prioridade pode mudar sem mudança
correspondente de rota. O custo é uma projeção unitária sob tarifas escolhidas, não uma
fatura real; o volume baixado também pode diferir entre runs.

Para clientes honestos, o índice operacional de QoE é a fração do período observado com progresso
multiplicada pelo bitrate exibido médio, ponderado pelo tempo com progresso, dividida
pelo teto ABR do run. Comparar apenas o mesmo vídeo e teto; não chamá-lo de MOS ou
escala perceptual validada. Exibir tempo sem progresso, rebuffer, qualidade exibida,
pausa e falha terminal para explicar o índice. Os gráficos temporais cobrem
0–120 s desde o limite comum do run e usam índice acumulado até cada instante.
Os players iniciam em sequência antes desse limite, de modo que partida e buffer
prévio podem diferir entre slots; registrar essa condição na interpretação. A janela
40–120 s serve somente aos cálculos finais de `D_steer` e custo. O gráfico
principal de dose deve mostrar, em painéis alinhados, `D_steer`,
`Delta_egress_cost` e QoE; componentes ficam em gráficos auxiliares. Não atribuir
causalidade a um evento `waiting/stalled` isolado.
Se o índice for indefinido por cobertura insuficiente de qualidade, preservar o
run e exibir os componentes e a falha; não selecionar outra execução com base
nesse desfecho. Erros de decodificação do player exigem investigação separada
antes de atribuir perda de QoE à rota CDN.

## Rede rápida, rede degradada e limites das inferências

O cenário 4/12/9 ms produziu TTLBs medianos aproximados de 31/80/61 ms nas matrizes
anteriores, com segmentos de 4 s em cache e teto de 576p. É um cenário de entrega rápida
compatível em ordem de grandeza com a faixa de dezenas a cerca de 150 ms usada como
referência de latência de CDN. A [bunny.net](https://bunny.net/network/) informa
23 ms de latência para sua rede LATAM; uma [pesquisa da Akamai](https://www.akamai.com/site/en/documents/research-paper/faster-web-through-client-assisted-cdn-servers-selection.pdf)
observou latência média cliente–servidor Akamai de até 100–150 ms para 80% dos
clientes em alguns métodos de resolução. Esses números usam métodos e populações
diferentes e **não estimam a média de TTLB de segmentos de vídeo na América Latina**.
Os alvos, horários e RTTs ICMP usados para escolher a ordem
de latências constam de [risk-matrix.md](risk-matrix.md#proveniência-dos-atrasos). RTT
ICMP, TTFB e TTLB de segmento não são intercambiáveis; tamanho do objeto, throughput,
cache, conexão e localidade alteram o TTLB. O teto de 720p do estudo novo exige
recalibração.

Nas matrizes 4/12/9 ms, ataques frequentemente aumentaram `D_steer` e custo unitário; a
versão histórica não demonstrou degradação consistente de QoE honesta. No piloto de dez
clientes 9/270/900 ms, `lambda=10`, 720p, `M=3` e TTLB falso de 9.000 ms, um controle e
um ataque válidos deram QoE média dos sete honestos de 0,954 e 0,960, `D_steer=-3,63`
pontos percentuais e `Delta_egress_cost=-0,00249 USD/GB`. Foram aceitos 59 relatos
falsos entre 371 observações aprendidas da CDN-1; sua média final ficou 0,744 contra
0,300 da melhor alternativa. Artefatos: `results/qoe-pilots/9-270-900/`. É um
**piloto**, não uma réplica final nem prova de que toda rede degradada resiste.

Mesmo TTLB declarado muito alto tem efeito limitado quando a recompensa falsa já se
aproxima de zero e a maior parte do feedback da CDN-alvo continua honesta. Para
ilustrar, uma mistura estática com média honesta `mu_1`, recompensa falsa `r_f` e fração
aceita falsificada `f` teria média `(1−f)mu_1 + f r_f`. Ela igualaria a melhor
alternativa em `f ≈ (mu_1−mu_alt)/(mu_1−r_f)`. As médias do controle 9/270/900 dão
aproximadamente 67%; o ataque teve `f=59/371≈16%`. Essa conta **não prevê** o UCB1
completo: ignora bônus, ordem temporal e mudanças nas taxas de requisição. Mostra por
que prolongar o mesmo ataque com `M=3` não garante inversão da preferência.

Quando as três CDNs são rápidas, a função escolhida pode produzir gaps de recompensa
pequenos ou grandes. A capacidade do ataque depende tanto do gap honesto quanto da
redução da recompensa pelo relato falso, da contaminação aceita e da exploração. A queda
de QoE requer ainda que a rota alternativa prejudique a entrega e que buffer/ABR não
absorvam o desvio. Tratar “custo antes de QoE” como hipótese testável, não conclusão
antecipada. A
[Akamai](https://www.akamai.com/blog/cloud/get-your-player-analytics-with-cmcd) explica
por que tempo de entrega deve ser lido junto da duração do segmento e do estado do
player; o [dash.js](https://dashif.org/dash.js/pages/usage/abr/) documenta adaptação por
throughput e buffer.

## Tarifas e cálculo de custo

Tarifas públicas de egress ao cliente na primeira faixa e região indicada, conferidas em
2026-11-07. A associação tarifa–braço Nginx é hipótese **independente** da latência
simulada; os braços não representam literalmente esses operadores.

| Braço | Referência                                                                                                | `p_j` (USD/GB decimal) |
| ----- | --------------------------------------------------------------------------------------------------------- | ---------------------: |
| CDN-1 | [bunny.net Standard, América do Sul](https://bunny.net/pricing/)                                          |                  0,045 |
| CDN-2 | [Azure Front Door Standard/Premium, Zona 3](https://azure.microsoft.com/en-us/pricing/details/frontdoor/) |                   0,11 |
| CDN-3 | [KeyCDN, América Latina](https://www.keycdn.com/pricing)                                                  |                   0,10 |

O modelo inclui só egress por GB; não inclui taxa base ou por requisição do Azure Front
Door, descontos, origem/cache, impostos ou perda de receita por QoE. Com `V` GB
hipotéticos, a diferença projetada é `V × Delta_egress_cost`. Tarifas podem mudar: citar
SKU, região e data. Logs UDP das CDNs são _best effort_, logo a completude dos bytes
limita a estimativa.

## Análise complementar de lambda e histórico auditável

As matrizes existentes variaram `lambda=1,10,25`, `M=1..6` e TTLB declarado de 90, 200,
340, 530, 800 ou 1.200 ms em UCB1, 576p e rede 4/12/9 ms. Cada regime prevê seis
controles e dois ataques por célula. `low/medium/high` são nomes históricos para
**valores de lambda**, não níveis universais de sensibilidade. Preservar
`results/research-matrices/`; [risk-matrix.md](risk-matrix.md) documenta execução e
retomada. `plot_control_sensitivity.py` resume seis controles por regime. Variação de
lambda é complementar: muda separação honesta, recompensa falsa e escala relativa ao
bônus do UCB1.

Para `R_lambda=d/(d+lambda×ttlb)`, `|∂R/∂ttlb| = lambda×d/(d+lambda×ttlb)^2`. Para TTLBs
`a<b`, a separação `R_lambda(a)−R_lambda(b)` atinge máximo em `lambda=d/sqrt(a×b)`. Não
chamar lambda isoladamente de sensibilidade monotônica nem atribuir a ela sozinha uma
diferença de ataque.

Quatro runs históricos com rebuffer foram retirados das matrizes ativas **após observar
o desfecho** e arquivados com `selection.json` em `results/excluded-rebuffer-20261101/`.
Na matriz `low`, duas células (`M=4/5`, `ttlb=1200`) também foram repetidas após
inspeção do mapa; seus diretórios originais foram removidos. Substituições assim são
exploratórias, não confirmações independentes. Relatar isso no TCC; matrizes históricas
não provam efeito de QoE. Pilotos curtos a 4/900/900 ms com quatro players sugeriram
queda de qualidade, mas não equivalem ao desenho final de dez players e ataque após 40
s.

## Próximas alterações de código

O runner `scripts/multi_client.py` executa controles e ataques e grava QoE em
40–120 s e 0–120 s. `scripts/run_tcc_series.sh` orquestra as etapas 1–3 e
`scripts/plot_tcc_series.py` analisa seus runs. A proteção e os trabalhos
complementares ainda não estão implementados. Consulte [simulations.md](simulations.md)
para comandos, calibração e retomada.

Não misturar pilotos com amostra final nem tratar células com controles compartilhados
como comparações independentes.
