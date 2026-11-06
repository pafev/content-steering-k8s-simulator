# Executar as matrizes de risco

Este guia é o procedimento operacional para as três matrizes UCB1. O desenho,
as fórmulas e os limites de interpretação estão no
[protocolo de pesquisa](research-protocol.md). Para preparar Kind, dependências
e NetChaos, siga [simulations.md](simulations.md).

## Condições fixas

O experimento usa dez players reais, vídeo 576p/1,5 Mb/s, 120 s por execução,
ataque após 40 s e análise de 40–120 s. O
[manifesto de falha](../manifests/risk-matrix-netchaos.yaml) configura atrasos
iniciais de 4, 12 e 9 ms para tráfego de CDN-1, CDN-2 e CDN-3 destinado aos
pods de clientes. A calibração deve confirmar a ordem observada de
recompensas `CDN-1 > CDN-3 > CDN-2`; a configuração de atraso por si só não
a garante. O runner cria um pod `dash-client` por player e remove os pods e
objetos NetChaos ao fim de cada execução. Execute somente uma matriz por vez.

### Proveniência dos atrasos

O histórico do repositório (commit `fbda50d`, de 2026-10-07) registra a
escolha com base em uma hora de pings ICMP IPv4 da [sonda RIPE Atlas
24628](https://atlas.ripe.net/api/v2/probes/24628/), em conexão Vivo de São
Paulo, de 02:00 a 03:00 UTC em 2026-10-06. Cada rodada contém três respostas
ICMP. A mediana das **médias por rodada** nas 15 rodadas foi 3,841 ms para
[Fastly](https://atlas.ripe.net/api/v2/measurements/177401244/results/?probe_ids=24628&start=1791252000&stop=1791255600),
4,550 ms para
[Cloudflare](https://atlas.ripe.net/api/v2/measurements/176906978/results/?probe_ids=24628&start=1791252000&stop=1791255600)
e 5,161 ms para
[Amazon](https://atlas.ripe.net/api/v2/measurements/177401165/results/?probe_ids=24628&start=1791252000&stop=1791255600).
A [lista oficial de medições conhecidas do RIPE Atlas](https://atlas.ripe.net/docs/getting-started/well-known-measurements/)
confirma os IDs e os respectivos alvos (`fastly.com`, `cloudflare.com` e
`d1.awsstatic.com`). A [API pública do RIPE Atlas](https://atlas.ripe.net/docs/apis/rest-api-reference/measurements/measurements_results)
permite filtrar resultados por sonda e intervalo de tempo. Os três resumos
foram recalculados das séries vinculadas acima; a série da Amazon tem também
rodadas acima de 50 ms, de modo que sua mediana esconde variação relevante.

Os três operadores são **alvos de medição**, não identidades atribuídas às
CDNs Nginx do simulador. A correspondência usada para a *ordem* foi
CDN-1/Fastly, CDN-3/Cloudflare e CDN-2/Amazon. Os valores configurados
4/9/12 ms são parâmetros de cenário que preservam a ordem dos três resumos;
não são os RTTs ICMP medidos, nem uma medição de atraso unilateral, TTLB de segmento
ou latência representativa de toda a rede brasileira. Em particular, o
Amazon medido foi `d1.awsstatic.com`, não uma CDN brasileira identificada.

Cada matriz tem 36 células (`M=1..6` clientes modificados × `ttlb` declarado
de 90, 200, 340, 530, 800 ou 1200 ms), dois ataques por célula e seis
controles: **78 execuções válidas por regime**. As ordens de ataque são
embaralhadas e salvas. O runner aguarda a barreira de recursos do cluster
antes de cada execução; consulte o respectivo `idle-check.json` se ela falhar.

## Executar ou retomar

Na raiz do repositório, escolha **um** regime por invocação:

```sh
bash scripts/run_research_matrices.sh low
bash scripts/run_research_matrices.sh medium
bash scripts/run_research_matrices.sh high
```

`low`, `medium` e `high` usam `lambda=1`, `10` e `25`, respectivamente.
O segundo argumento opcional define a raiz de saída (padrão:
`results/research-matrices`). Repetir o mesmo comando retoma a matriz:
execuções válidas são reutilizadas e falhas são refeitas. O script exige seis
controles e dois ataques válidos em cada célula antes de produzir os mapas.
Com todas as execuções válidas já presentes, a mesma invocação refaz os plots
diretamente dos runs arquivados; não é necessário apagar os PNGs antigos.
Na primeira passagem, há um controle após cada seis ataques; a segunda
passagem completa o segundo ataque por célula sem novos controles.

Um terceiro argumento opcional substitui o manifesto NetChaos padrão. Use uma
raiz de saída exclusiva para cada cenário de rede; controle e ataque devem
usar o mesmo manifesto. A matriz continua com dez clientes, UCB1, 120 s,
seis controles e dois ataques por célula. Valide o cenário com runs isolados
antes de executar a matriz completa. No manifesto padrão, cada controle exige
`CDN-1 > CDN-3 > CDN-2` em recompensa; com manifesto alternativo, exige apenas
que a CDN-1 seja a melhor das três.

Em 2026-11-01, quatro runs com rebuffer observado em clientes honestos foram
retirados das matrizes ativas para reexecução: `low` (`M=6`, `ttlb=340`),
`medium` (`M=3`, `ttlb=90` e `530`) e `high` (`M=2`, `ttlb=1200`). Os runs,
logs, plots anteriores e `selection.json` estão em
`results/excluded-rebuffer-20261101/`. Os comandos acima encontrarão uma
execução válida restante em cada uma dessas células e criarão a segunda.
Esta foi uma seleção após observar o desfecho; consulte o
[protocolo](research-protocol.md) antes de interpretar os novos mapas.

Após a conclusão, confira em `results/research-matrices/<regime>/plots/ucb1/`
as 36 linhas de `cells.csv`, 72 de `attack-runs.csv` e seis de `controls.csv`.
`controls-summary.csv` resume os gaps de recompensa e a prioridade da CDN-1;
`calibration.json` mostra a calibração detalhada. `metrics.json` preserva
efeitos individuais e caminhos dos runs. `D_steer.png` e `Delta_c.png`
exibem as médias das células. O plotter ignora tentativas
falhas e respostas de mídia que não foram `HIT`.
Os títulos usam `D` com subscrito `steer` e `Δ` com subscrito `egress cost`.
Os dois mapas usam limites de cor fixos entre regimes: `D_steer` de −50 a
+50 pontos percentuais e `Delta_c` de −0,025 a +0,025 USD/GB. `D_steer`
permanece como fração (0–1) nos CSVs e JSON; só o plot o converte para pontos
percentuais. As pontas da legenda indicam valores
fora do limite, enquanto o número na célula conserva o valor calculado.

## Falha por cache após uma pausa longa

As matrizes exigem `HIT` em todas as respostas de mídia do browser.
O NGINX usa `proxy_cache_valid 24h` para os objetos estáticos e ignora o
`Cache-Control: max-age=3600` da origem. Aquecer um objeto já em `HIT` **não
renova** sua validade. Se uma matriz atravessar o vencimento do cache,
respostas `STALE`, `UPDATING` ou `REVALIDATED` invalidam a execução, ainda
que o corpo tenha vindo do cache. Verifique `cache-validation.json` para
separar esses estados de misses reais.

Com a execução parada e sem pods `dash-client` nem objetos `NetworkChaos`
ativos, recrie os três pods de CDN para esvaziar os caches e retome o mesmo
regime:

```sh
kubectl --context kind-kind get networkchaos
kubectl --context kind-kind get pods -l app=dash-client
kubectl --context kind-kind delete pod cdn-1-edge-1 cdn-2-edge-1 cdn-3-edge-1
kubectl --context kind-kind apply -f manifests/k8s-deploy.yaml
kubectl --context kind-kind wait --for=condition=Ready \
  pod/cdn-1-edge-1 pod/cdn-2-edge-1 pod/cdn-3-edge-1 --timeout=180s
bash scripts/run_research_matrices.sh high
```

Substitua `high` pelo regime interrompido. O primeiro run aquece os caches
vazios; runs válidos anteriores são preservados. Se a falha ocorrer antes do
aquecimento por `Connection refused`, verifique a prontidão dos serviços
após a recriação dos pods e repita o mesmo comando. Não force a inclusão de
uma tentativa não `HIT` apenas para completar a matriz.
