# Run simulations

Run commands from the repository root. The examples use the `kind-kind` context
and the packaged video in `bucket/`. Install
Docker, Kind, kubectl, mkcert, and Python first.

## Start the simulator

```sh
./setup.sh
```

The gateway is optional for simulations. To inspect health and run state, use
`kubectl --context kind-kind port-forward pod/gateway 5000:80` and open
`http://localhost:5000`.

Install the runner and plotting dependencies:

```sh
python3 -m venv .venv
.venv/bin/pip install -r scripts/requirements.txt -r scripts/plot-requirements.txt
```

`./setup.sh` builds the dash-client image, restarts the
simulator pods and clears their ephemeral CDN caches. Ensure the NetChaos
controller and agents are installed in the same Kind cluster before applying a
latency fault; see the separate NetChaos Simulator project.
Check that its CRD, controller, and node agents are present:

```sh
kubectl --context kind-kind get crd networkchaos.net-chaos-simulator.pafev.dev
kubectl --context kind-kind get pods -n net-chaos-simulator-system
```

## Clean baseline

The runner launches one dash-client pod per client. Each pod fetches its MPD
and segments from CDN services, steering from the CSS, and sends CMCD directly
to telemetry. The runner warms CDN caches through temporary CDN port forwards.

```sh
.venv/bin/python scripts/multi_client.py --strategy ucb1 --clients 5 \
  --seconds 60 --output results/clean
```

The runner starts independent dash.js sessions in one fresh run, warms
all CDN caches with full GETs, verifies HITs, and saves the results. Use
`--strategy all` for separate UCB1, epsilon-greedy, and LinUCB runs. Use a
new invocation for each independent trial; do not reuse a run ID.
The general runner and player now default to 720p/3,000 kb/s. Pass
`--max-video-kbps 1500` for a 576p pilot; the historical matrix script pins
this value independently.

## Modified player reporting false latency

Run another clean baseline without an active NetChaos fault. Then start five
honest players and one modified dash.js player (six total):

```sh
.venv/bin/python scripts/multi_client.py --strategy ucb1 --clients 6 \
  --seconds 60 --malicious-count 1 --malicious-cdn cdn-1 \
  --attack-ttlb 800 --output results/modified-player
```

The modified player follows CSS decisions and downloads real media. For
successful CDN-1 video responses, it declares `ttlb=800 ms`. The reported
delivery reward is then computed from `d/(d+lambda×ttlb)`; with `d=4000 ms`
and the default `lambda=5`, it is 0.5.

For a separate pilot that poisons learning from the first modified-player
response, use `--attack-from-start` with `--malicious-count` and omit
`--attack-delay`. This changes the attack timing and should not be mixed with
the 40 s delayed risk matrices.

The run's `modified-players.json` records original and claimed timing,
matching responses, and telemetry ingestion results. The role label is used
only by the runner, not by CSS policy.

For the 10-player attack experiment and matched controls, see [risk-matrix.md](risk-matrix.md).

## Pilotos de QoE

Após editar `client/assets/js/main.js`, reconstrua e carregue a imagem do
cliente antes dos novos runs:

```sh
docker build -t pafev/content-steering:client-latest ./client
kind load docker-image --name kind pafev/content-steering:client-latest
```

O runner grava `viewer-traces.json` com eventos nativos (`waiting`, `pause`,
`error`), a pilha de chamadas JavaScript a `video.pause()`, e eventos oficiais
do dash.js (`qualityChangeRendered`, `error`),
além de amostras de avanço a cada 500 ms. Cada `summary.json` inclui, por
player, `qoe`: fração da janela sem avanço, tempo pausado, falha terminal,
bitrate de vídeo exibido ponderado pelo tempo com avanço e `qoe_index`.
`rebuffer_seconds` fica em campo separado. O índice é a fração da janela com
avanço multiplicada pelo bitrate exibido médio dividido pelo teto ABR do run
(1.500 ou 3.000 kb/s). É um
índice operacional para **o mesmo vídeo**, não MOS nem modelo perceptual
validado. Fica `null` se houver avanço mas a cobertura de qualidade exibida
for inferior a 95%; se não houver qualquer avanço, vale zero.
O atraso de partida não integra esses desfechos.

Use `--allow-viewer-failure` somente nos pilotos de QoE: erro ou pausa
posterior ao início da reprodução passa a ser um desfecho observado, mas
falhas de infraestrutura, ausência de início e fim natural do vídeo ainda
invalidam o run. O script histórico de matrizes não usa essa opção.

Para uma comparação temporal separada, com seis controles e seis ataques
independentes na mesma dose, use `plot_qoe_timeline.py`. O estudo de dose
abaixo tem apenas dois ataques por TTLB e não gera essa figura. O script
temporal usa as médias de run dos mesmos slots honestos (`M+1..10`). A faixa sombreada
mostra o desvio padrão **entre runs**. O quarto painel mostra a diferença
ataque−controle do tempo sem progresso acumulado, com intervalo bootstrap
pontual de 95% reamostrando runs. Não interprete o primeiro instante em que
a faixa cruza zero como limiar causal preciso. O CSV vizinho ao PNG guarda os
12 resumos individuais. Passe os caminhos dos diretórios `multi-<id>` completos:

```sh
.venv/bin/python scripts/plot_qoe_timeline.py \
  --controls <controle1> <controle2> <controle3> <controle4> <controle5> <controle6> \
  --attacks <ataque1> <ataque2> <ataque3> <ataque4> <ataque5> <ataque6> \
  --output results/qoe-final/timeline.png
```

## Orquestrador de dose existente

`scripts/run_qoe_dose_response.sh` reutiliza `scripts/multi_client.py`, mas
foi escrito para um estudo **específico**: seis controles, dois ataques por
TTLB, dez clientes, `M=3`, UCB1, `lambda=10`, 120 s, ataque após 40 s e teto
ABR de 720p/3.000 kb/s. O Bash intercala controles e registra ordem, doses,
SHA do manifesto e condições para retomada. Ele produz apenas os plots de QoE
via `plot_qoe_dose_response.py`; ainda falta acrescentar steering, rota real
e custo à análise da mesma série, como definido no
[protocolo do TCC](research-protocol.md#próximas-alterações-de-código).
As doses agora são obrigatórias no comando, após calibrar o cenário.

A grade anteriormente sugerida de TTLBs e os pilotos com o manifesto
`manifests/qoe-pilot-netchaos.yaml` (4/270/250 ms) são exploratórios e não
definem o novo experimento principal. Os controles desse cenário mediram
aproximadamente 1,5–1,8 s na CDN-2 e 1,3–1,5 s na CDN-3; um ataque tardio
com `M=3` e TTLB falso de 12.000 ms em 720p não mostrou queda honesta. Dois
ataques curtos com quatro players em 4/900/900 ms reduziram qualidade frente
a um controle, mas não atendem ao desenho de dez players e 40 s. Um novo par
de dez players em 9/270/900 ms e TTLB falso de 9.000 ms também não mostrou
queda de QoE; seus artefatos estão em `results/qoe-pilots/9-270-900/`.
Não misture esses pilotos com a amostra final.

O teto de 720p foi testado em `results/qoe-cap-pilots/`: dois controles de
dez clientes em 576p e dois em 720p, todos válidos e sem rebuffer ou falhas
terminais. O consumo de CPU e memória subiu em 720p, mas não houve sinal de
saturação nos testes locais. Esse resultado não dispensa verificar recursos
no novo manifesto. Para repetir em 576p, use `QOE_MAX_VIDEO_KBPS=1500` e
outra raiz de saída; o índice de QoE não deve ser comparado diretamente
entre tetos diferentes.

Para usar o orquestrador em um **piloto** com doses explicitamente escolhidas:

```sh
bash scripts/run_qoe_dose_response.sh \
  manifests/qoe-pilot-netchaos.yaml results/qoe-dose-pilot \
  800 1600 5000
```

Esse comando executa doze runs válidos (seis controles, três doses com dois
ataques cada) e pode demorar. Passe outra raiz ao mudar manifesto ou doses.
O script não é um runner genérico para proporção, política ou função de
recompensa. Quando terminar, `plots/` contém `qoe-dose-response.png`,
`no-progress.png`, `rebuffer.png`, `terminal-failures.png`,
`rendered-quality.png`, `run-qoe.csv` e `dose-summary.csv`. Com dois ataques
por dose, as figuras são descritivas: não ajustar curva ou declarar um limiar
exato.

## Séries finais do TCC (etapas 1–3)

Primeiro calibre em 720p o manifesto 4/12/9 ms e os candidatos de QoE com
`scripts/multi_client.py`. Guarde pilotos fora das raízes finais. Para cada
candidato de QoE, execute um controle e um ataque **curtos**, com 60 s de
reprodução e ataque após 20 s. Mantenha `M=3` e os demais parâmetros finais.
Os players começam em sequência; examine a posição de reprodução e o buffer
de cada slot ao interpretar os pilotos.
Use uma raiz separada por piloto e consulte
`scripts/check_qoe_pilot.py <controle/multi-id> <ataque/multi-id>` para comparar
recompensa, prioridade, rota efetiva, bitrate, QoE e tempo sem progresso.
Se não houver queda, teste outras latências em manifestos novos e registre
quais candidatos foram avaliados antes de congelar as séries finais.

```sh
.venv/bin/python scripts/multi_client.py --strategy ucb1 --clients 10 \
  --seconds 60 --measurement-start 20 --reward-lambda 10 \
  --max-video-kbps 3000 --require-fresh-cache --allow-viewer-failure \
  --fault-manifest manifests/qoe-12-900-900.yaml \
  --output results/qoe-calibration-short/12-900-900/control
.venv/bin/python scripts/multi_client.py --strategy ucb1 --clients 10 \
  --seconds 60 --measurement-start 20 --reward-lambda 10 \
  --max-video-kbps 3000 --require-fresh-cache --allow-viewer-failure \
  --fault-manifest manifests/qoe-12-900-900.yaml \
  --malicious-count 3 --attack-delay 20 --attack-ttlb 9000 \
  --output results/qoe-calibration-short/12-900-900/attack
```

Para as etapas 1–2, execute a série abaixo. Ela inclui as seis
doses com `M=3` e as quatro células adicionais `M=1/5`, compartilhando seis
controles (26 runs válidos). Repetir o mesmo comando retoma somente runs que
atendam às condições registradas no `plan.json` e tenham traços de QoE.
Índices indefinidos por cobertura insuficiente continuam nos resultados, com
tempo sem avanço e falhas explícitos.

```sh
bash scripts/run_tcc_dose_proportion.sh \
  manifests/risk-matrix-netchaos.yaml results/tcc-final/dose-proportion
```

Os cenários 12/900/900 e 240/500/500 ms continuam como pilotos, não como
comandos finais aprovados. A série final de QoE será definida após validar um
cenário; seus pilotos permanecem em raízes separadas.
`TCC_PLAN_ONLY=1` imprime a ordem planejada sem executar.
`plots/` contém as curvas 0–120 s, o avanço individual dos controles e ataques
com `M=3` e CSVs de efeitos
calculados em 40–120 s. As linhas finas nas curvas são runs individuais e
a linha grossa é a média entre runs. O runner histórico de dose permanece
separado e não deve ser misturado com esta amostra.

## Read and plot results

Each invocation writes `results/<output>/<timestamp>/<run_id>/`. The useful
files are `summary.json` (configuration, final model, validity checks, attack
counts and the path to its detailed artifact),
`events.jsonl` (steering responses, media responses, feedback),
`samples.jsonl` (playback and model snapshots), and
`cache-validation.json`.
Attack runs also write `modified-players.json`.
The timestamp directory contains `warmup.json` and `runs.json`.

```sh
.venv/bin/python scripts/plot_run.py results/clean/<timestamp>
.venv/bin/python scripts/plot_run.py results/modified-player/<timestamp>
```

Open each run's `plots/index.html` or `plots/overview.png`. The six panels
show CDN mean reward and learning counts, CSS first priorities, actual media
pathways, playback position, and cache status. For the attack, compare the
honest clients' first priorities and CDN-1 mean reward before and after the
modified player reports. Mean reward is a reported delivery outcome, not session
QoE; playback position is sampled, so a flat interval is not by itself proof of
a stall. Cache state and network scheduling can differ between trials. Repeat
trials before drawing general performance conclusions.
