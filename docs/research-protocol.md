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

**3. Condições de degradação de QoE.** Avaliar separadamente o caso de CDN-1
muito mais rápida que as alternativas e o caso de três CDNs lentas com CDN-1
melhor. Os pontos iniciais foram 12/900/900 ms com TTLB falso de 9.000 ms e
300/500/500 ms com TTLB falso de 5.000 ms. Usar primeiro pilotos de 60 s com
ataque após 20 s; os runs finais mantêm 120 s e ataque após 40 s. Nesta etapa,
preparar todos os players antes de disparar `play()` em sequência de 1 s
(`--bounded-start`), registrando o intervalo real entre os disparos. As etapas
1–2 mantêm seu início sequencial atual. O vídeo tem 182,8 s: verificar se o cliente
mais adiantado não alcançará o fim natural durante os 120 s finais. Calibrar
controle estável,
desvio de prioridade e de rota efetiva sob ataque, e queda de QoE dos honestos.
Se um candidato não produzir o efeito, testar outros valores de latência em
pilotos identificados e registrar a seleção; congelar os cenários escolhidos
antes dos runs finais. Para cada cenário selecionado, fazer seis controles e
quatro ataques independentes. Exibir bitrate, índice de QoE e avanço por cliente
honesto em 0–120 s, incluindo tempo sem progresso, rebuffer e falhas
terminais. A escolha adaptativa ilustra **quando e como** a queda pode ocorrer;
não estima sua frequência em redes não selecionadas.

Os pilotos de 9/11/2026 ainda não fixaram um cenário para a amostra final.
Em 12/900/900, o desvio de rota foi pequeno e o buffer amortizou o ataque.
Em 300/500/500, dois pares curtos tiveram diferenças pequenas e variáveis;
o par de 120 s teve QoE pós-ataque praticamente igual à do controle.
300/800/800 já prejudicou o controle; 150/900/900 e o controle de 120 s
em 250/700/700 tiveram falhas terminais antes de qualquer ataque.
300/650/650 mostrou menor QoE no ataque curto, mas essa diferença já existia
antes do ataque e a fração efetiva da CDN-1 aumentou. Esses resultados são
pilotos, não réplicas finais. Diferenças anteriores ao ataque e falhas no
controle não são evidência de queda causada pelo envenenamento. A revisão
posterior selecionou 250/700/700 para a série final.

Na recalibração com o player recuperável, manter os buffers padrão, `M=3`,
UCB1 e `lambda=10`. Após validar uma falha de mídia induzida em piloto
descartável, testar pares de 60 s/20 s nas famílias CDN-1 rápida com alternativas
acima de 900 ms e três CDNs lentas, incluindo 250/700/700 ms e pontos próximos.
Começar com TTLB falso de 20.000 ms: com segmento de 4 s, a recompensa falsa
já é aproximadamente 0,020. Só aumentar a dose se um resultado observado
justificar. Levar a pilotos de 120 s/40 s apenas cenários com controle saudável,
mudança efetiva de rota e queda de QoE posterior ao ataque. Congelar manifesto,
dose e condições antes da amostra final; não alterar o buffer para produzir
queda. Se nenhum cenário passar, relatar esse limite para `M=3` e UCB1.
No piloto descartável de falha induzida com um cliente e 35 s,
`results/qoe-recovery-pilot/20261111T004109Z-b3906a55/`, houve uma tentativa e
uma retomada de 7,84 s, sem falha terminal ou miss de cache. Os pares curtos
foram executados antes do ajuste final que espera o erro fatal do dash.js. Um
segundo piloto descartável de 25 s com esse gatilho está em
`results/qoe-recovery-pilot-v2/20261111T005503Z-ff5eed41/`: erro nativo,
erro fatal do dash.js, uma tentativa, retomada de 7,87 s e nenhum miss de cache.
O par de 60 s/20 s
em 12/900/900 ms com TTLB falso de 20.000 ms está em
`results/qoe-recovery-calibration/12-900-900/`: o controle teve QoE média
pós-20 s de 0,928 e o ataque, 0,910 nos sete slots comparáveis. A rota efetiva
da CDN-1 caiu de 1,000 para 0,895, mas a QoE no ataque já era menor antes dos
20 s; este par não valida uma queda posterior causada pelo ataque.
O par curto em 250/700/700 ms, no mesmo diretório de calibração, teve controle
sem falhas terminais, rota efetiva da CDN-1 de 0,688 (controle) contra 0,446
(ataque), e QoE média pós-20 s de 0,880 contra 0,808. Antes dos 20 s, o run de
ataque tinha QoE maior que o controle. É candidato para piloto de 120 s/40 s,
ainda não um cenário congelado nem uma réplica final.
O par longo de 120 s/40 s confirmou 250/700/700 como cenário selecionado:
controle válido, sem erros de mídia ou falhas terminais, rota efetiva da CDN-1
de 0,742 para 0,532 no ataque e QoE pós-40 s de 0,909 para 0,854. A QoE
pré-ataque era maior no run de ataque (0,638 contra 0,558). Artefatos em
`results/qoe-recovery-calibration/250-700-700/long-{control,attack}/`.
Congelar 250/700/700 ms, TTLB falso de 20.000 ms, dez clientes, `M=3`, UCB1,
`lambda=10`, teto 3.000 kb/s, 120 s/40 s e `--bounded-start` para a série
final: seis controles e quatro ataques independentes, sem reutilizar estes pilotos.
Esses pilotos não tiveram erro de mídia nos dez clientes; a espera de 3 s
introduzida posteriormente para um erro fatal não altera seus desfechos.
As séries finais estão em subdiretórios de `results/qoe-final/`, separados por
perfil NetChaos e TTLB declarado.
Um terceiro piloto descartável de um cliente e 25 s, em
`results/qoe-recovery-grace-pilot/`, validou a espera após erro fatal: 3,002 s
entre `recovery_wait` e `recovery_attempt`, retomada 0,773 s depois, 4,504 s
sem avanço na janela completa, sem falha terminal, erro JavaScript ou miss de
cache.

**Leitura das séries finais da etapa 3.** Cada linha abaixo reúne seis controles
e quatro ataques válidos e independentes, com dez clientes, `M=3`, UCB1,
`lambda=10`, 720p, 120 s/40 s e falsificação da CDN-1. A QoE é a média, entre
runs, da média dos sete clientes honestos em 40–120 s; a rota é a fração de
segmentos de vídeo 2xx desses clientes efetivamente servidos pela CDN-1 na
mesma janela, calculada dos `events.jsonl` com os limites
`observation_start`/`observation_end` de cada run. Pares controle → ataque
pertencem à mesma série; séries com
doses diferentes têm controles próprios.

| NetChaos 1/2/3 (ms) | TTLB falso (ms) | QoE controle → ataque | Rota CDN-1 controle → ataque |
| ------------------- | --------------: | --------------------: | ---------------------------: |
| 250/700/700         |          10.000 |         0,899 → 0,887 |                0,678 → 0,610 |
| 250/700/700         |          12.000 |         0,897 → 0,879 |                0,690 → 0,587 |
| 250/700/700         |          20.000 |         0,922 → 0,836 |                0,687 → 0,540 |
| 100/900/900         |          20.000 |         0,921 → 0,911 |                0,894 → 0,779 |

Os artefatos são `results/qoe-final/250-700-700-{10000,12000,20000}/` e
`results/qoe-final/100-900-900-20000/`; `plots/run-qoe.csv` preserva os
valores individuais. Em 250/700/700, nenhuma CDN sustentou QoE unitária em
todos os controles; as alternativas tinham TTLB percebido maior que a CDN-1.
Com 10.000 e 12.000 ms, a rota CDN-1 caiu cerca de 6,8 e 10,3 pontos
percentuais, respectivamente, mas as diferenças médias de QoE foram apenas
−0,012 e −0,018. Alterar o steering não implicou perda de QoE na mesma
magnitude. Na série de 20.000 ms, a rota CDN-1 caiu cerca de 14,7 pontos
percentuais e a diferença média de QoE foi
−0,086; os quatro ataques ainda variaram de 0,724 a 0,999. A QoE média antes
dos 40 s já era menor nos ataques dessa série (0,605 contra 0,645 nos
controles), exigindo cautela na atribuição de toda a diferença posterior ao
envenenamento. A comparação é compatível com perda de QoE sob ataque forte
neste cenário selecionado, sem estabelecer um limiar exato de dose.
Nas séries de 12.000 ms e 100/900/900, um controle teve falha terminal e os
ataques não tiveram; isso também limita a leitura das médias de QoE.

Em 100/900/900, a CDN-1 permaneceu em cerca de 78% das rotas de vídeo dos
honestos durante o ataque, e a diferença média de QoE foi −0,009. A série
12/900/900 com 20.000 ms, arquivada separadamente, também teve diferença
pequena (0,951 → 0,938). Uma CDN-1 muito superior pode ser difícil de deslocar:
parte do feedback segue honesto, o UCB1 continua explorando, e downloads pela
rota rápida podem recompor o buffer. O momento de ativação também importa
porque os players já acumularam reserva. Esses mecanismos ajudam a interpretar
os resultados; não provam impossibilidade de ataque. Prolongar 10.000 ou
12.000 ms seria outro experimento, não uma conclusão destas séries de 120 s.

**Trabalhos complementares.** Comparações com epsilon-greedy, LinUCB e
`random`, falsificação de outros campos CMCD e outras funções de recompensa
ficam fora da amostra principal. A proteção da etapa 2 é especificada abaixo.
Uma série exploratória adicional declarou 100 ms nas CDNs 2 e 3 com os mesmos
três clientes modificados. Os seis controles e quatro ataques válidos estão em
`results/qoe-final/cdn23-250-700-700-100/`, separados das séries com alvo
CDN-1. A QoE média pós-40 s foi 0,913 nos controles e 0,912 nos ataques;
houve 31–42 relatos falsificados aceitos por ataque. Esta série testa outro
mecanismo e não deve ser combinada com a dose dirigida à CDN-1. Em outros
cenários, zero relatos falsificados aceitos também pode ser um resultado
quando não há respostas elegíveis nos caminhos alvo; registrar isso sem
substituir a réplica por outra com maior exposição.

## Etapa 4: função de recompensa, separação e exposição ao ataque

Antes de avaliar a solução, examinar como a regra de recompensa transforma TTLB
em observações para o UCB1. A regra adotada pelo simulador é um exemplo de
função racional hiperbólica decrescente, `R_lambda(t)=d/(d+lambda×t)` para
`d>0`, `lambda>0` e `t≥0`; não é exigida por CMCD nem pelo Content Steering.
Com `d` fixo, TTLBs menores produzem recompensas maiores, e a inclinação
absoluta `lambda×d/(d+lambda×t)^2` diminui à medida que `t` cresce. Logo, a
mesma alteração absoluta de TTLB pode mudar mais a recompensa na região de
tempos baixos do que na cauda alta dessa curva. O efeito sobre o CSS, porém,
depende das médias acumuladas, da fração de feedback contaminado e do bônus
de exploração, não apenas da inclinação pontual.

`results/research-matrices/{low,medium,high}/plots/ucb1/` permite examinar
esse compromisso com a mesma rede NetChaos 4/12/9 ms, UCB1 e teto histórico
de 576p. `low/medium/high` designam **lambda=1/10/25**, não níveis universais
de sensibilidade. Cada regime contém seis controles e dois ataques por célula
de `M=1..6` e TTLB falso de 90, 200, 340, 530, 800 ou 1.200 ms. Nos controles,
o gap médio `mu_1−mu_2` foi 0,012/0,089/0,149, e a fração de CDN-1 em primeira
prioridade foi 0,353/0,495/0,621, respectivamente. A separação maior ajudou
o CSS a distinguir a melhor CDN nessa rede. Na célula `M=3`, TTLB falso de
800 ms, `D_steer` passou de 6,4 para 24,5 e 25,9 pontos percentuais entre
esses regimes, enquanto `Delta_egress_cost` passou de aproximadamente
0,0031 para 0,0133 e 0,0147 USD/GB. As tabelas `controls-summary.csv`,
`cells.csv` e `attack-runs.csv` mostram médias e runs individuais. O aumento
simultâneo da separação honesta e do desvio observado ilustra o compromisso
nestas condições; não estabelece que aumentar `lambda` sempre facilita um
ataque, nem que outra função tenha o mesmo comportamento.

Para dois TTLBs honestos `a<b`, a separação `R_lambda(a)−R_lambda(b)` é máxima
em `lambda=d/sqrt(a×b)`; portanto, ela **não cresce monotonicamente** com
`lambda`. Além disso, alterar `lambda` muda tanto as recompensas honestas
quanto a falsa e a escala delas em relação ao bônus do UCB1. A escolha de uma
função deve examinar o mapa de recompensas das CDNs e a influência de relatos
plausíveis ou extremos, nas faixas de TTLB e durações reais da implantação.
As matrizes testam somente esta função com três valores de `lambda`, não
comparam famílias diferentes de funções nem demonstram QoE adversa.

O histórico dessas matrizes limita a inferência: quatro runs com rebuffer
foram retirados **após observar o desfecho** e arquivados em
`results/excluded-rebuffer-20261101/`; na matriz `low`, duas células
(`M=4/5`, TTLB=1.200 ms) foram repetidas após inspeção do mapa e seus runs
originais removidos. Tratar esse material como análise complementar e
exploratória, sem usar clientes ou segmentos como réplicas. A execução e a
retomada estão em [risk-matrix.md](risk-matrix.md).

## Etapa 5: proteção do aprendizado nas condições das etapas 1–2

**Hipótese.** Rejeitar feedback com TTLB fora de uma faixa de referência e
isolar sessões repetidamente atípicas deve reduzir o desvio de prioridade e
custo observado na etapa 2. A regra é bilateral, mas a eficácia experimental
será demonstrada apenas para a falsificação **para cima** já estudada. Não
extrapolar para valores falsos plausíveis, outros campos ou ataques distribuídos.
O [CTA-5004-B](https://cta-wave.github.io/Resources/common-media-client-data--cta-5004-b.html)
alerta que players maliciosos podem enviar dados falsos; trabalhos sobre
[bandits com recompensas contaminadas](https://arxiv.org/abs/2002.07214)
motivam limitar a influência das observações, mas suas garantias não se
transferem automaticamente para este UCB1 nem para o limiar proposto.

**Defesa.** O módulo lógico fica no serviço de telemetria, antes da atualização
do modelo compartilhado; o CSS continua apenas ordenando as CDNs. Para relato
correlacionado `e=rr`, `ot=v`, `rc=2xx`, ignorar na aprendizagem valores de TTLB
`<p1` ou `>p99` da CDN: não incrementar nem recompensa nem número de observações.
Auditar o original, limites usados e motivo; deduplicar também relatos rejeitados.
Falhas (`rc=0`, 4xx/5xx) mantêm a recompensa zero. Entre os últimos cinco relatos
de vídeo 2xx elegíveis de uma sessão, três rejeições por percentil colocam seu feedback em
quarentena até o fim da sessão, sem bloquear a reprodução. Isso classifica
comportamento atípico, não identifica fraude; novo `sid` pode contornar o estado.

Obter a referência inicial de seis pilotos honestos independentes, sob as mesmas
condições da etapa 2, preservando todos os TTLBs de vídeo 2xx aprendidos por CDN.
Calcular p1/p99 pelo método de posto `ceil(p×N)` sobre a referência inicial
combinada com relatos aceitos nos últimos **30 s** do mesmo run. Os pilotos não
entram na amostra final. Arquivar amostra, hash e versão. A referência inicial
domina a janela curta deste simulador: nos controles anteriores cada CDN teve
cerca de 98–183 relatos em 120 s. Em produção, estratificar por CDN, classe
de rede, cache e perfil de objeto quando houver amostra suficiente.

Uma janela menor responde mais rápido a mudanças reais, mas produz caudas mais
instáveis e é mais fácil de contaminar; uma maior reduz variação amostral, mas
responde lentamente e conserva valores contaminados por mais tempo. Atualizar
somente com relatos aceitos reduz deslocamentos bruscos, mas limita adaptação a
novas condições reais. A contaminação gradual do limiar permanece possível;
discutir essa brecha sem alegar proteção completa. A fração de relatos honestos
rejeitados em redes heterogêneas fica como limite de validade externa, não como
experimento adicional obrigatório deste TCC.

**Experimento.** A proteção foi testada repetindo apenas a etapa 2: dez
clientes, UCB1, `lambda=10`, 720p/3.000 kb/s, 120 s/40 s, NetChaos 4/12/9 ms,
`M=1/3/5` e TTLB falso
530/800 ms. Há seis controles e dois ataques por cada uma das seis células:
18 runs protegidos válidos em `results/tcc-defense-stage2-4-12-9/`, comparados
aos 26 runs desprotegidos de `results/tcc-final-recovery-4-12-9/` apenas nas
células correspondentes. Os seis pilotos de referência estão em
`results/tcc-defense-calibration/` e não integram a amostra final. Preservar
slots honestos `M+1..10`, janelas, fórmulas e critérios de validade; controles
são compartilhados entre células de cada modo. O plano, a ordem, o manifesto
e o hash da referência permitem auditar a comparação.

Para cada célula, calcular o efeito ataque menos média dos controles **dentro
do mesmo modo** e depois a diferença entre efeitos com e sem proteção para
`D_steer`, `Delta_egress_cost` e QoE. Mostrar valores por run e curvas 0–120 s,
além da rota efetiva, fração de feedback falsificado **aceito** e distribuição
de recompensas. Não tratar os seis controles
compartilhados como 60 controles independentes. O run é a réplica; clientes e
segmentos são observações internas. Como as séries são sequenciais, conferir
deriva de recursos, cache e tempos efetivos antes de atribuir diferenças à
defesa. A QoE pode permanecer estável mesmo com melhoria de steering/custo;
isso é resultado, não falha do experimento.

Em `plots/etapa-2/defense-comparison.csv`, as seis células mostram redução
dos efeitos de steering e de custo calculados como ataque menos controles
dentro de cada modo. As diferenças de QoE entre modos são pequenas nessa rede
rápida. Interpretar esses resultados como evidência da regra implementada
sob a referência calibrada, não como garantia para outras redes, doses ou
funções de recompensa.

**Critério de utilidade.** A defesa é útil neste cenário se reduzir de forma
reprodutível os efeitos de steering/custo nas células em que o ataque os elevou,
sem desvio material de rota ou QoE nos controles honestos. Relatar células sem
ganho e dependência da referência; dois ataques por célula sustentam descrição, não estimativa precisa de
eficácia geral. Não afirmar que protege qualquer implantação de Content
Steering, pois o protocolo não impõe esta regra de aprendizado.

**Alternativas para discussão.** Blacklist de IP pode bloquear usuários
legítimos que compartilham ou mudam de endereço. Logs de CDN podem auxiliar
na investigação de sessões sinalizadas, caso haja correlação por requisição e
entrega confiável; tempo do servidor não equivale ao TTLB do player. Logs não
capturam diretamente buffer, ABR, rebuffer ou reprodução, motivo para manter
CMCD/RUM como fonte complementar. K-means pode ser estudado para padrões
multivariados, mas clusters não provam desonestidade e exigem atributos, número
de grupos e regra de ação. Essas alternativas não integram a implementação.

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

Para clientes honestos, o único índice operacional de QoE é
`qoe_index = fração com progresso × bitrate exibido médio / teto ABR ×
(0,75 + 0,25 × média[min(buffered_ahead/18 s, 1)])`, com as médias
ponderadas pelo tempo com progresso.
Assim, reserva inferior a 18 s reduz o índice antes de um travamento; com
qualidade constante, um segundo sem progresso pesa quatro vezes mais que um
segundo com reserva zerada. O limiar acompanha o `bufferTimeDefault=18 s` do
dash.js; na qualidade máxima o alvo do player é 30 s, mas o limiar da análise
permanece fixo em 18 s. O peso 0,25 não é um parâmetro perceptual validado.
Comparar apenas o mesmo vídeo e teto; não chamar o índice de MOS ou escala
perceptual validada. Exibir tempo sem progresso, rebuffer, qualidade exibida,
pausa e falha terminal para explicá-lo. O rebuffer integra a perda de tempo
com progresso; sua duração é apresentada separadamente. Os gráficos temporais
cobrem 0–120 s desde o limite comum do run e usam índice acumulado.
Nos 26 runs de `results/tcc-final-recovery-4-12-9/`, a reserva é reconstruída
dos snapshots e dos relatos CMCD de áudio e vídeo. Entre leituras, o cálculo
usa o menor valor compatível com consumo linear do buffer e sem esvaziamento
súbito, condição adotada para essa série. A reconstrução é conferida contra
o snapshot aos 40 s; `plots/qoe-clients.csv` registra a origem de cada valor.
Os `summary.json` brutos são preservados. O `qoe_index` oficial recalculado
aparece nos CSVs e gráficos de análise, sem repetir os runs 1–2.
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

## Artefatos de execução e análise

O runner `scripts/multi_client.py` executa controles e ataques e grava QoE em
40–120 s e 0–120 s. `scripts/run_tcc_dose_proportion.sh` orquestra as etapas 1–2,
`scripts/run_qoe_dose_response.sh` a etapa 3 e `scripts/plot_tcc_series.py` e
`scripts/plot_qoe_dose_response.py` analisam seus runs. A etapa 4 usa
`results/research-matrices/`, e a etapa 5 usa
`scripts/calibrate_tcc_defense.sh` e `scripts/run_tcc_stage2_defended.sh`.
Consulte [simulations.md](simulations.md)
para comandos, calibração e retomada.

Não misturar pilotos com amostra final nem tratar células com controles compartilhados
como comparações independentes.
