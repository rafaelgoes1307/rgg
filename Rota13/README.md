# Rota13 Bid Intelligence

Sistema local de análise de editais de locação de veículos para o setor público —
gera um painel executivo de decisão (GO / GO COM RESSALVAS / NO GO), não um relatório.

## Como usar

1. Instale a única dependência Python (uma vez): `pip install -r requirements.txt`
2. Execute:
   ```
   python main.py
   ```
3. O sistema sobe um servidor web local e imprime no terminal:
   - o endereço local (`http://127.0.0.1:8000`)
   - o endereço de rede (para acessar de outro dispositivo/rede, se a porta estiver liberada)
   - uma **senha de acesso** gerada na hora (ou definida por você via `ROTA13_PASSWORD`)
4. Abra o endereço no navegador, entre com a senha, e arraste o edital em PDF.
   O Dashboard aparece na mesma tela ao final da análise.

Alternativamente, você ainda pode colocar PDFs direto em `uploads/` antes de
rodar `python main.py` — eles são processados automaticamente na inicialização.

Cada análise é salva permanentemente em `historical/<ano>/<pregão>/`
(edital.pdf + dashboard.html + analise.json) e resumida no banco
`database/rota13.db`. Veja o histórico completo em `/historico` no navegador.

## Motor de extração: IA local (opcional) + regex (padrão, sempre disponível)

Por padrão, o sistema lê o edital com um motor **determinístico por regex** —
sem depender de internet ou de hardware potente, e com rastreabilidade total
(toda informação extraída cita página + trecho do PDF).

Se você tiver o [Ollama](https://ollama.com) rodando localmente
(`ollama serve` + um modelo como `qwen2.5:7b-instruct`), o sistema tenta usá-lo
primeiro para uma extração mais robusta em editais fora do padrão comum — com
o mesmo requisito de citação verificada (página + trecho conferidos contra o
texto real; citações não verificáveis são descartadas, nunca inventadas). Se a
IA estiver indisponível, lenta ou falhar, o sistema cai automaticamente para o
motor por regex sem interromper a análise. Configurável via `ROTA13_AI_MODEL`,
`ROTA13_OLLAMA_HOST` e `ROTA13_AI_NUM_CTX`.

**Nota de hardware:** modelos de 7B parâmetros exigem ~6-8GB de RAM livres;
em máquinas mais modestas prefira um modelo menor (`llama3.2:3b`) ou desative
a IA e use só o motor por regex (funciona igualmente bem e é mais rápido).

## Estrutura

- `uploads/` — cole aqui os editais em PDF (opcional; upload pelo navegador também funciona)
- `output/` — dashboard e analise.json da última execução
- `historical/` — histórico permanente de todas as análises
- `database/rota13.db` — banco SQLite (licitações, lotes, veículos, base de conhecimento)
- `knowledge/` — base de conhecimento jurídica/técnica (Lei 14.133, LC 123, acórdãos TCU, guias, etc.)
- `datasets/vehicles/` — base local de veículos usados como referência (FIPE, ficha técnica, garantia)
- `datasets/fipe/` — estrutura de snapshots da tabela FIPE (mantém os 3 últimos)
- `market/` — estrutura da Inteligência de Mercado (implementação completa em versão futura)
- `scripts/` — código do pipeline (extração, motor financeiro, motor de score, dashboard, servidor web)

## Motor financeiro (DRE)

Todo indicador financeiro parte de uma DRE explícita:

```
Receita Bruta
(-) Tributos
(-) Seguro
(-) Manutenção
(-) Pneus
(-) Administração
(-) Financeiro (só os JUROS do financiamento — o principal não é despesa contábil)
(-) Depreciação (valor residual calculado por curva de depreciação, escalada ao prazo do contrato)
(-) Custos Operacionais
= Lucro Operacional
```

ROI, Payback, TIR e VPL são calculados sobre o **fluxo de caixa** (Lucro
Operacional + Depreciação, que não é desembolso), não sobre a receita bruta —
e nunca aparecem como um número quando os dados são insuficientes: o
Dashboard mostra "Indicador não calculado por falta de informações." em vez
de arriscar um valor irreal. Se o prazo de financiamento for maior que o
prazo contratual, o sistema simula a amortização mês a mês e sinaliza o saldo
devedor remanescente ao final do contrato.

## Dashboard

Painel de decisão, dark mode, responsivo, com: Resumo Executivo (decisão
GO/GO COM RESSALVAS/NO GO com motivos, score por categoria, semáforo,
pontos fortes/fracos, riscos, oportunidades, ações recomendadas), Análise
por Lote (score, capital, receita, margem, risco, semáforo, recomendação
SIM/TALVEZ/NÃO com justificativa), Financeiro (DRE completa), Jurídico
(análise de risco com citação de página/trecho do edital, não só uma lista
de leis), Operacional (veículos com FIPE/consumo/pneu/garantia/valor
residual), checklist prático ("O que preciso fazer"), timeline do processo
licitatório, confiança da extração (% de campos identificados, pendentes e
a revisar) e um Simulador financeiro interativo que recalcula tudo em tempo
real no navegador, usando exatamente a mesma fórmula de DRE do motor em
Python.

## Limitações conhecidas

- A extração por regex é heurística: editais fora do padrão comum podem
  exigir conferência manual — por isso a seção "Confiança da extração"
  sinaliza campos pendentes ou a revisar.
- A Inteligência de Mercado (benchmark de preços entre órgãos) está
  estruturada (`market/market.db`) mas não implementada.
- A base FIPE local (`datasets/fipe/`) ainda não é preenchida
  automaticamente; a base de veículos usa valores de referência fixos.
- O servidor web usa uma senha única compartilhada (não é um sistema de
  login/multiusuário) — adequada para uso pessoal/pequena equipe, não para
  exposição pública ampla sem proteção adicional.
