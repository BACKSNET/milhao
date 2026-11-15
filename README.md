# Milhão.

Site de carteira de ações e FIIs da B3, versão 1, com custo zero.

- **Site:** um arquivo só (`index.html`), hospedado de graça no GitHub Pages.
- **Dados:** um robô em Python (`etl/milhao_dados.py`) baixa todo dia os arquivos públicos da B3 e da CVM, calcula os indicadores e grava os JSON em `data/`.
- **Carteiras:** ficam salvas no navegador de cada cliente, com exportação e restauração de backup.

## Como colocar no ar (uma vez, uns 15 minutos)

1. Crie uma conta no GitHub, se ainda não tiver.
2. Crie um repositório **público** chamado `milhao` (público é o que deixa o GitHub Actions e o Pages de graça).
3. No repositório, clique em "Add file" → "Upload files" e arraste o conteúdo desta pasta (`index.html`, `README.md`, `.gitignore` e as pastas `etl` e `tests`). Clique em "Commit changes".
4. A pasta `.github` costuma ficar escondida no computador e não sobe arrastando. Crie o arquivo pelo próprio site: "Add file" → "Create new file", digite no nome `.github/workflows/atualizar-dados.yml`, cole o conteúdo do arquivo de mesmo nome deste pacote e clique em "Commit changes".
5. No repositório, vá em **Settings → Pages** e, em "Source", escolha **GitHub Actions**.
6. Vá em **Actions**, abra "Atualizar dados e publicar" e clique em **Run workflow**. A primeira rodada leva de 10 a 25 minutos, porque baixa 5 anos de cotações.
7. Quando terminar, o endereço do site aparece no resumo da execução, no formato `https://SEU-USUARIO.github.io/milhao/`.

Depois disso o robô roda sozinho de segunda a sexta, às 20h30 de Brasília.

Se a execução falhar, abra o passo com o X vermelho em Actions, copie o erro e mande para o Claude.

## Versão de arquivo único

`python etl/montar_arquivo_unico.py` gera `milhao.html` com os dados embutidos. Esse arquivo abre com dois cliques, sem servidor nem internet (só a fonte da marca precisa de internet). Serve para testar ou mostrar o site para alguém.

## Fontes dos dados

| Dado | Fonte | Arquivo |
| --- | --- | --- |
| Cotações diárias (fechamento) | B3, Séries Históricas | `COTAHIST_AAAA.ZIP` |
| DRE, balanço, ações em circulação | CVM Dados Abertos | DFP (anual) e ITR (trimestral) |
| Ticker, nome e setor da empresa | CVM Dados Abertos | FCA |
| Valor patrimonial, cotistas e segmento dos FIIs | CVM Dados Abertos | Informe mensal de FII |
| Dividendos, JCP, rendimentos, desdobramentos | B3, página de empresas listadas | consulta por emissor |

Se uma fonte falhar num dia, o robô segue com as outras e registra o aviso em `data/meta.json`.

## Rodar no próprio computador

```bash
pip install pandas requests
python etl/milhao_dados.py --saida data      # baixa tudo e gera data/
python -m http.server 8000                   # abre em http://localhost:8000
```

Sem internet, dá para testar com empresas fictícias:

```bash
python tests/gerar_fixtures.py
python etl/milhao_dados.py --saida data --fonte-local tests/fixtures
```

## O que conferir na primeira rodada real

O robô foi testado com arquivos de exemplo nos formatos oficiais, mas ainda não com os arquivos reais. Na primeira execução, confira:

- se `data/meta.json` tem avisos;
- três ou quatro ações conhecidas contra outra fonte (P/L, DY, ROE);
- uma ação que teve desdobramento recente: o gráfico não pode ter um degrau no dia do evento;
- os bancos: a DRE deles tem outra estrutura, então margens e Ebit podem sair estranhos.

## Limites da versão 1

- Cotação com um dia de atraso (fechamento do pregão anterior).
- A carteira fica no navegador: trocou de computador, use "Exportar backup" e "Restaurar backup".
- Sem conexão automática com a B3; o cliente importa a planilha de Negociação da Área do Investidor.
- Antes de divulgar o site, confirme com a B3 qual licença cobre a exibição dos dados de cotação.
