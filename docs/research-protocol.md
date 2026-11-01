# Protocolo experimental: envenenamento de CMCD no Content Steering

## Objetivo e escopo

Avaliar, com UCB1 e dez players DASH por execução, como clientes que falsificam
`ttlb` de respostas de vídeo da CDN-1 alteram a prioridade devolvida pelo CSS,
o rebuffer dos clientes honestos e o preço unitário de tráfego entregue. O
experimento compara três valores calibrados de `lambda` na recompensa
`R_lambda = d / (d + lambda * ttlb)`. A fórmula é uma escolha do simulador, não
uma fórmula prescrita por CMCD ou Content Steering.

Os eixos de cada matriz 6 × 6 são a quantidade de players modificados
`M = 1..6` e o `ttlb` declarado na CDN-1, em milissegundos:
`90, 200, 340, 530, 800, 1200`. A faixa aproxima os TTLB que a antiga grade
de `r=0.9..0.4` produzia com `lambda=5` e `d=4000 ms`, arredondados para
valores legíveis. Ela é idêntica nas três sensibilidades e acima da mediana
honesta observada da CDN-1 (~31 ms). O player declara esse valor fixo em cada
resposta de vídeo elegível; a recompensa resultante é calculada pela função da
execução e resumida apenas para relatos aceitos pelo CSS. O eixo representa
o dado que o cliente controla, sem pressupor que ele conhece a função interna.

## Etapa 1: piloto curto e critérios de avanço

1. Confirmar integridade do cluster, mídia, caches e aplicação do NetChaos.
2. Executar controles limpos espaçados, com dez players, 120 segundos,
   `--measurement-start 40`, UCB1 e a mesma falha de rede da matriz.
3. Em cada controle, medir médias de recompensa e `ttlb` por CDN, primeira
   prioridade por cliente, rebuffer e consumo de CPU/memória dos nós.
4. Escolher três valores de `lambda` por sensibilidade observada no intervalo
   real de `ttlb`, e verificar a ordem de recompensa esperada
   `CDN-1 > CDN-3 > CDN-2`. A derivada local é
   `abs(dR/dttlb) = lambda*d / (d + lambda*ttlb)^2`; seu valor não cresce
   indefinidamente com `lambda`.
5. Registrar a recompensa resultante de cada TTLB declarado e verificar que a
   faixa permanece acima do TTLB honesto típico da CDN-1.

O controle disponível em `results/risk-matrix/v1` demonstrou a ordem esperada
uma vez; ele não estabelece estabilidade. O piloto precisa produzir novos
controles antes de avançar.

### Piloto inicial de 2026-10-29: instabilidade a 1080p

Foram executados dois controles limpos com `lambda=5`, dez players, NetChaos e
120 s. Ambos terminaram com `success=true` e preservaram a ordem média de
recompensa CDN-1 > CDN-3 > CDN-2, porém as condições observadas não foram
estáveis:

| Medida | Controle 1 | Controle 2 |
| --- | ---: | ---: |
| Mediana `ttlb` CDN-1/3/2 (ms) | 47 / 83 / 106 | 122 / 151 / 186 |
| Recompensa média CDN-1/3/2 | 0.9451 / 0.9125 / 0.8900 | 0.8708 / 0.8397 / 0.8262 |
| Rebuffer médio dos dez viewers | 0.0000 | 0.1454 |
| `g_13` / `g_32` | 0.0325 / 0.0226 | 0.0311 / 0.0135 |

Artefatos: `results/research-pilot/20261029T202456Z-f43f0975/` e
`results/research-pilot/20261029T203014Z-86630c86/`. Durante o segundo
controle, uma amostra de `docker stats` registrou CPU de 463.56% e 671.41%
nos dois nós workers e cerca de 3.1 GiB de memória em cada um. Essa amostra
não identifica sozinha a causa da degradação. A remoção dos pods foi solicitada
sem espera pelo runner; uma consulta logo após a conclusão ainda encontrou os
dez pods e uma consulta posterior confirmou sua remoção. Os objetos NetChaos
também foram removidos.

No segundo controle, a recompensa honesta da CDN-1 foi 0.8708. Portanto,
`r=0.9` a promoveria nesse regime. Essa era uma observação do piloto antigo
com recompensa-alvo; a matriz revisada usa TTLB fixo.
Nenhuma conclusão de ataque pode ser extraída desses dois controles.

### Correção e validação da estabilidade

O player estava configurado com `maxBitrate.video=5800`, e os eventos dos dois
controles iniciais mostram que os dez clientes baixaram segmentos de vídeo
de 5.8 Mb/s, representação 1080p. A imagem Docker de 3.68 GB já estava
carregada nos nós; seu tamanho afeta build/load e armazenamento, mas não
explica, por si só, a CPU durante a reprodução. A carga simultânea de dez
decodificadores 1080p é uma causa plausível da instabilidade. Os caches eram
HIT em ambos os controles.

O limite do player foi ajustado para `maxBitrate.video=1500`, a representação
576p disponível no MPD. O runner passou a aguardar a exclusão efetiva dos
pods e, antes de cada execução, exige três amostras consecutivas com os dois
workers abaixo de 50% de CPU e 1.5 GiB de memória, sem pods `dash-client`
nem objetos NetChaos. Amostras a cada 5 s, prazo de 180 s. O arquivo
`idle-check.json` registra o resultado de cada invocação. Esses limiares
foram escolhidos para este cluster Kind de dois workers e devem ser
recalibrados se o ambiente mudar.
Após interrupção por suspensão do notebook, o runner também verifica a
estabilidade antes do aquecimento completo e aguarda CDNs, origem, gateway e
telemetria ficarem prontos antes de abrir os port-forwards.

Dois controles consecutivos a 576p, com dez clientes e o mesmo NetChaos,
foram concluídos com `success=true`, sem rebuffer e com medianas `ttlb`
CDN-1/3/2 de 31/61/79 ms e 32/61/79 ms. As recompensas médias foram
0.9635/0.9327/0.9125 e 0.9631/0.9333/0.9121. Uma célula piloto `M=1,
r=0.5`, com ataque após 40 s, também terminou com sucesso, nove relatórios
falsificados aceitos, `D_steer≈+0.051` contra seu controle e `D_viewer=0`.
Em todas as três execuções, os segmentos de vídeo finais eram de 1.5 Mb/s;
pods e NetChaos foram removidos após cada execução.

Artefatos: `results/stability-576p/`. Essas verificações demonstram
estabilidade local da condição e do caminho de ataque; não substituem os
seis controles escalonados de cada matriz completa. Fixar 576p em
todas as próximas execuções; não misturar os controles 1080p ou 720p aos
resultados 576p.

## Etapa 2: alterações mínimas

Implementado: `--reward-lambda` é registrado por execução no Redis, aplicado
à recompensa e propagado ao player que falsifica `ttlb`. O runner salva
`cdn_bytes_initial`, `cdn_bytes_final` e `cdn_bytes_window` para 40–120 s,
além do `idle-check.json`. O plotter usa a média dos seis controles nos mesmos
slots honestos `M+1..10` e calcula custo unitário e custo observado. A opção
`--require-complete` exige dois ataques válidos em cada uma das 36 células e
seis controles.

As sensibilidades escolhidas para as matrizes finais são **baixa `lambda=1`,
média `lambda=10` e alta `lambda=25`**. São três coeficientes da mesma família
de recompensa, não três funções usadas pela indústria. A revisão após a matriz
`low` busca separar mais os gaps entre CDNs: com `d=4000 ms` e TTLBs
representativos de 31/61/80 ms, `g_13` projetado é aproximadamente
0.007/0.060/0.114. As matrizes parciais de `medium=5` foram descartadas e
não entram na análise final. A escolha abrange uma escala de 25 vezes em
`lambda` e será conferida no TTLB observado dos controles.
Os valores declarados de `ttlb` e o protocolo de ataque permanecem constantes
entre as três matrizes. A antiga grade de recompensa-alvo foi abandonada antes
das matrizes completas por confundir a sensibilidade com magnitudes distintas
de telemetria falsificada.

### Piloto histórico de `lambda=1,5,15` (576p)

Um controle de 120 s por regime, sempre com dez clientes, NetChaos e a janela
40–120 s, produziu:

| `lambda` | TTLB mediano CDN-1/3/2 (ms) | `g_13` | `g_12` | CDN-1 em primeiro | Rebuffer médio |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 31/61/80 | 0.0067 | 0.0117 | 34.1% | 0 |
| 5 | 31/61/79 | 0.0307 | 0.0505 | 40.9% | 0 |
| 15 | 31/61/79 | 0.0805 | 0.1152 | 56.0% | 0 |

Os gaps e a prioridade caminham na direção esperada com `lambda`, sob TTLB
quase idênticos. A fração de primeiras prioridades não chega a 100% porque
o UCB1 mantém o bônus de exploração. É uma verificação de calibração histórica, não uma
estimativa de incerteza ou prova de causalidade: há só um controle por regime.
Dados: `results/lambda-pilot/{low,medium,high}/`, incluindo `controls.csv`.
Em `d=4000 ms` e `ttlb=31 ms`, a sensibilidade local
`|dR/dttlb|` é 0.000246, 0.001158 e 0.003010 por ms para esses três valores.
Uma célula `lambda=5, M=1, r=0.5` confirmou o fluxo completo: oito relatos
falsificados aceitos, `D_steer=+0.0810`, `D_viewer=0` e
`Delta_c=+0.00437 USD/GB` contra o único controle médio disponível.
Esse piloto usou o antigo ataque por recompensa-alvo; ele não entra nas novas
matrizes de TTLB fixo. O contraste é apenas diagnóstico; a estimativa de cada célula da matriz
usará os seis controles da respectiva sensibilidade. Após esse piloto, o runner
passou a pausar os players no encerramento antes de esperar 2 s pelos logs
UDP já emitidos; o custo piloto pode incluir até esse curto intervalo extra.

### Verificação do eixo TTLB fixo (2026-10-30)

Após substituir a recompensa-alvo pelo TTLB declarado, uma execução curta
com `lambda=15`, `M=1` e `--attack-ttlb 800` aceitou cinco relatos
falsificados. Todos declararam 800 ms; a recompensa média aceita foi 0.25,
consistente com `R=4000/(4000+15*800)`. A grade final usa 90, 200, 340,
530, 800 e 1200 ms em todos os regimes. Os mapas exibem somente a medida
de efeito por célula; `cells.csv` registra o TTLB declarado e a recompensa
média efetivamente aceita.
Um controle de 60 s pareado ao ataque de 60 s validou `cells.csv` e os três
mapas com o novo eixo: `D_steer=+0.0873`, `D_viewer=0` e
`Delta_c=+0.00429 USD/GB`. São apenas testes de integração; a matriz final
usa 120 s e seis controles por sensibilidade. Artefatos: `results/ttlb-pilot/`.

## Etapa 3: desenho das matrizes

Para cada `lambda`, sortear duas ordens independentes das 36 células e salvar
as sementes e ordens. Na primeira passagem, executar um controle limpo **após**
cada bloco de seis ataques, inclusive no fim. A segunda passagem repete cada
célula uma vez, sem novos controles. Portanto, cada sensibilidade tem **72
ataques e seis controles**, sempre com dez players. Um `run_id` novo isola o modelo de cada
execução; aquecimento e estado dos caches devem ser documentados e mantidos
comparáveis. Avançar apenas se os controles e a checagem de recursos forem
aceitáveis. Há uma matriz por sensibilidade, com duas execuções independentes
por célula; os seis controles são uma referência compartilhada, inclusive
para a segunda passagem. Como ela ocorre depois dos controles, registrar a
possibilidade de deriva temporal e manter a barreira de recursos antes de
cada execução.

Na execução `low`, a origem impunha `Cache-Control: max-age=3600`, que tinha
prioridade sobre `proxy_cache_valid 24h` da CDN. Uma célula `M=3`, TTLB
declarado de 530 ms, registrou 46 respostas `STALE` e foi excluída. A CDN
passou a ignorar esse cabeçalho para os objetos estáticos; a mesma célula foi
repetida após reconstruir as CDNs e terminou com zero respostas não `HIT`.
As duas tentativas permanecem nos dados brutos para auditoria.

Após inspeção do mapa `low`, foram selecionadas para repetição as células
`M=4, ttlb=1200` (`D_steer=+0.1699`) e `M=5, ttlb=1200`
(`D_steer=+0.0972`), cada uma inicialmente com dois ataques válidos.
Identificadores originais: `20261030T181203Z-9b1f2eb1`,
`20261030T204030Z-bb1ad07e` (M=4), `20261030T180220Z-a9470bad` e
`20261030T211550Z-d4a20393` (M=5). Os quatro diretórios originais foram
removidos a pedido do pesquisador. A seleção ocorreu após observar o
desfecho; interpretar as células refeitas como análise exploratória, sem
atribuir a troca a falha técnica das execuções originais.

Para cada controle `c`, calcular `mu_1,c`, `mu_3,c`, `mu_2,c` das recompensas
aceitas e **`g_13,c = mu_1,c - mu_3,c` e `g_12,c = mu_1,c - mu_2,c`**.
No ordenamento esperado, `g_13` é a separação da melhor para a segunda melhor,
e `g_12` é a separação da melhor para a pior. Como a pergunta é se o CSS
reconhece a CDN-1 como melhor, `g_32` não deve limitar a métrica principal;
ele avalia a ordenação das alternativas. Um `g_min` de todos os pares poderia
ser governado pelo par 3–2 e ocultar boa distinção entre CDN-1 e ambas.
Reportar ambos os gaps e a fração observada de primeiras prioridades à CDN-1
entre 40–120 s. Esta última é a medida **operacional** de distinção do UCB1;
os gaps explicam o sinal disponível no aprendizado. Resumir média e variação
entre os seis controles, sem tratar os segmentos da mesma execução como
réplicas independentes. A literatura de identificação do melhor braço usa os
gaps entre o melhor braço e **cada braço subótimo**, com dificuldade relacionada
a `1/gap²` sob suas hipóteses estocásticas
([Audibert e Bubeck, COLT 2010](https://www.microsoft.com/en-us/research/publication/best-arm-identification-multi-armed-bandits/)).
Esses limites teóricos não são estimativas de tamanho amostral para este
simulador, cujo tráfego e UCB1 são adaptativos.

Para uma célula com `M` atacantes, `P` é a média, nos slots honestos
`M+1..10`, das frações individuais de respostas CSS que põem CDN-2 ou CDN-3
em primeiro lugar. `B` é a média, nos mesmos slots, de
`rebuffer_seconds / (played_seconds + rebuffer_seconds)` entre 40 e 120 s.

```text
D_steer,i  = P_attack,i - mean(P_control,c for c in 1..6)
D_viewer,i = B_attack,i - mean(B_control,c for c in 1..6)
D_celula   = mean(D_1, D_2)
```

Calcular `P_control,c` e `B_control,c` novamente para os slots honestos
correspondentes a cada `M`. Guardar o número de consultas CSS por cliente.
A execução é a unidade experimental; clientes e segmentos da mesma execução
compartilham ambiente e modelo. Os seis controles formam uma referência para
cada sensibilidade, não seis réplicas independentes de cada ataque.
Reutilizar a mesma média de controle cria dependência entre células da matriz;
não tratar células como amostras independentes ao estimar incerteza. Guardar
ambos os efeitos individuais por célula além da média usada nos mapas.

## Custo de tráfego

Usar um cenário de tarifas públicas de saída ao usuário na América do Sul,
primeira faixa mensal, consultadas em 2026-10-29. A associação entre tarifa e
CDN simulada é uma hipótese econômica, não uma identificação dos operadores
ou uma explicação das latências do NetChaos:

| Braço | Referência | Preço em USD/GB decimal |
| --- | --- | ---: |
| CDN-1 | [bunny.net Standard](https://bunny.net/pricing/) | 0.045 |
| CDN-3 | [KeyCDN, América Latina](https://www.keycdn.com/pricing) | 0.10 |
| CDN-2 | [Azure Front Door Standard/Premium, América do Sul](https://azure.microsoft.com/en-us/pricing/details/frontdoor/) | 0.11 |

Os preços são públicos e sujeitos a mudança; taxas fixas, requisições e
outros itens de fatura ficam fora deste modelo de custo marginal de egress.
Para bytes `B_j` entregues no intervalo de medição:

```text
C_observado_USD = sum((B_j / 1e9) * p_j)
s_j = B_j / sum(B_k)
c_USD_por_GB = sum(s_j * p_j)
Delta_c,i = c_attack,i - mean(c_control,c for c in 1..6)
Delta_c,celula = mean(Delta_c,1, Delta_c,2)
```

`Delta_c` é a diferença de preço médio por GB entregue. Para um volume
hipotético `V` GB, a diferença projetada é `V * Delta_c`; `V` precisa ser
declarado como cenário. Os bytes atuais vêm de logs de CDN enviados por UDP,
que são best effort. Validar a completude antes de usar custos. O simulador
não mede perda de receita por QoE.

## Etapa 4: entregável

Produzir três matrizes de `D_steer`, três de `D_viewer` e três de `Delta_c`,
mais tabela dos controles (`g_13`, `g_12`, prioridades da CDN-1 e
dispersão), dados brutos por execução, parâmetros, versões, semente, ordem,
leituras de recursos, tarifas e limitações. Concluir apenas o que duas execuções
por célula e a estabilidade dos controles sustentarem. Alterar `lambda`
também modifica a escala dos intervalos de recompensa perante o bônus fixo
de exploração do UCB1; comparar os regimes como políticas operacionais
completas, sem atribuir toda a diferença exclusivamente à derivada de `R`.

Cada chamada executa **uma matriz de uma sensibilidade**. O primeiro parâmetro
seleciona `low` (`lambda=1`), `medium` (`lambda=10`) ou `high` (`lambda=25`);
o segundo, opcional, é o diretório de saída. A execução pode ser retomada
com o mesmo comando: células concluídas são ignoradas, e células falhas são
repetidas. Cada matriz gera seus resultados em `plots/ucb1/`:

```sh
for regime in low medium high; do
  bash scripts/run_research_matrices.sh "$regime" results/research-matrices
done
git rev-parse HEAD > results/research-matrices/code-commit.txt
git status --short > results/research-matrices/worktree-status.txt
tar -czf results/content-steering-tcc-delivery.tar.gz \
  docs/research-protocol.md docs/risk-matrix.md \
  scripts/run_research_matrices.sh results/research-matrices
```

Cada regime gera `controls.csv`, `controls-summary.csv`, `cells.csv`, `calibration.json`,
`metrics.json`, `attack-runs.csv` e três figuras PNG em `plots/ucb1/`; os diretórios datados
guardam os dados brutos e `idle-check.json`. O CSV de células inclui o custo
observado médio em USD para os bytes das duas execuções e `Delta_c` médio em
USD/GB contra a média dos controles. `attack-runs.csv` e `metrics.json` guardam
os dois efeitos individuais. A comparação econômica principal é `Delta_c`, porque o volume
de bytes pode variar entre execuções. Preservar também o código fonte exato
correspondente ao commit registrado; se o worktree não estiver limpo, salvar
um patch ou fazer um commit antes das matrizes.
