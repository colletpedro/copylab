"""Executa a verificação de dados (§4.1) inteira: RF-VER-01 a RF-VER-04 e o relatório.

    python scripts/verify/run.py            # execução completa (~1 a 2 h)
    python scripts/verify/run.py --smoke    # modo reduzido: 3 carteiras, 2 min de gravação, 1 dia

Ordem: o gravador de WebSocket sobe em segundo plano (processo próprio) e as medidas de REST
rodam enquanto ele grava; depois vêm o proxy da Binance, a espera do gravador, o orçamento
(v04) e o relatório.

**Retomável.** Cada etapa grava `results/<etapa>.json` e é pulada se ele já existe (use
`--force` para refazer; os dados brutos em cache são reaproveitados). Carteiras, papéis e
arquivos da Binance têm cache por arquivo. Se a sessão cair, rode o mesmo comando de novo.
O progresso corrente está em `data/verify/progress.json` e `data/verify/run_state.json`.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import report
import v01_schema
import v02_universe
import v03_proxy
import v04_budget
from common import (
    Ctx,
    HlClient,
    RateBudget,
    iso,
    make_ctx,
    now_ms,
    read_json,
    setup_logging,
    write_json,
)

HERE = Path(__file__).resolve().parent


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def start_recorder(ctx: Ctx, log: Any) -> subprocess.Popen[bytes] | int | None:
    """Sobe o gravador, a menos que uma gravação completa já exista ou esteja rodando."""
    ws_dir = ctx.path("ws", "main", "x").parent
    if (ws_dir / "DONE").exists():
        log.info("gravação já concluída; reaproveitando", dir=str(ws_dir))
        return None
    pid_file = ws_dir / "recorder.pid"
    if pid_file.exists():
        pid = int(pid_file.read_text())
        if _alive(pid):
            log.info("gravador já está rodando; aguardando", pid=pid)
            return pid
    if any(ws_dir.glob("*.tsv")):
        partial = ws_dir.with_name(f"main.partial-{now_ms()}")
        ws_dir.rename(partial)
        log.warning("gravação anterior incompleta; movida", para=str(partial))
        ws_dir.mkdir(parents=True)
    cmd = [
        sys.executable,
        str(HERE / "record.py"),
        "--out",
        str(ws_dir),
        "--minutes",
        str(ctx.ws_minutes),
    ]
    out = (ws_dir / "recorder.log").open("ab")
    proc = subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT)
    pid_file.write_text(str(proc.pid))
    log.info("gravador iniciado", pid=proc.pid, minutos=ctx.ws_minutes)
    return proc


def wait_recorder(ctx: Ctx, handle: subprocess.Popen[bytes] | int | None, log: Any) -> None:
    ws_dir = ctx.path("ws", "main", "x").parent
    while handle is not None and not (ws_dir / "DONE").exists():
        if isinstance(handle, subprocess.Popen):
            if handle.poll() is not None and not (ws_dir / "DONE").exists():
                log.error("gravador terminou sem DONE", code=handle.returncode)
                return
        elif not _alive(handle):
            log.error("gravador morreu sem DONE", pid=handle)
            return
        log.info("aguardando o gravador terminar")
        time.sleep(30)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--smoke", action="store_true", help="modo reduzido")
    parser.add_argument(
        "--force", action="store_true", help="refaz as etapas, reaproveitando o cache bruto"
    )
    parser.add_argument("--skip-record", action="store_true", help="não sobe o gravador")
    args = parser.parse_args()

    ctx = make_ctx(args.smoke)
    log = setup_logging()
    state_path = ctx.path("run_state.json")
    state: dict[str, Any] = read_json(state_path) if state_path.exists() else {"runs": []}
    state["runs"].append({"started": iso(now_ms()), "smoke": args.smoke})
    write_json(state_path, state)

    recorder = None if args.skip_record else start_recorder(ctx, log)

    client = HlClient(RateBudget())

    def step(name: str, fn: Any) -> None:
        result_file = ctx.path("results", f"{name}.json")
        if result_file.exists() and not args.force:
            log.info("etapa já concluída; pulando", etapa=name)
            return
        log.info("etapa", etapa=name)
        t0 = time.monotonic()
        fn()
        log.info("etapa concluída", etapa=name, segundos=round(time.monotonic() - t0))

    step("v01", lambda: v01_schema.run(ctx, client))
    step("v02", lambda: v02_universe.run(ctx, client))
    step("v03", lambda: v03_proxy.run(ctx))
    wait_recorder(ctx, recorder, log)
    step("v04", lambda: v04_budget.run(ctx))

    state["runs"][-1]["finished"] = iso(now_ms())
    write_json(state_path, state)
    path = report.build(ctx)
    log.info("relatório gravado", arquivo=str(path))


if __name__ == "__main__":
    main()
