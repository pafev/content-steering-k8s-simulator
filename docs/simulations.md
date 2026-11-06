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
avanço multiplicada pelo bitrate exibido médio dividido por 1500 kb/s. É um
índice operacional para **o mesmo vídeo**, não MOS nem modelo perceptual
validado. Fica `null` se houver avanço mas a cobertura de qualidade exibida
for inferior a 95%; se não houver qualquer avanço, vale zero.
O atraso de partida não integra esses desfechos.

Use `--allow-viewer-failure` somente nos pilotos de QoE: erro ou pausa
posterior ao início da reprodução passa a ser um desfecho observado, mas
falhas de infraestrutura, ausência de início e fim natural do vídeo ainda
invalidam o run. O script histórico de matrizes não usa essa opção.

Após seis controles e seis ataques independentes sob as mesmas condições,
gere as médias de run dos mesmos slots honestos (`M+1..10`). A faixa sombreada
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

## Estudo de dose de TTLB e QoE

`scripts/run_qoe_dose_response.sh` chama o mesmo `scripts/multi_client.py`
usado nas matrizes históricas. O novo Bash organiza seis controles e dois
ataques por TTLB, em ordem fixa embaralhada e com controles intercalados. Usa
dez clientes, `M=3`, UCB1, `lambda=10`, 120 s e ataque após 40 s. Os resultados
ficam em uma raiz separada; a retomada reutiliza runs válidos e rejeita
mudanças de doses ou de SHA do manifesto na mesma raiz.

Com o manifesto provisório 4/850/700 ms, o controle piloto observou TTLB
mediano de 5.106 ms na CDN-2 e 3.508,5 ms na CDN-3. Por isso a primeira
grade usa 1.200, 2.500, 3.500, 5.000, 8.000 e 12.000 ms declarados para
CDN-1. Esses valores são exploratórios; os atrasos NetChaos não são TTLB.
O piloto 850/700 com ataque tardio e `M=9` não mostrou degradação honesta
reproduzível, portanto a nova grade não garante efeito com `M=3`.

```sh
mkdir -p results/qoe-dose-response
nohup bash scripts/run_qoe_dose_response.sh \
  manifests/qoe-pilot-netchaos.yaml results/qoe-dose-response \
  > results/qoe-dose-response/run.log 2>&1 &
```

Passe TTLBs adicionais ao fim do comando para substituir a grade padrão;
use outra raiz de saída ao mudar doses ou manifesto. Para conferir somente
a ordem planejada, sem executar runs, prefixe o comando com
`QOE_PLAN_ONLY=1` e omita `nohup` e redirecionamento.

Quando os 18 runs válidos terminarem, `results/qoe-dose-response/plots/`
conterá `qoe-dose-response.png`, `no-progress.png`, `rebuffer.png`,
`terminal-failures.png`, `rendered-quality.png` quando houver qualidade
observável, `run-qoe.csv` e `dose-summary.csv`. Cada figura agrega todos os
TTLBs, mostra os dois ataques individuais, a média deles e a referência dos
seis controles (média ± desvio padrão). Com dois ataques por dose, os pontos
são descritivos; não se ajusta uma curva nem se declara um limiar exato.

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
