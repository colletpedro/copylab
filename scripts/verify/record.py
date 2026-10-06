"""Gravador descartável de WebSocket (RF-VER-04 CA-04.1 e RF-VER-01 CA-01.5).

Assina `l2Book`, `bbo` e `trades` de BTC, ETH e SOL (conexão principal) e, numa segunda
conexão, `l2Book` com `fast: true` (gravado como `l2BookFast`). Cada mensagem é gravada
**como recebida**, com o instante de recebimento local em milissegundos:

    <recv_ms>\\t<mensagem JSON bruta>\\n

um arquivo por (ativo, canal). O instante da corretora vem dentro da mensagem (`time`).
Não é o coletor: é uma régua para medir bytes e atrasos na configuração default e para
conferir se o fluxo de negócios traz os endereços das duas pontas. Somente leitura:
assina canais públicos, sem chave e sem assinatura.

Uso: `python scripts/verify/record.py [--smoke] [--minutes N] [--out DIR]`
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import IO, Any

import websockets

from common import UNIVERSE, WS_URL, iso, make_ctx, now_ms, setup_logging

#: Conexão principal: canais na configuração default. Conexão rápida: `l2Book` com `fast`.
MAIN_CHANNELS = ("l2Book", "bbo", "trades")
SILENCE_TIMEOUT_S = 30.0  # sem mensagem por tanto tempo, a conexão é tratada como morta
PING_EVERY_S = 25.0
FLUSH_EVERY_S = 5.0


def route(message: dict[str, Any], l2_name: str = "l2Book") -> tuple[str, str] | None:
    """`(ativo, canal)` de uma mensagem de dados, ou `None` para as demais.

    `l2_name` diz como chamar o canal `l2Book` desta conexão (`l2Book` ou `l2BookFast`),
    já que as duas variantes chegam com o mesmo nome de canal.
    """
    channel = message.get("channel")
    data = message.get("data")
    if channel == "l2Book" and isinstance(data, dict):
        return str(data.get("coin")), l2_name
    if channel == "bbo" and isinstance(data, dict):
        return str(data.get("coin")), "bbo"
    if channel == "trades" and isinstance(data, list) and data:
        return str(data[0].get("coin")), "trades"
    return None


class Recorder:
    def __init__(self, out_dir: Path, coins: tuple[str, ...]) -> None:
        self.out_dir = out_dir
        self.coins = coins
        out_dir.mkdir(parents=True, exist_ok=True)
        self._files: dict[tuple[str, str], IO[str]] = {}
        self._events = (out_dir / "events.tsv").open("a", encoding="utf-8")
        self._log = setup_logging()

    def event(self, kind: str, detail: str = "") -> None:
        self._events.write(f"{now_ms()}\t{kind}\t{detail}\n")
        self._events.flush()
        self._log.info("evento", kind=kind, detail=detail)

    def write(self, key: tuple[str, str], recv_ms: int, raw: str) -> None:
        handle = self._files.get(key)
        if handle is None:
            handle = (self.out_dir / f"{key[0]}.{key[1]}.tsv").open("a", encoding="utf-8")
            self._files[key] = handle
        handle.write(f"{recv_ms}\t{raw}\n")

    def flush(self) -> None:
        for handle in self._files.values():
            handle.flush()

    def close(self) -> None:
        self.flush()
        for handle in self._files.values():
            handle.close()
        self._events.close()


async def _ping(ws: Any) -> None:
    while True:
        await asyncio.sleep(PING_EVERY_S)
        await ws.send(json.dumps({"method": "ping"}))


async def _session(
    rec: Recorder, deadline: float, name: str, subs: list[dict[str, Any]], l2_name: str
) -> None:
    async with websockets.connect(WS_URL, ping_interval=None, max_size=None) as ws:
        rec.event("connect", name)
        for sub in subs:
            await ws.send(json.dumps({"method": "subscribe", "subscription": sub}))
        pinger = asyncio.create_task(_ping(ws))
        last_flush = time.monotonic()
        try:
            while time.monotonic() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), SILENCE_TIMEOUT_S)
                except TimeoutError:
                    rec.event("silence", f"{name}: >{SILENCE_TIMEOUT_S:.0f}s sem mensagem")
                    return
                recv_ms = now_ms()
                text = raw if isinstance(raw, str) else raw.decode("utf-8")
                try:
                    key = route(json.loads(text), l2_name)
                except ValueError:
                    rec.event("bad_json", text[:80])
                    continue
                if key is not None:
                    rec.write(key, recv_ms, text)
                if time.monotonic() - last_flush > FLUSH_EVERY_S:
                    rec.flush()
                    last_flush = time.monotonic()
        finally:
            pinger.cancel()


async def _keep_alive(
    rec: Recorder, deadline: float, name: str, subs: list[dict[str, Any]], l2_name: str
) -> None:
    """Mantém uma conexão de pé até o prazo, reconectando sozinha (RF-COL-02 CA-02.1)."""
    while time.monotonic() < deadline:
        try:
            await _session(rec, deadline, name, subs, l2_name)
        except (websockets.WebSocketException, OSError) as exc:
            rec.event("disconnect", f"{name}: {type(exc).__name__}: {exc}")
        if time.monotonic() < deadline:
            await asyncio.sleep(1.0)


async def run(out_dir: Path, minutes: float, coins: tuple[str, ...]) -> None:
    rec = Recorder(out_dir, coins)
    started = now_ms()
    deadline = time.monotonic() + minutes * 60
    rec.event("start", f"minutes={minutes} coins={','.join(coins)}")
    main_subs = [{"type": ch, "coin": coin} for coin in coins for ch in MAIN_CHANNELS]
    fast_subs = [{"type": "l2Book", "coin": coin, "fast": True} for coin in coins]
    try:
        await asyncio.gather(
            _keep_alive(rec, deadline, "principal", main_subs, "l2Book"),
            _keep_alive(rec, deadline, "l2Book-fast", fast_subs, "l2BookFast"),
        )
    finally:
        rec.event("end", "")
        rec.close()
    (out_dir / "DONE").write_text(f"{iso(started)} -> {iso(now_ms())}\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true", help="modo reduzido: 2 minutos")
    parser.add_argument("--minutes", type=float, default=None)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    ctx = make_ctx(args.smoke)
    minutes = args.minutes if args.minutes is not None else ctx.ws_minutes
    out = args.out or ctx.path("ws", "main", "x").parent
    asyncio.run(run(out, minutes, UNIVERSE))


if __name__ == "__main__":
    main()
