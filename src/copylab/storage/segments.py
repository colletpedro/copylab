"""Segmentos brutos do coletor (design §3.4, ADR-0006 decisões 3 e 7).

O coletor grava cada mensagem como veio, e este módulo é quem sabe onde e como. Um
segmento é um arquivo por ativo, canal e hora de recebimento:

``<diretório de dados>/collector/segments/<ativo>/<canal>/<hora>.<aberto>.jsonl.gz``

``<hora>`` é o início da hora UTC em ``Ms``, e ``<aberto>`` é o instante em que o
segmento foi aberto, que distingue dois segmentos da mesma hora (o processo reiniciou no
meio dela). Enquanto está em escrita, o arquivo tem o sufixo ``.open``; ao fechar, ele é
sincronizado com o disco e renomeado.

**Registro.** Cada mensagem vira um registro ``<recebimento>\\t<conexão>\\t<n>\\t<bytes>\\n``:
o instante de recebimento em ``Ms``, o instante em que a conexão que a trouxe foi aberta
(que identifica a conexão), o tamanho da mensagem em bytes e a mensagem, intacta. O
tamanho explícito faz a leitura não depender de a mensagem não conter quebra de linha.

**Blocos.** Os registros acumulam em memória e, a cada descarga, vão para o arquivo como
um membro gzip completo, com o próprio CRC, seguido de ``fsync``. Uma queda perde no
máximo o que ainda não foi descarregado. Um segmento interrompido é lido até o último
membro íntegro (:meth:`SegmentStore.recover`), e o resto é descartado.

**Eventos.** Conexões, desconexões e as mensagens da corretora que não são de um ativo
(resposta de assinatura, ``pong``, erro) vão para a família ``_events``, no mesmo
formato, para que nenhuma mensagem recebida fique sem registro.
"""

import fcntl
import gzip
import os
import re
import zlib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from copylab.config import Settings
from copylab.exceptions import ConfigError, DataError
from copylab.logging import get_logger
from copylab.timeutil import Ms

__all__ = ["EVENTS", "Record", "SegmentRef", "SegmentStore", "SegmentWriter"]

log = get_logger(__name__)

#: Ativo e canal da família de eventos da conexão.
EVENTS: Final = ("_events", "events")

_SUFFIX: Final = ".jsonl.gz"
_OPEN: Final = ".open"
_NAME: Final = re.compile(r"(?P<hour>-?\d+)\.(?P<opened>-?\d+)\.jsonl\.gz(?P<open>\.open)?")
_PART: Final = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_@:-]*")


@dataclass(frozen=True, slots=True)
class Record:
    """Uma mensagem gravada: quando chegou, por qual conexão, e os bytes dela."""

    recv_ms: Ms
    conn_ms: Ms
    raw: bytes

    def encode(self) -> bytes:
        return b"%d\t%d\t%d\t" % (self.recv_ms, self.conn_ms, len(self.raw)) + self.raw + b"\n"


@dataclass(frozen=True, slots=True, order=True)
class SegmentRef:
    """Um segmento em disco."""

    coin: str
    channel: str
    hour_ms: Ms
    opened_ms: Ms
    closed: bool
    path: Path


def _check_part(kind: str, value: str) -> str:
    if _PART.fullmatch(value) is None:
        raise DataError(f"{kind} inválido para segmento: {value!r}.")
    return value


def _decode_records(block: bytes, where: Path) -> Iterator[Record]:
    offset = 0
    while offset < len(block):
        try:
            recv, conn, size, rest_start = _header(block, offset)
        except ValueError as exc:
            raise DataError(f"Registro malformado em {where}, byte {offset}.") from exc
        end = rest_start + size
        if end >= len(block) or block[end : end + 1] != b"\n":
            raise DataError(f"Registro sem fim em {where}, byte {offset}.")
        yield Record(Ms(recv), Ms(conn), block[rest_start:end])
        offset = end + 1


def _header(block: bytes, offset: int) -> tuple[int, int, int, int]:
    first = block.index(b"\t", offset)
    second = block.index(b"\t", first + 1)
    third = block.index(b"\t", second + 1)
    return (
        int(block[offset:first]),
        int(block[first + 1 : second]),
        int(block[second + 1 : third]),
        third + 1,
    )


def _members(data: bytes, where: Path, tolerant: bool) -> tuple[list[bytes], int]:
    """Membros gzip íntegros de ``data`` e o byte em que o último termina.

    Estrito, qualquer defeito é ``DataError``. Tolerante, a leitura para no primeiro
    membro truncado ou corrompido: é o fim de um segmento interrompido.
    """
    blocks: list[bytes] = []
    offset = 0
    while offset < len(data):
        decoder = zlib.decompressobj(wbits=31)
        try:
            block = decoder.decompress(data[offset:])
        except zlib.error as exc:
            if tolerant:
                break
            raise DataError(f"Bloco corrompido em {where}, byte {offset}.") from exc
        if not decoder.eof:
            if tolerant:
                break
            raise DataError(f"Bloco truncado em {where}, byte {offset}.")
        blocks.append(block)
        offset = len(data) - len(decoder.unused_data)
    return blocks, offset


def _fsync_dir(directory: Path) -> None:
    handle = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(handle)
    finally:
        os.close(handle)


class SegmentWriter:
    """Escreve um segmento aberto. Só o :class:`SegmentStore` cria um."""

    def __init__(self, ref: SegmentRef, closed_path: Path) -> None:
        ref.path.parent.mkdir(parents=True, exist_ok=True)
        self.ref = ref
        self._closed_path = closed_path
        self._file = ref.path.open("xb")
        self._pending: list[bytes] = []
        self.records = 0

    def append(self, record: Record) -> None:
        self._pending.append(record.encode())
        self.records += 1

    def flush(self) -> None:
        """Grava o que está pendente como um membro gzip íntegro e sincroniza o disco."""
        if not self._pending:
            return
        self._file.write(gzip.compress(b"".join(self._pending), mtime=0))
        self._file.flush()
        os.fsync(self._file.fileno())
        self._pending.clear()

    def close(self) -> SegmentRef:
        """Descarrega, fecha e renomeia para o nome de segmento fechado."""
        self.flush()
        self._file.close()
        os.replace(self.ref.path, self._closed_path)
        _fsync_dir(self._closed_path.parent)
        return SegmentRef(
            self.ref.coin,
            self.ref.channel,
            self.ref.hour_ms,
            self.ref.opened_ms,
            True,
            self._closed_path,
        )


class SegmentStore:
    """Os segmentos brutos sob o diretório de dados."""

    def __init__(self, data_dir: Path) -> None:
        if data_dir.exists() and not data_dir.is_dir():
            raise ConfigError(f"O diretório de dados {data_dir} existe e não é um diretório.")
        self._root = data_dir / "collector" / "segments"
        self._lock_path = data_dir / "collector" / "recorder.lock"

    @classmethod
    def from_settings(cls, settings: Settings) -> "SegmentStore":
        if settings.data_dir is None:
            raise ConfigError(
                "COPYLAB_DATA_DIR não está definido. Aponte-o para o diretório de dados, "
                "fora do git (ver .env.example)."
            )
        return cls(settings.data_dir)

    def _paths(self, coin: str, channel: str, hour_ms: Ms, opened_ms: Ms) -> tuple[Path, Path]:
        folder = self._root / _check_part("Ativo", coin) / _check_part("Canal", channel)
        closed = folder / f"{hour_ms}.{opened_ms}{_SUFFIX}"
        return closed.with_name(closed.name + _OPEN), closed

    def open_writer(self, coin: str, channel: str, hour_ms: Ms, opened_ms: Ms) -> SegmentWriter:
        """Abre um segmento novo. Nunca acrescenta a um segmento que já existe."""
        open_path, closed_path = self._paths(coin, channel, hour_ms, opened_ms)
        if closed_path.exists():
            raise DataError(f"Segmento {closed_path} já existe.")
        ref = SegmentRef(coin, channel, hour_ms, opened_ms, False, open_path)
        return SegmentWriter(ref, closed_path)

    def segments(self, *, include_open: bool = False) -> list[SegmentRef]:
        """Segmentos em disco, em ordem de ativo, canal, hora e abertura."""
        if not self._root.is_dir():
            return []
        found = []
        for path in self._root.glob(f"*/*/*{_SUFFIX}*"):
            match = _NAME.fullmatch(path.name)
            if match is None:
                continue
            closed = match["open"] is None
            if closed or include_open:
                found.append(
                    SegmentRef(
                        path.parent.parent.name,
                        path.parent.name,
                        Ms(int(match["hour"])),
                        Ms(int(match["opened"])),
                        closed,
                        path,
                    )
                )
        return sorted(found)

    def read(self, ref: SegmentRef) -> Iterator[Record]:
        """Registros do segmento.

        Fechado, a leitura é estrita: qualquer defeito é ``DataError``. Aberto (em escrita
        agora, ou deixado por uma queda), ela vai até o último bloco íntegro.
        """
        blocks, _ = _members(ref.path.read_bytes(), ref.path, tolerant=not ref.closed)
        for block in blocks:
            yield from _decode_records(block, ref.path)

    def recover(self) -> list[SegmentRef]:
        """Fecha os segmentos deixados abertos por uma queda, até o último bloco íntegro.

        Só pode rodar com a trava do gravador (:meth:`exclusive`): sem ela, fecharia o
        segmento que um gravador vivo está escrevendo.
        """
        recovered = []
        for ref in self.segments(include_open=True):
            if ref.closed:
                continue
            _, valid = _members(ref.path.read_bytes(), ref.path, tolerant=True)
            dropped = ref.path.stat().st_size - valid
            _, closed_path = self._paths(ref.coin, ref.channel, ref.hour_ms, ref.opened_ms)
            if valid == 0:
                ref.path.unlink()
            else:
                os.truncate(ref.path, valid)
                os.replace(ref.path, closed_path)
                _fsync_dir(closed_path.parent)
                recovered.append(
                    SegmentRef(ref.coin, ref.channel, ref.hour_ms, ref.opened_ms, True, closed_path)
                )
            log.warning(
                "collector.segment_recovered",
                segment=str(closed_path),
                kept_bytes=valid,
                dropped_bytes=dropped,
            )
        return recovered

    def delete(self, ref: SegmentRef) -> None:
        if not ref.closed:
            raise DataError(f"Segmento aberto não é apagado: {ref.path}.")
        ref.path.unlink()

    def disk_bytes(self) -> int:
        """Bytes ocupados por todos os segmentos, abertos e fechados."""
        return sum(ref.path.stat().st_size for ref in self.segments(include_open=True))

    @contextmanager
    def exclusive(self) -> Iterator[None]:
        """Trava de um gravador só por diretório de dados.

        Raises:
            ConfigError: se outro processo já tem a trava.
        """
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock_path.open("a+") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ConfigError(
                    f"Outro gravador já está rodando sobre {self._lock_path.parent}."
                ) from exc
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
