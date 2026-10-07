"""Gravador de WebSocket contra um servidor falso, local (T-010, T-011).

Nenhum teste aqui fala com a corretora: o servidor é `websockets` em `127.0.0.1`, numa
porta livre, e o roteiro de cada teste diz o que ele manda, quando se cala e quando
derruba a conexão. As mensagens são cópias do formato real gravado na verificação de
dados (`data/verify/ws/`), com valores à mão.

Prova de dente de `test_recorder_writes_bbo_and_fast_book_with_both_timestamps_compressed`,
feita à mão em 2026-10-07 e restaurada, uma mutação por vez em `copylab.collector.recorder`:

- `subscriptions` sem `"fast": True`: o teste falhou na conferência das assinaturas.
- `Recorder.record` gravando `raw.strip(b"}")`: o teste falhou, porque a mensagem gravada
  deixou de ser byte a byte a enviada (e outros três, pelo mesmo motivo).
- `route` mandando `l2Book` para o canal `l2Book` em vez de `book`: o teste falhou, porque
  o segmento de livro não apareceu.

Prova de dente de `test_recorder_reconnects_with_backoff_and_records_each_disconnect`:
`run` sem o laço de reconexão (`break` depois da primeira desconexão) fez o teste falhar,
com uma conexão só, e também os testes de silêncio e de recuo.
"""

import asyncio
import gzip
import json
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
from websockets.asyncio.server import ServerConnection, serve

from copylab import clock
from copylab.collector.recorder import Recorder, RecorderConfig, route, run, subscriptions
from copylab.storage.segments import EVENTS, SegmentStore
from copylab.timeutil import MS_PER_HOUR, Ms

BBO_BTC = (
    b'{"channel":"bbo","data":{"coin":"BTC","time":1791261053067,"bbo":'
    b'[{"px":"85560.0","sz":"5.61122","n":21},{"px":"85561.0","sz":"2.07737","n":22}]}}'
)
BOOK_BTC = (
    b'{"channel":"l2Book","data":{"coin":"BTC","time":1791261051777,"levels":'
    b'[[{"px":"85560.0","sz":"5.61122","n":21}],[{"px":"85561.0","sz":"2.22707","n":23}]],'
    b'"fast":true}}'
)
TRADES_BTC = (
    b'{"channel":"trades","data":[{"coin":"BTC","side":"B","px":"85561.0","sz":"0.00047",'
    b'"time":1791261053067,"hash":"0x00","tid":635248800193868,'
    b'"users":["0x1e1e5046b07be9a2d0f5223a723bf49e23b5ef73",'
    b'"0xf58b673c1633ccef0ac58263cdc95ed80f817fc7"]}]}'
)
BBO_ETH = BBO_BTC.replace(b'"BTC"', b'"ETH"')
SUB_ACK = b'{"channel":"subscriptionResponse","data":{"method":"subscribe"}}'
PONG = b'{"channel":"pong"}'

Script = Callable[[ServerConnection, int], Awaitable[None]]


class FakeExchange:
    """Servidor falso: guarda o que cada conexão pediu e roda o roteiro do teste."""

    def __init__(self, script: Script) -> None:
        self.script = script
        self.subscriptions: list[list[dict[str, object]]] = []
        self.done = asyncio.Event()

    async def handler(self, ws: ServerConnection) -> None:
        number = len(self.subscriptions)
        received: list[dict[str, object]] = []
        self.subscriptions.append(received)

        async def collect() -> None:
            async for message in ws:
                payload = json.loads(message)
                if payload.get("method") == "subscribe":
                    received.append(payload["subscription"])

        reader = asyncio.create_task(collect())
        try:
            await self.script(ws, number)
        finally:
            reader.cancel()


async def record_against(
    exchange: FakeExchange,
    store: SegmentStore,
    coins: tuple[str, ...],
    *,
    silence_s: float = 5.0,
    settle_s: float = 0.3,
) -> None:
    """Grava contra o servidor falso até o roteiro terminar, e então para o gravador."""
    async with serve(exchange.handler, "127.0.0.1", 0) as server:
        port = next(iter(server.sockets)).getsockname()[1]
        config = RecorderConfig(
            url=f"ws://127.0.0.1:{port}",
            coins=coins,
            flush_s=0.05,
            silence_s=silence_s,
            backoff_initial_s=0.01,
            backoff_max_s=0.04,
        )
        stop = asyncio.Event()
        task = asyncio.create_task(run(config, Recorder(store, coins, clock.now), clock.now, stop))
        await asyncio.wait_for(exchange.done.wait(), timeout=10)
        await asyncio.sleep(settle_s)
        stop.set()
        await asyncio.wait_for(task, timeout=10)


def raws(store: SegmentStore, coin: str, channel: str) -> list[bytes]:
    return [
        r.raw
        for ref in store.segments()
        if (ref.coin, ref.channel) == (coin, channel)
        for r in store.read(ref)
    ]


def events(store: SegmentStore) -> list[dict[str, object]]:
    found = []
    for raw in raws(store, *EVENTS):
        payload = json.loads(raw)
        if "event" in payload:
            found.append(payload)
    return found


async def _wait_subscribed(ws: ServerConnection, exchange: FakeExchange, n: int) -> None:
    for _ in range(200):
        if len(exchange.subscriptions[-1]) >= n:
            return
        await asyncio.sleep(0.01)


# ─── Roteamento e assinaturas ────────────────────────────────────────────────


@pytest.mark.unit
def test_subscriptions_are_bbo_fast_book_and_trades_per_coin() -> None:
    assert subscriptions(["BTC", "kPEPE"]) == [
        {"type": "bbo", "coin": "BTC"},
        {"type": "l2Book", "coin": "BTC", "fast": True},
        {"type": "trades", "coin": "BTC"},
        {"type": "bbo", "coin": "kPEPE"},
        {"type": "l2Book", "coin": "kPEPE", "fast": True},
        {"type": "trades", "coin": "kPEPE"},
    ]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (BBO_BTC, ("BTC", "bbo")),
        (BOOK_BTC, ("BTC", "book")),
        (TRADES_BTC, ("BTC", "trades")),
        (SUB_ACK, None),
        (PONG, None),
        (b'{"channel":"trades","data":[]}', None),
        (b'{"channel":"error","data":"x"}', None),
        (b"nao e json", None),
        (b"[1, 2]", None),
    ],
)
def test_route_reads_only_channel_and_coin(raw: bytes, expected: tuple[str, str] | None) -> None:
    assert route(raw) == expected


# ─── Gravação ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_recorder_writes_bbo_and_fast_book_with_both_timestamps_compressed(
    tmp_path: Path,
) -> None:
    """RF-COL-01 CA-01.1. Melhor compra e venda e livro rápido, com o instante da corretora
    (dentro da mensagem, intacta) e o de recebimento (no registro), em gzip."""

    async def script(ws: ServerConnection, number: int) -> None:
        await _wait_subscribed(ws, exchange, 6)
        for message in (SUB_ACK, BBO_BTC, BOOK_BTC, TRADES_BTC, BBO_ETH, PONG):
            await ws.send(message.decode())
        exchange.done.set()
        await ws.wait_closed()

    exchange = FakeExchange(script)
    store = SegmentStore(tmp_path)
    before = clock.now()
    asyncio.run(record_against(exchange, store, ("BTC", "ETH")))
    after = clock.now()

    assert exchange.subscriptions == [subscriptions(["BTC", "ETH"])]
    assert all(s.get("fast") is True for s in exchange.subscriptions[0] if s["type"] == "l2Book")

    assert raws(store, "BTC", "bbo") == [BBO_BTC]
    assert raws(store, "BTC", "book") == [BOOK_BTC]
    assert raws(store, "BTC", "trades") == [TRADES_BTC]
    assert raws(store, "ETH", "bbo") == [BBO_ETH]
    for ref in store.segments():
        assert ref.path.read_bytes()[:2] == b"\x1f\x8b"  # gzip
        gzip.decompress(ref.path.read_bytes())
        for record in store.read(ref):
            assert before <= record.conn_ms <= record.recv_ms <= after
    (book,) = [r for ref in store.segments() if ref.channel == "book" for r in store.read(ref)]
    assert json.loads(book.raw)["data"]["time"] == 1_791_261_051_777  # relógio da corretora

    control = raws(store, *EVENTS)
    assert SUB_ACK in control
    assert PONG in control
    assert [e["event"] for e in events(store)] == ["connect", "stop"]


@pytest.mark.unit
def test_recorder_reconnects_with_backoff_and_records_each_disconnect(tmp_path: Path) -> None:
    """RF-COL-02 CA-02.1, do lado do gravador. A corretora derruba a primeira conexão; o
    gravador reconecta sozinho, assina de novo, e cada mensagem leva a conexão que a trouxe.
    """

    async def script(ws: ServerConnection, number: int) -> None:
        await _wait_subscribed(ws, exchange, 3)
        await ws.send(BOOK_BTC.decode())
        if number == 0:
            await asyncio.sleep(0.1)
            await ws.close(code=1011, reason="queda simulada")
            return
        exchange.done.set()
        await ws.wait_closed()

    exchange = FakeExchange(script)
    store = SegmentStore(tmp_path)
    asyncio.run(record_against(exchange, store, ("BTC",)))

    assert len(exchange.subscriptions) == 2
    assert exchange.subscriptions[1] == subscriptions(["BTC"])
    books = [r for ref in store.segments() if ref.channel == "book" for r in store.read(ref)]
    assert [r.raw for r in books] == [BOOK_BTC, BOOK_BTC]
    assert books[0].conn_ms < books[1].conn_ms
    assert books[0].recv_ms < books[1].conn_ms  # a segunda conexão abriu depois da mensagem

    kinds = [e["event"] for e in events(store)]
    assert kinds == ["connect", "disconnect", "connect", "stop"]
    disconnect = events(store)[1]
    assert "queda simulada" in str(disconnect["reason"])
    assert disconnect["retry_in_s"] == pytest.approx(0.01)


@pytest.mark.unit
def test_silent_connection_is_dropped_and_reopened(tmp_path: Path) -> None:
    """A conexão que não traz nada por `silence_s` é dada por morta, mesmo sem erro."""

    async def script(ws: ServerConnection, number: int) -> None:
        await _wait_subscribed(ws, exchange, 3)
        if number == 0:
            await ws.wait_closed()  # silêncio até o gravador desistir
            return
        await ws.send(BBO_BTC.decode())
        exchange.done.set()
        await ws.wait_closed()

    exchange = FakeExchange(script)
    store = SegmentStore(tmp_path)
    asyncio.run(record_against(exchange, store, ("BTC",), silence_s=0.6))

    reasons = [str(e.get("reason")) for e in events(store) if e["event"] == "disconnect"]
    assert len(reasons) == 1
    assert "sem mensagem" in reasons[0]
    assert raws(store, "BTC", "bbo") == [BBO_BTC]


@pytest.mark.unit
def test_backoff_doubles_up_to_the_cap_while_the_exchange_is_unreachable(
    tmp_path: Path,
) -> None:
    """Sem servidor na porta: 0,01, 0,02, 0,04 e daí em diante 0,04 s entre tentativas."""

    async def scenario() -> None:
        async with serve(lambda ws: ws.wait_closed(), "127.0.0.1", 0) as server:
            port = next(iter(server.sockets)).getsockname()[1]
        config = RecorderConfig(f"ws://127.0.0.1:{port}", ("BTC",), 0.05, 5.0, 0.01, 0.04)
        stop = asyncio.Event()
        task = asyncio.create_task(
            run(config, Recorder(store, ("BTC",), clock.now), clock.now, stop)
        )
        await asyncio.sleep(0.4)
        stop.set()
        await task

    store = SegmentStore(tmp_path)
    asyncio.run(scenario())
    waits = [e["retry_in_s"] for e in events(store) if e["event"] == "disconnect"]
    assert waits[:4] == pytest.approx([0.01, 0.02, 0.04, 0.04])
    assert all(e["event"] != "connect" for e in events(store))


@pytest.mark.unit
def test_segments_roll_over_at_the_hour_and_close_when_it_ends(tmp_path: Path) -> None:
    """Relógio controlado: 10:59:59.900, 11:00:00.100 e, na descarga, 12:00."""
    ten = Ms(1_791_280_800_000)  # 2026-10-06T10:00:00Z
    times = iter([ten + MS_PER_HOUR - 100, ten + MS_PER_HOUR + 100])
    store = SegmentStore(tmp_path)
    now_value = [Ms(ten)]
    recorder = Recorder(store, ("BTC",), lambda: now_value[0])

    for t in times:
        recorder.record(Ms(t), Ms(ten), BBO_BTC)
    # A primeira hora fechou ao chegar a mensagem da segunda; a segunda segue aberta.
    assert [(r.hour_ms, r.closed) for r in store.segments(include_open=True)] == [
        (ten, True),
        (ten + MS_PER_HOUR, False),
    ]
    now_value[0] = Ms(ten + 2 * MS_PER_HOUR)
    recorder.flush()  # a hora das 11h acabou: o segmento fecha sem esperar mensagem nova
    assert all(r.closed for r in store.segments(include_open=True))
    recorder.close()


@pytest.mark.unit
def test_unknown_coin_goes_to_events_untouched(tmp_path: Path) -> None:
    store = SegmentStore(tmp_path)
    recorder = Recorder(store, ("ETH",), clock.now)
    recorder.record(clock.now(), clock.now(), BBO_BTC)
    recorder.close()
    assert raws(store, *EVENTS) == [BBO_BTC]
