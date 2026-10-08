"""Ingestão de leaderboard, fills, funding, metadados e preço proxy (RF-ING; Bloco B).

``budget`` e ``provider`` falam com a API de informação, somente leitura; ``fake`` é o
provedor falso da suíte offline. Os demais módulos transformam respostas em tabelas e as
entregam a ``copylab.storage``: a ingestão não grava por conta própria (design §2.1).
"""
