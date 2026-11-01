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
Na primeira passagem, há um controle após cada seis ataques; a segunda
passagem completa o segundo ataque por célula sem novos controles.

Após a conclusão, confira em `results/research-matrices/<regime>/plots/ucb1/`
as 36 linhas de `cells.csv`, 72 de `attack-runs.csv` e seis de `controls.csv`.
`controls-summary.csv` resume os gaps de recompensa e a prioridade da CDN-1;
`calibration.json` mostra a calibração detalhada. `metrics.json` preserva
efeitos individuais e caminhos dos runs. `D_steer.png`, `D_viewer.png` e
`Delta_c.png` exibem as médias das células. O plotter ignora tentativas
falhas e respostas de mídia que não foram `HIT`.

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
