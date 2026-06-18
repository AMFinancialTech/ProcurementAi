"""
pipeline.py — A espinha do processo: as 8 etapas, em ordem.

Aqui ficam declaradas as 8 etapas na sequência em que rodam, e quais delas
têm checkpoint (param pra você confirmar antes de seguir).

Por enquanto isto é só a DECLARAÇÃO da ordem. A lógica de cada etapa entra
nos módulos etapa1.py ... etapa8.py conforme a gente constrói — e o app vai
consultar esta lista pra saber em que ponto do processo está.
"""

# Cada etapa: número, chave interna, título exibido, e se pausa pra confirmação humana.
# checkpoint=True significa que o app para e pergunta algo a você antes de avançar:
#   Etapa 1 → confirmar a classificação dos documentos
#   Etapa 6 → informar taxa de desconto e regra de moeda
#   Etapa 8 → informar (ou mandar pesquisar) o risco de suprimento da Kraljic
ETAPAS = [
    {"n": 1, "chave": "classificacao",      "titulo": "Classificação dos Documentos", "checkpoint": True},
    {"n": 2, "chave": "baseline",           "titulo": "Cenário Atual (Baseline)",      "checkpoint": False},
    {"n": 3, "chave": "edital_tecnico",     "titulo": "Edital Técnico",                "checkpoint": False},
    {"n": 4, "chave": "propostas_tecnicas", "titulo": "Propostas Técnicas",            "checkpoint": False},
    {"n": 5, "chave": "comparacao_tecnica", "titulo": "Comparação Técnica",            "checkpoint": False},
    {"n": 6, "chave": "equalizacao",        "titulo": "Equalização Comercial",         "checkpoint": True},
    {"n": 7, "chave": "recomendacoes",      "titulo": "Recomendações (neutras)",       "checkpoint": False},
    {"n": 8, "chave": "estrategia",         "titulo": "Estratégia da Categoria",       "checkpoint": True},
]


def etapa_por_numero(n: int):
    """Devolve a definição de uma etapa pelo número (ou None)."""
    for e in ETAPAS:
        if e["n"] == n:
            return e
    return None


def total_etapas() -> int:
    """Quantas etapas o processo tem."""
    return len(ETAPAS)
