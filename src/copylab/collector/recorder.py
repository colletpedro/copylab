"""Gravador de WebSocket (design §3.4; RF-COL-01, RF-COL-03, RF-COL-04; T-010 e T-011).

Uma conexão, três assinaturas por ativo (melhor compra e venda, livro na assinatura
rápida e negócios) e um ping periódico. Cada mensagem é gravada como veio, com o instante
de recebimento e o da abertura da conexão que a trouxe, num segmento por ativo, canal e
hora (:mod:`copylab.storage.segments`).

O gravador não interpreta preço. Ele lê só o nome do canal e o do ativo de cada mensagem,
para saber em que segmento ela vai. Mensagem que não é de um ativo assinado vai, intacta,
para a família de eventos.

Formato e limites conferidos na documentação oficial da Hyperliquid em 2026-10-07
(seções "Subscriptions", "Timeouts and heartbeats" e "Rate limits and user limits"):

- assinatura: ``{"method": "subscribe", "subscription": {"type": ..., "coin": ...}}``;
  ``l2Book`` com ``"fast": true`` dá 5 níveis (sem ele, 20 níveis a cada ~5 s);
- ping: ``{"method": "ping"}``, respondido com ``{"channel": "pong"}``; a corretora fecha
  a conexão que passa 60 s sem mandar mensagem;
- por IP: 1.000 assinaturas, 10 conexões e 30 conexões novas por minuto. Com 27 ativos
  são 81 assinaturas numa conexão, e o recuo entre tentativas começa em 1 s e dobra.

Nenhuma assinatura de usuário, nenhuma chave, nenhum endpoint de ordem (ADR-0001).
"""

import asyncio
import contextlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Final

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosedOK, WebSocketException

from copylab.logging import get_logger
from copylab.storage.segments import EVENTS, Record, SegmentStore, SegmentWriter
from copylab.timeutil import Ms, hour_floor

__all__ = [
    "CHANNELS",
    "CLOSE_TIMEOUT_S",
    "PING_INTERVAL_S",
    "WS_URL",
    "Recorder",
    "RecorderConfig",
    "route",
    "run",
    "subscriptions",
]

log = get_logger(__name__)

#: WebSocket público de mainnet (documentação da Hyperliquid, "Websocket").
WS_URL: Final = "wss://api.hyperliquid.xyz/ws"
#: A corretora fecha a conexão depois de 60 s sem mensagem do cliente. Um ping a cada
#: 20 s deixa duas tentativas de folga antes desse prazo.
PING_INTERVAL_S: Final = 20.0
#: Espera máxima pelo fechamento educado de uma conexão. O padrão do `websockets` é 10 s:
#: numa reconexão, essa espera viraria lacuna, e a corretora nem sempre responde ao pedido
#: de fechamento. Medido no primeiro teste do roteiro (docs/coletor.md): 10 s por parada.
CLOSE_TIMEOUT_S: Final = 1.0
#: Canal da corretora -> canal gravado. Só o livro na assinatura rápida é gravado.
CHANNELS: Final = {"bbo": "bbo", "l2Book": "book", "trades": "trades"}


def subscriptions(coins: Sequence[str]) -> list[dict[str, Any]]:
    """As três assinaturas de cada ativo, na ordem em que são enviadas."""
    subs: list[dict[str, Any]] = []
    for coin in coins:
        subs.append({"type": "bbo", "coin": coin})
        subs.append({"type": "l2Book", "coin": coin, "fast": True})
        subs.append({"type": "trades", "coin": coin})
    return subs


def route(raw: bytes) -> tuple[str, str] | None:
    """``(ativo, canal gravado)`` de uma mensagem de dados, ou ``None`` para as demais."""
    try:
        message = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(message, dict):
        return None
    name = message.get("channel")
    channel = CHANNELS.get(name) if isinstance(name, str) else None
    if channel is None:
        return None
    data = message.get("data")
    item = data[0] if isinstance(data, list) and data else data
    coin = item.get("coin") if isinstance(item, dict) else None
    return (coin, channel) if isinstance(coin, str) else None


class Recorder:
    """Distribui as mensagens pelos segmentos da hora. Não interpreta conteúdo."""

    def __init__(self, store: SegmentStore, coins: Sequence[str], now: Callable[[], Ms]) -> None:
        self._store = store
        self._coins = frozenset(coins)
        self._now = now
        self._writers: dict[tuple[str, str], SegmentWriter] = {}
        self._last_opened: dict[tuple[str, str], int] = {}

    def record(self, recv_ms: Ms, conn_ms: Ms, raw: bytes) -> None:
        key = route(raw)
        if key is None or key[0] not in self._coins:
            key = EVENTS
        self._writer(key, recv_ms).append(Record(recv_ms, conn_ms, raw))

    def event(self, conn_ms: Ms, kind: str, **detail: object) -> None:
        """Registra um evento da conexão (conexão, desconexão, parada) no instante atual."""
        raw = json.dumps({"event": kind, **detail}, sort_keys=True).encode()
        at = self._now()
        self._writer(EVENTS, at).append(Record(at, conn_ms, raw))
        log.info("collector.event", kind=kind, conn_ms=conn_ms, **detail)

    def _writer(self, key: tuple[str, str], recv_ms: Ms) -> SegmentWriter:
        hour = hour_floor(recv_ms)
        writer = self._writers.get(key)
        if writer is not None and writer.ref.hour_ms != hour:
            writer.close()
            writer = None
        if writer is None:
            # Dois segmentos da mesma hora nunca têm o mesmo instante de abertura.
            opened = max(recv_ms, self._last_opened.get(key, recv_ms - 1) + 1)
            self._last_opened[key] = opened
            writer = self._store.open_writer(key[0], key[1], hour, Ms(opened))
            self._writers[key] = writer
        return writer

    def flush(self) -> None:
        """Descarrega tudo e fecha os segmentos de horas que já terminaram."""
        current = hour_floor(self._now())
        for key, writer in list(self._writers.items()):
            if writer.ref.hour_ms < current:
                writer.close()
                del self._writers[key]
            else:
                writer.flush()

    def close(self) -> None:
        for writer in self._writers.values():
            writer.close()
        self._writers.clear()


@dataclass(frozen=True, slots=True)
class RecorderConfig:
    url: str
    coins: tuple[str, ...]
    flush_s: float
    silence_s: float
    backoff_initial_s: float
    backoff_max_s: float


async def _ping(ws: Any) -> None:
    while True:
        await asyncio.sleep(PING_INTERVAL_S)
        await ws.send(json.dumps({"method": "ping"}))


async def _session(
    config: RecorderConfig,
    recorder: Recorder,
    now: Callable[[], Ms],
    conn_ms: Ms,
    stop: asyncio.Event,
) -> tuple[str, bool]:
    """Uma conexão, do início ao fim. Devolve o motivo do fim e se chegou alguma mensagem."""
    loop = asyncio.get_running_loop()
    received = False
    try:
        async with connect(
            config.url, ping_interval=None, max_size=None, close_timeout=CLOSE_TIMEOUT_S
        ) as ws:
            recorder.event(conn_ms, "connect", url=config.url)
            for sub in subscriptions(config.coins):
                await ws.send(json.dumps({"method": "subscribe", "subscription": sub}))
            pinger = asyncio.create_task(_ping(ws))
            last = loop.time()
            try:
                while not stop.is_set():
                    try:
                        raw = await asyncio.wait_for(ws.recv(decode=False), timeout=0.5)
                    except TimeoutError:
                        if loop.time() - last > config.silence_s:
                            return f"sem mensagem por mais de {config.silence_s:g} s", received
                        continue
                    recorder.record(now(), conn_ms, raw)
                    received = True
                    last = loop.time()
                return "parada", received
            finally:
                pinger.cancel()
    except ConnectionClosedOK as exc:
        return f"fechada pela corretora: {exc}", received
    except (WebSocketException, OSError, TimeoutError) as exc:
        return f"{type(exc).__name__}: {exc}", received


async def _flush_every(recorder: Recorder, seconds: float, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=seconds)
        except TimeoutError:
            recorder.flush()


async def run(
    config: RecorderConfig, recorder: Recorder, now: Callable[[], Ms], stop: asyncio.Event
) -> None:
    """Grava até ``stop``, reconectando sozinho, com recuo, a cada queda (RF-COL-02 CA-02.1).

    Cada conexão é identificada pelo instante em que foi aberta, que vai em cada registro.
    É por ele que a compactação reconhece uma desconexão entre duas mensagens.
    """
    flusher = asyncio.create_task(_flush_every(recorder, config.flush_s, stop))
    backoff = config.backoff_initial_s
    conn_ms = now()
    try:
        while not stop.is_set():
            conn_ms = now()
            reason, received = await _session(config, recorder, now, conn_ms, stop)
            if stop.is_set():
                recorder.event(conn_ms, "stop")
                break
            if received:
                backoff = config.backoff_initial_s
            recorder.event(conn_ms, "disconnect", reason=reason, retry_in_s=backoff)
            recorder.flush()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=backoff)
            backoff = min(backoff * 2, config.backoff_max_s)
    except asyncio.CancelledError:
        # No Windows, Ctrl+C chega como cancelamento do laço, e não como sinal.
        recorder.event(conn_ms, "stop", reason="cancelado")
        raise
    finally:
        stop.set()
        await flusher
        recorder.close()
