---
titulo: Engenharia Financeira Aplicada à Locação de Veículos
categoria: manual
palavras_chave: roi, payback, tir, vpl, capital, financiamento, residual, fluxo de caixa
fonte: Metodologia interna Rota13 — consolidação de práticas de locadoras de frota
---

## Resumo
A viabilidade de um contrato de locação de veículos ao setor público depende
de cinco variáveis centrais: capital investido (entrada + custo de aquisição),
receita mensal contratada, custos recorrentes (financiamento, seguro,
manutenção), valor residual do veículo ao final do contrato, e o prazo
contratual. O cruzamento dessas variáveis gera ROI, payback, TIR e VPL.

## Aplicação Prática
O Dashboard calcula automaticamente, por lote e de forma consolidada:
- **Capital investido**: entrada paga na aquisição de cada veículo.
- **ROI**: retorno total sobre o capital investido ao longo do contrato.
- **Payback**: tempo (em meses) para o fluxo de caixa líquido cobrir o
  capital investido.
- **TIR**: taxa interna de retorno mensal/anual do fluxo de caixa do lote.
- **VPL**: valor presente líquido descontado pela taxa de financiamento.
Use o simulador do Dashboard para testar cenários (mais desconto do
fabricante, menos entrada, prazo de financiamento maior) e ver o impacto
imediato nesses indicadores.

## Pontos Importantes
- Payback maior que o prazo contratual é sinal de alerta grave (risco alto).
- TIR abaixo da taxa de financiamento indica que o contrato destrói valor.
- Valor residual subestimado penaliza o ROI; superestimado é otimismo de
  risco — use sempre a tabela FIPE como referência conservadora.
- Reserva técnica (sugerida em 10% do custo total) protege contra
  imprevistos (sinistros não cobertos, atraso de pagamento do órgão).

## Fonte Oficial
Metodologia interna Rota13, baseada em práticas de mercado de locação de frotas.
