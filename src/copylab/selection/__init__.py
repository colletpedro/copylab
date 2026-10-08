"""Seleção pré-registrada de carteiras, isolada no tempo (RF-SEL).

Lógica pura (design §2.1): lê por ``copylab.ports``, não importa armazenamento, rede nem
relógio, e devolve objetos. Por enquanto, só o que a ingestão precisa saber: o pool de
candidatas (``pool``, T-060, adiantada do Bloco F). O resto chega com o Bloco F.
"""
