"""Seleção pré-registrada de carteiras, isolada no tempo (RF-SEL).

Lógica pura (design §2.1): lê por ``copylab.ports``, não importa armazenamento, rede nem
relógio, e devolve objetos. Por enquanto, só o que a ingestão precisa saber, adiantado do
Bloco F: o pool de candidatas (``pool``, T-060) e a ordenação dos ativos candidatos por
notional (``assets``, a primeira metade de T-061). O resto chega com o Bloco F.
"""
