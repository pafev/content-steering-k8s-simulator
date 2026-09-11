# DASH Content Steering simulator

Simulador multi-client de DASH Content Steering em Kubernetes/Kind, com playback
real em dash.js 5.2.1, três caches CDN Nginx, origem Caddy, telemetria CMCD,
Redis e um Content Steering Server (CSS). Baseado em
[alissonpef/Content-Steering](https://github.com/alissonpef/Content-Steering).

O objetivo é experimentar políticas de Content Steering sobre métricas agregadas
de vários clientes. O projeto implementa DASH; playback HLS não está incluído.

## Executar

Requisitos: Docker, Kind, kubectl, mkcert e mídia em `bucket/`. Somente a origem
monta esse diretório, em modo somente leitura. Veja [bucket/README.md](bucket/README.md).

```sh
./setup.sh
kubectl --context kind-kind port-forward pod/gateway 5000:80
```

Abra http://localhost:5000, informe um run ID, selecione a estratégia e carregue
o MPD. O link para outro cliente preserva o run e a estratégia; cada carregamento
cria um novo `sid`. Um novo run ID cria um modelo independente.

O setup reconstrói e carrega as imagens locais, reinicia os pods da aplicação e
limpa os caches CDN efêmeros. O estado Redis permanece até a substituição do seu
pod. Um cluster Kind existente sem `/mnt/bucket` precisa ser recriado.

## Arquitetura

```text
browser -> gateway -> dash-client -> steering-server
                         |       \-> telemetry-service -> Redis
                         \-> CDN 1/2/3 -> origin-server
                                  \----> telemetry-service (UDP logs)
```

- `dash-client`: UI, dash.js e proxy para CSS, telemetria e CDNs.
- `steering-server`: aplica a política do run e retorna `PATHWAY-PRIORITY`.
- `cdn-1..3`: caches pull-through independentes; misses consultam a origem.
- `origin-server`: único componente que monta o bucket.
- `telemetry-service`: correlaciona sessões, CMCD e logs CDN.
- `Redis`: sessões, configuração, decisões, estatísticas e auditoria por run.

O NetChaos é responsável por latência, banda e congestionamento. O CSS consome
somente o estado de decisão no Redis e não acessa a API Kubernetes.

### Fluxo

1. O cliente registra a correlação `sid -> run_id`.
2. dash.js consulta o CSS e recebe `VERSION`, `TTL`, `RELOAD-URI` e
   `PATHWAY-PRIORITY`.
3. dash.js seleciona uma `BaseURL@serviceLocation` e envia CMCD nas requisições.
4. A CDN registra status, bytes, duração e cache por UDP.
5. CMCD Response Mode (`e=rr`) e eventos do player chegam por HTTP.
6. Uma resposta elegível atualiza o modelo compartilhado; novas consultas ao
   CSS usam esse estado.

Clientes do mesmo run compartilham estatísticas, mas recebem decisões por
requisição. Atualizações concorrentes usam transações Redis, portanto workers do
CSS não mantêm modelos divergentes.

Os MPDs anunciam três BaseURLs absolutas com a autoridade de empacotamento
`http://content-steering.invalid`. O proxy troca somente essa autoridade pelo
gateway visível ao navegador, preservando as três opções no dash.js. A seleção é
nativa do player; Pathway Cloning não é necessário para os pathways fixos deste
simulador.

## Políticas e aprendizado

| Estratégia | Implementação |
| --- | --- |
| `fixed` | Prioridade fixa `cdn-1`, `cdn-2`, `cdn-3` |
| `random` | Permutação uniforme por consulta |
| `epsilon_greedy` | Médias amostrais, epsilon 0,2 e exploração de braços novos |
| `ucb1` | `media + sqrt(2 log(total) / observacoes)` |
| `linucb` | Modelos ridge disjuntos, identidade inicial e alpha 1 |

A primeira sessão define estratégia e seed do run; registros conflitantes são
rejeitados. A seed controla o RNG das decisões, mas ordem dos relatórios e
agendamento de rede também devem ser registrados para reprodução completa.

Cada decisão aceita no máximo uma recompensa: a primeira resposta de segmento de
vídeo correlacionada pelo seu ID. Init, áudio, segmentos posteriores, eventos do
player e logs CDN permanecem observáveis, mas não contam como novos pulls. A
recompensa é atribuída à CDN efetivamente reportada, contemplando fallbacks.

Para HTTP 2xx, a recompensa básica é `1 / (1 + ttlb_ms / REWARD_SCALE_MS)`;
outros status recebem zero. O scale padrão é 1000 ms. Essa função é uma baseline
configurável, não uma métrica QoE padronizada.

LinUCB usa o contexto `[1, buffer_ms / (buffer_ms + 10000)]`, capturado antes da
decisão. `RELOAD-URI` transporta o `decision_id` privado, que o cliente copia para
`cs_decision` na URL da mídia. Esses parâmetros servem à correlação do simulador
e não são campos CMCD.

Decisões expiram após `FEEDBACK_MAX_AGE_SECONDS` (60 por padrão). Feedback tardio
não treina; quando o último feedback aceito fica stale, a seleção volta à
exploração cold-start sem apagar o modelo acumulado. Redis indisponível faz o CSS
retornar prioridade fixa para preservar o playback.

## CMCD e RUM

CMCD v2 Response/Event Mode fornece a perspectiva RUM do player: tempos de
resposta, buffer, estado, startup e erros. Logs CDN complementam essa visão com
status, bytes, duração e cache observados no servidor.

Valores declarados pelo cliente continuam não confiáveis quando copiados para
logs CDN. `mtp` é uma estimativa histórica do cliente, não throughput medido na
requisição atual. Pares inválidos (`ttfb > ttlb`) ficam na auditoria, mas não
entram nos agregados. O aprendizado usa `ttlb`; logs CDN não geram uma segunda
atualização do modelo.

## Interfaces e estado

- `GET /steering/manifest.json` e `GET /steering/healthz`
- `POST /telemetry/v1/sessions`
- `POST /telemetry/v1/cmcd/events` (`application/cmcd`, 1–100 registros)
- `GET /telemetry/v1/state/<run_id>` e `GET /telemetry/healthz`

Sessões expiram após uma hora sem renovação; a UI renova a cada 30 segundos. As
chaves de run expiram após 24 horas de inatividade. Os streams Redis
`run:<id>:decisions` e `run:<id>:observations` guardam aproximadamente os últimos
5.000 registros. Eles são diagnósticos limitados, não armazenamento durável.
Logs UDP são best effort.

## Testes

```sh
python3 -m venv .venv
.venv/bin/pip install -r steering-server/requirements.txt pytest
.venv/bin/python -m pytest tests telemetry-service/tests
node --check client/assets/js/main.js
```

Os testes usam instâncias Redis temporárias. [tests/compose.yaml](tests/compose.yaml)
oferece um smoke test isolado em `localhost:15000`; defina `TEST_CERT_DIR` com
`cdn.pem` e `cdn-key.pem`. [tests/browser_smoke.py](tests/browser_smoke.py) valida
playback, CMCD, cache, estado compartilhado e seleção de mais de uma CDN.
[examples/cmcd_client.py](examples/cmcd_client.py) gera carga CMCD controlada sem
executar vídeo.

## Invariantes do simulador

- Estado e configuração são isolados por `run_id`; um cliente não reseta o run.
- A estratégia escolhida não é substituída por outra heurística de telemetria.
- Uma decisão produz no máximo uma atualização atômica do modelo.
- Contexto é capturado no momento da decisão e preservado até o feedback.
- Identidades ou rótulos definidos pelo avaliador não entram nas políticas.
- Cache, telemetria e decisão permanecem componentes separados.

## Base técnica

- [ETSI TS 103 998](https://www.etsi.org/deliver/etsi_ts/103900_103999/103998/01.01.01_60/ts_103998v010101p.pdf): sinalização DASH e interação com o CSS; não prescreve algoritmo de decisão.
- [Apple WWDC22](https://developer.apple.com/videos/play/wwdc2022/10144/): políticas regionais, buckets e `RELOAD-URI`; não documenta a arquitetura interna do Apple TV+.
- [dash.js CMCD](https://dashif.org/dash.js/pages/usage/cmcd.html): Request, Response e Event Mode.
- [Akamai — player analytics with CMCD](https://www.akamai.com/blog/cloud/get-your-player-analytics-with-cmcd): observações complementares do player e CDN.
- [Auer et al., 2002](https://doi.org/10.1023/A:1013689704352): UCB1.
- [Li et al., WWW 2010](https://www.schapire.net/papers/www10.pdf): LinUCB disjunto.
