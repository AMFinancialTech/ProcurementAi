"""
estudo.py — O objeto Estudo.

É a "ficha" do estudo: uma estrutura única que vai acumulando tudo
conforme o estudo passa pelas 8 etapas. Cada etapa lê o que as anteriores
deixaram aqui e grava o seu próprio resultado.

Na prática, este objeto fica guardado no session_state do Streamlit, então
ele sobrevive enquanto você navega pelas telas do app.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Estudo:
    # --- Identificação (perguntada quando relevante, ex.: na Etapa 8) ---
    cliente: Optional[str] = None
    setor: Optional[str] = None

    # --- Etapa 1: classificação e configuração ---
    # documentos: lista de {nome, texto, tipo}; tipo = edital|proposta|baseline|fornecedor|desconhecido
    documentos: list = field(default_factory=list)
    # proponentes: agrupamento por fornecedor montado na Etapa 1 e confirmado no
    # checkpoint. Cada proponente:
    #   {"id": "P1", "fornecedor": "<nome>",
    #    "arquivos": {"tecnica": <nome|None>, "comercial": <nome|None>, "combinada": <nome|None>}}
    # É a chave que liga técnica↔comercial do MESMO fornecedor. As Etapas 4/4B/6
    # passarão a ler por aqui (camada 2, ainda não ligada). Edital e baseline NÃO
    # entram em proponentes — são o Cenário Atual (As Is).
    proponentes: list = field(default_factory=list)
    categoria: Optional[str] = None            # Serviço | Material | Commodity
    micro_categoria: Optional[str] = None      # ex.: Limpeza, Segurança, MRO...
    modelo_precificacao: Optional[str] = None  # hora-homem | por funcionário | mensal fixo | variável por consumo | TPQ

    # --- Etapa 2: cenário atual (baseline) ---
    baseline: Optional[dict] = None

    # --- Etapa 3: edital técnico (requisitos + delta de escopo vs baseline) ---
    edital: Optional[dict] = None

    # --- Etapa 4: propostas técnicas (uma entrada por fornecedor) ---
    propostas_tecnicas: list = field(default_factory=list)

    # --- Etapa 4B: extração comercial das propostas (suporte à Etapa 6) ---
    propostas_comerciais: list = field(default_factory=list)

    # --- Etapa 5: comparação técnica (one-pager) ---
    comparacao_tecnica: Optional[dict] = None

    # --- Etapa 6: equalização comercial ---
    equalizacao_comercial: Optional[dict] = None

    # --- Etapa 7: recomendações neutras ---
    recomendacoes: Optional[dict] = None

    # --- Etapa 8: estratégia da categoria (Kraljic) ---
    estrategia_categoria: Optional[dict] = None

    # --- Entradas de runtime (perguntadas a cada estudo via chatbox) ---
    taxa_desconto: Optional[float] = None
    regra_moeda: Optional[str] = None

    # --- Output transversal: Memória de Premissas e Limitações ---
    premissas: list = field(default_factory=list)   # suposições assumidas
    matches: list = field(default_factory=list)     # pareamentos de item que a IA casou
    faltantes: list = field(default_factory=list)   # documentos/dados que faltaram
    fraquezas: list = field(default_factory=list)   # limitações da análise

    # --- Controle de fluxo ---
    etapa_atual: int = 1

    # ---- Helpers da Memória de Premissas ----
    def add_premissa(self, texto: str):
        self.premissas.append(texto)

    def add_faltante(self, texto: str):
        self.faltantes.append(texto)

    def add_fraqueza(self, texto: str):
        self.fraquezas.append(texto)

    def add_match(self, texto: str):
        self.matches.append(texto)
