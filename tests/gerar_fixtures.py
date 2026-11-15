#!/usr/bin/env python3
"""
Gera arquivos de teste nos mesmos formatos das fontes oficiais (COTAHIST da B3,
DFP/ITR/FCA e informe de FII da CVM, proventos da B3), com empresas FICTÍCIAS.

Serve para testar o robô sem internet e para a prévia do site.
Todos os tickers começam com Y para não colidir com ativos reais.
"""
import csv
import datetime as dt
import io
import json
import random
import zipfile
from pathlib import Path

random.seed(7)
HOJE = dt.date.today()
OUT = Path(__file__).parent / "fixtures"
OUT.mkdir(exist_ok=True)

EMPRESAS = [
    # ticker, nome, setor, receita base (R$ mi), margem líquida, crescimento a.a., payout, P/L alvo
    ("YBRA3", "Brasa Energia S.A.", "Energia Elétrica", 9000, 0.22, 0.06, 0.75, 7),
    ("YENE3", "Solaris Energia S.A.", "Energia Elétrica", 4200, 0.15, 0.12, 0.35, 12),
    ("YBAN4", "Banco Horizonte S.A.", "Bancos", 30000, 0.18, 0.08, 0.45, 7),
    ("YSEG3", "Âncora Seguros S.A.", "Seguradoras", 8000, 0.14, 0.07, 0.70, 9),
    ("YMIN3", "Mineração Pico S.A.", "Extração Mineral", 52000, 0.25, 0.03, 0.55, 6),
    ("YSID4", "Siderúrgica Ferro Forte S.A.", "Metalurgia e Siderurgia", 18000, 0.06, -0.02, 0.30, 10),
    ("YVAR3", "Varejo Aurora S.A.", "Comércio (Atacado e Varejo)", 12000, 0.03, 0.10, 0.10, 22),
    ("YSAN3", "Saneamento Rio Claro S.A.", "Saneamento, Serv. Água e Gás", 6500, 0.20, 0.07, 0.50, 9),
    ("YTEL3", "Telecom Sul S.A.", "Telecomunicações", 21000, 0.09, 0.02, 0.90, 14),
    ("YFRI3", "Frigorífico Pampa S.A.", "Alimentos", 38000, 0.04, 0.05, 0.25, 8),
    ("YLOG3", "Logística Vale Verde S.A.", "Serviços Transporte e Logística", 5200, 0.07, 0.11, 0.25, 15),
    ("YSOF3", "Lume Software S.A.", "Comunicação e Informática", 1900, 0.16, 0.18, 0.30, 25),
    ("YCON3", "Construtora Alto Padrão S.A.", "Construção Civil, Mat. Constr. e Decoração", 3600, 0.11, 0.09, 0.40, 8),
    ("YPAP4", "Papel Norte S.A.", "Papel e Celulose", 14000, 0.19, 0.04, 0.40, 9),
    ("YFAR3", "Farmácia Bem Estar S.A.", "Farmacêutico e Higiene", 16000, 0.035, 0.13, 0.25, 30),
    ("YAGR3", "Agro Cerrado S.A.", "Agricultura (Açúcar, Álcool e Cana)", 7000, 0.12, 0.05, 0.35, 8),
    ("YEDU3", "Educação Saber S.A.", "Educação", 2800, -0.02, -0.04, 0.0, 0),
    ("YCAF3", "Café Serrano S.A.", "Alimentos", 2100, 0.08, 0.06, 0.40, 12),
]
FIIS = [
    # ticker, nome, segmento, VP/cota, P/VP, DY a.a.
    ("YLGS11", "Fundo Logístico Horizonte", "Logística", 105.0, 0.97, 0.090),
    ("YREC11", "Fundo Recebíveis Âncora", "Títulos e Val. Mob.", 9.8, 1.02, 0.128),
    ("YSHO11", "Fundo Shoppings Aurora", "Shoppings", 92.0, 0.85, 0.088),
    ("YLAJ11", "Fundo Lajes Corporativas Centro", "Lajes Corporativas", 140.0, 0.62, 0.105),
    ("YHIB11", "Fundo Híbrido Pampa", "Híbrido", 98.0, 0.93, 0.110),
    ("YRND11", "Fundo Renda Urbana Sul", "Varejo", 88.0, 0.91, 0.095),
]
SPLIT = ("YVAR3", HOJE - dt.timedelta(days=420))  # desdobramento 1:2 para testar o ajuste


def dias_uteis(ini, fim):
    d = ini
    while d <= fim:
        if d.weekday() < 5:
            yield d
        d += dt.timedelta(days=1)


def isin(tk):
    return f"BR{tk[:4]}{'CTF' if tk.endswith('11') else 'ACN'}{'OR' if tk.endswith('3') else 'PR'}0"[:12]


def linha_cotahist(d, tk, nome, especi, bdi, preco, vol, cod_isin):
    p = lambda v: f"{round(v * 100):013d}"  # noqa: E731
    ln = ("01" + d.strftime("%Y%m%d") + bdi + tk.ljust(12) + "010" + nome[:12].ljust(12)
          + especi.ljust(10) + "   " + "R$  " + p(preco * 0.995) + p(preco * 1.01) + p(preco * 0.985)
          + p(preco) + p(preco) + p(preco * 0.999) + p(preco * 1.001) + f"{random.randint(500, 20000):05d}"
          + f"{int(vol / preco):018d}" + f"{round(vol * 100):018d}" + "0" * 13 + "0" + "99991231"
          + "0000001" + "0" * 13 + cod_isin.ljust(12) + "100")
    assert len(ln) == 245, len(ln)
    return ln


# ---------- fundamentos fictícios por empresa ----------
anos = list(range(HOJE.year - 7, HOJE.year))
fund = {}
for i, (tk, nome, setor, rec0, ml, cres, payout, pl_alvo) in enumerate(EMPRESAS):
    acoes = random.choice([0.4, 0.8, 1.2, 2.5, 5.0]) * 1e9
    rec = {}
    for k, a in enumerate(anos):
        rec[a] = rec0 * 1e6 * (1 + cres) ** k * random.uniform(0.95, 1.05)
    luc = {a: rec[a] * ml * random.uniform(0.85, 1.15) for a in anos}
    if tk == "YEDU3":
        luc[anos[-3]] = rec[anos[-3]] * 0.04
    pl_cont = {a: luc[a] * random.uniform(5, 9) / max(ml, 0.03) * ml for a in anos}
    fund[tk] = dict(nome=nome, setor=setor, acoes=acoes, rec=rec, luc=luc, ml=ml, payout=payout,
                    pl_alvo=pl_alvo or 15, cvm=f"{(i + 1) * 137:06d}",
                    cnpj=f"{10 + i:02d}.{100 + i:03d}.{200 + i:03d}/0001-{10 + i:02d}",
                    pat={a: luc[a] / random.uniform(0.08, 0.22) if luc[a] > 0 else rec[a] * 0.5 for a in anos})

# ---------- COTAHIST ----------
precos = {}
for tk, f in fund.items():
    lpa = f["luc"][anos[-1]] / f["acoes"]
    alvo = max(lpa * f["pl_alvo"], 3.0)
    precos[tk] = (alvo * random.uniform(0.6, 0.9), alvo, f["rec"][anos[-1]] * random.uniform(0.0004, 0.002))
for tk, nome, seg, vp, pvp, dy in FIIS:
    precos[tk] = (vp * pvp * random.uniform(0.9, 1.1), vp * pvp, random.uniform(3e6, 3e7))

por_ano = {a: [] for a in range(HOJE.year - 5, HOJE.year + 1)}
ultimo = HOJE - dt.timedelta(days=1)
while ultimo.weekday() >= 5:
    ultimo -= dt.timedelta(days=1)
ultimo_pregao = ultimo
for tk, (p0, alvo, vol) in precos.items():
    dias = list(dias_uteis(dt.date(HOJE.year - 5, 1, 2), ultimo_pregao))
    deriva = (alvo / p0) ** (1 / len(dias))
    p = p0
    fii = tk.endswith("11")
    nome = (fund[tk]["nome"] if tk in fund else dict((x[0], x[1]) for x in FIIS)[tk]).upper()
    for d in dias:
        p *= deriva * random.gauss(1, 0.008 if fii else 0.018)
        p = max(p, 0.5)
        bruto = p * (2 if (tk == SPLIT[0] and d <= SPLIT[1]) else 1)
        por_ano[d.year].append(linha_cotahist(d, tk, nome, "CI" if fii else ("ON NM" if tk.endswith("3") else "PN N1"),
                                              "12" if fii else "02", bruto, vol * random.uniform(0.6, 1.4), isin(tk)))
for a, linhas in por_ano.items():
    corpo = "00COTAHIST.%d BOVESPA %s\n" % (a, HOJE.strftime("%Y%m%d")) + "\n".join(linhas) + "\n99COTAHIST\n"
    with zipfile.ZipFile(OUT / f"COTAHIST_A{a}.ZIP", "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"COTAHIST_A{a}.TXT", corpo.encode("latin-1"))


# ---------- CVM: helpers ----------
def csv_bytes(cab, linhas):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\n")
    w.writerow(cab)
    w.writerows(linhas)
    return buf.getvalue().encode("latin-1")


CAB_DRE = ["CNPJ_CIA", "DT_REFER", "VERSAO", "DENOM_CIA", "CD_CVM", "GRUPO_DFP", "MOEDA", "ESCALA_MOEDA",
           "ORDEM_EXERC", "DT_INI_EXERC", "DT_FIM_EXERC", "CD_CONTA", "DS_CONTA", "VL_CONTA", "ST_CONTA_FIXA"]
CAB_BAL = [c for c in CAB_DRE if c != "DT_INI_EXERC"]


def contas_dre(f, a, frac=1.0):
    rec = f["rec"][a] * frac
    luc = f["luc"][a] * frac
    bruto = rec * min(0.25 + f["ml"] * 1.5, 0.7)
    ebit = luc * 1.45 if luc > 0 else luc * 0.7
    return [("3.01", "Receita de Venda de Bens e/ou Serviços", rec),
            ("3.03", "Resultado Bruto", bruto),
            ("3.05", "Resultado Antes do Resultado Financeiro e dos Tributos", ebit),
            ("3.11", "Lucro/Prejuízo Consolidado do Período", luc)]


def contas_bal(f, a):
    pat = f["pat"][a]
    ativo = pat * random.uniform(1.8, 3.2)
    ac = ativo * random.uniform(0.25, 0.45)
    pc = ac * random.uniform(0.55, 1.1)
    divida = (ativo - pat) * random.uniform(0.3, 0.6)
    caixa = ac * random.uniform(0.2, 0.5)
    bpa = [("1", "Ativo Total", ativo), ("1.01", "Ativo Circulante", ac),
           ("1.01.01", "Caixa e Equivalentes de Caixa", caixa * 0.6),
           ("1.01.02", "Aplicações Financeiras", caixa * 0.4)]
    bpp = [("2", "Passivo Total", ativo), ("2.01", "Passivo Circulante", pc),
           ("2.01.04", "Empréstimos e Financiamentos", divida * 0.3),
           ("2.02", "Passivo Não Circulante", ativo - pat - pc),
           ("2.02.01", "Empréstimos e Financiamentos", divida * 0.7),
           ("2.03", "Patrimônio Líquido Consolidado", pat)]
    return bpa, bpp


def linha(f, ref, ordem, ini, fim, cod, ds, vl, dre=True):
    base = [f["cnpj"], ref, "1", f["nome"], f["cvm"], "DF Consolidado", "REAL", "MIL", ordem]
    return base + ([ini] if dre else []) + [fim, cod, ds, f"{vl / 1000:.2f}", "S"]


def escrever_zip(nome, arquivos):
    with zipfile.ZipFile(OUT / nome, "w", zipfile.ZIP_DEFLATED) as z:
        for n, b in arquivos.items():
            z.writestr(n, b)


CAB_CAP = ["CNPJ_Companhia", "Data_Referencia", "Versao", "Nome_Empresarial",
           "Quantidade_Acoes_Ordinarias_Capital_Integralizado", "Quantidade_Acoes_Preferenciais_Capital_Integralizado",
           "Quantidade_Total_Acoes_Capital_Integralizado", "Quantidade_Total_Acoes_Tesouro"]

# DFP: um arquivo por ano, com ÚLTIMO e PENÚLTIMO
for a in anos[1:]:
    dre, bpa, bpp, dfc, cap = [], [], [], [], []
    for tk, f in fund.items():
        ref = f"{a}-12-31"
        for ordem, ano in (("ÚLTIMO", a), ("PENÚLTIMO", a - 1)):
            for cod, ds, vl in contas_dre(f, ano):
                dre.append(linha(f, ref, ordem, f"{ano}-01-01", f"{ano}-12-31", cod, ds, vl))
            pa, pp = contas_bal(f, ano)
            bpa += [linha(f, ref, ordem, None, f"{ano}-12-31", c, d, v, dre=False) for c, d, v in pa]
            bpp += [linha(f, ref, ordem, None, f"{ano}-12-31", c, d, v, dre=False) for c, d, v in pp]
        dfc.append(linha(f, ref, "ÚLTIMO", f"{a}-01-01", f"{a}-12-31", "6.01.01.02", "Depreciação e amortização",
                         f["rec"][a] * 0.04))
        cap.append([f["cnpj"], ref, "1", f["nome"], int(f["acoes"] * 0.6), int(f["acoes"] * 0.4), int(f["acoes"]),
                    int(f["acoes"] * 0.01)])
    escrever_zip(f"dfp_cia_aberta_{a}.zip", {
        f"dfp_cia_aberta_DRE_con_{a}.csv": csv_bytes(CAB_DRE, dre),
        f"dfp_cia_aberta_BPA_con_{a}.csv": csv_bytes(CAB_BAL, bpa),
        f"dfp_cia_aberta_BPP_con_{a}.csv": csv_bytes(CAB_BAL, bpp),
        f"dfp_cia_aberta_DFC_MI_con_{a}.csv": csv_bytes(CAB_DRE, dfc),
        f"dfp_cia_aberta_composicao_capital_{a}.csv": csv_bytes(CAB_CAP, cap),
    })

# ITR do ano atual: trimestres já encerrados, acumulado no ano (ÚLTIMO) e mesmo período do ano anterior (PENÚLTIMO)
tri = [m for m in (3, 6, 9) if dt.date(HOJE.year, m, 28) + dt.timedelta(days=45) < HOJE]
ano_atual = HOJE.year
for tk, f in fund.items():
    f["rec"][ano_atual] = f["rec"][anos[-1]] * (1 + random.uniform(-0.03, 0.12))
    f["luc"][ano_atual] = f["luc"][anos[-1]] * (1 + random.uniform(-0.1, 0.15))
    f["pat"][ano_atual] = f["pat"][anos[-1]] * 1.04
dre, bpa, bpp, cap = [], [], [], []
for tk, f in fund.items():
    for m in tri:
        fim = dt.date(ano_atual, m, 30 if m in (6, 9) else 31)
        frac = m / 12
        ref = fim.isoformat()
        for ordem, ano in (("ÚLTIMO", ano_atual), ("PENÚLTIMO", ano_atual - 1)):
            for cod, ds, vl in contas_dre(f, ano, frac):
                dre.append(linha(f, ref, ordem, f"{ano}-01-01", fim.replace(year=ano).isoformat(), cod, ds, vl))
        pa, pp = contas_bal(f, ano_atual)
        bpa += [linha(f, ref, "ÚLTIMO", None, ref, c, d, v, dre=False) for c, d, v in pa]
        bpp += [linha(f, ref, "ÚLTIMO", None, ref, c, d, v, dre=False) for c, d, v in pp]
    cap.append([f["cnpj"], ref, "1", f["nome"], int(f["acoes"] * 0.6), int(f["acoes"] * 0.4), int(f["acoes"]),
                int(f["acoes"] * 0.01)])
escrever_zip(f"itr_cia_aberta_{ano_atual}.zip", {
    f"itr_cia_aberta_DRE_con_{ano_atual}.csv": csv_bytes(CAB_DRE, dre),
    f"itr_cia_aberta_BPA_con_{ano_atual}.csv": csv_bytes(CAB_BAL, bpa),
    f"itr_cia_aberta_BPP_con_{ano_atual}.csv": csv_bytes(CAB_BAL, bpp),
    f"itr_cia_aberta_composicao_capital_{ano_atual}.csv": csv_bytes(CAB_CAP, cap),
})

# FCA
vm_cab = ["CNPJ_Companhia", "Data_Referencia", "Versao", "Nome_Empresarial", "Valor_Mobiliario", "Codigo_Negociacao",
          "Mercado", "Segmento"]
geral_cab = ["CNPJ_Companhia", "Data_Referencia", "Versao", "Nome_Empresarial", "Codigo_CVM", "Setor_Atividade"]
vm = [[f["cnpj"], f"{HOJE.year}-01-01", "1", f["nome"], "Ações Ordinárias", tk, "Bolsa", "Novo Mercado"]
      for tk, f in fund.items()]
ge = [[f["cnpj"], f"{HOJE.year}-01-01", "1", f["nome"], f["cvm"], f["setor"]] for f in fund.values()]
escrever_zip(f"fca_cia_aberta_{HOJE.year}.zip", {
    f"fca_cia_aberta_valor_mobiliario_{HOJE.year}.csv": csv_bytes(vm_cab, vm),
    f"fca_cia_aberta_geral_{HOJE.year}.csv": csv_bytes(geral_cab, ge),
})

# Informe mensal de FII
g_cab = ["CNPJ_Fundo_Classe", "Data_Referencia", "Versao", "Nome_Fundo_Classe", "Codigo_ISIN", "Segmento_Atuacao",
         "Mandato", "Tipo_Gestao", "Publico_Alvo"]
c_cab = ["CNPJ_Fundo_Classe", "Data_Referencia", "Versao", "Total_Numero_Cotistas", "Patrimonio_Liquido",
         "Cotas_Emitidas", "Valor_Patrimonial_Cotas", "Percentual_Despesas_Taxa_Administracao",
         "Percentual_Dividend_Yield_Mes"]
for a in (HOJE.year - 1, HOJE.year):
    gl, cl = [], []
    for i, (tk, nome, seg, vp, pvp, dy) in enumerate(FIIS):
        cnpj = f"{40 + i:02d}.{500 + i:03d}.{600 + i:03d}/0001-{20 + i:02d}"
        cotas = random.randint(5, 80) * 1e6
        for m in range(1, 13):
            ref = dt.date(a, m, 1)
            if ref >= HOJE.replace(day=1):
                break
            gl.append([cnpj, ref.isoformat(), "1", nome, isin(tk), seg,
                       "Renda" if seg != "Títulos e Val. Mob." else "Títulos e Valores Mobiliários",
                       "Ativa", "Investidores em Geral"])
            cl.append([cnpj, ref.isoformat(), "1", int(cotas / random.uniform(400, 900)), round(vp * cotas, 2),
                       int(cotas), vp, 0.0009, round(dy / 12 * random.uniform(0.9, 1.1), 5)])
    escrever_zip(f"inf_mensal_fii_{a}.zip", {
        f"inf_mensal_fii_geral_{a}.csv": csv_bytes(g_cab, gl),
        f"inf_mensal_fii_complemento_{a}.csv": csv_bytes(c_cab, cl),
    })

# Proventos no formato da B3
br = lambda d: d.strftime("%d/%m/%Y")  # noqa: E731
for tk, f in fund.items():
    cash = []
    for a in range(HOJE.year - 5, HOJE.year + 1):
        luc = f["luc"].get(a) or f["luc"][anos[-1]]
        total = max(luc, 0) * f["payout"] / f["acoes"]
        if total <= 0:
            continue
        meses = random.choice([[4], [5, 11], [3, 6, 9, 12], [4, 8, 12]])
        for k, m in enumerate(meses):
            com = dt.date(a, m, 15)
            if com > HOJE:
                continue
            pag = com + dt.timedelta(days=random.randint(10, 50))
            label = "JRS CAP PROPRIO" if k % 2 else "DIVIDENDO"
            cash.append({"assetIssued": isin(tk), "isinCode": isin(tk), "label": label,
                         "rate": f"{total / len(meses):.8f}".replace(".", ","),
                         "lastDatePrior": br(com), "paymentDate": br(pag), "approvedOn": br(com - dt.timedelta(days=3)),
                         "relatedTo": f"{a}"})
    stock = []
    if tk == SPLIT[0]:
        stock.append({"assetIssued": isin(tk), "isinCode": isin(tk), "label": "DESDOBRAMENTO",
                      "factor": "100,00000000000", "lastDatePrior": br(SPLIT[1])})
    (OUT / f"proventos_{tk[:4]}.json").write_text(json.dumps([{"cashDividends": cash, "stockDividends": stock}]),
                                                  encoding="utf-8")
for tk, nome, seg, vp, pvp, dy in FIIS:
    cash = []
    d = dt.date(HOJE.year - 5, 1, 31)
    while d < HOJE:
        val = vp * pvp * dy / 12 * random.uniform(0.85, 1.1)
        cash.append({"isinCode": isin(tk), "label": "RENDIMENTO", "rate": f"{val:.8f}".replace(".", ","),
                     "lastDatePrior": br(d), "paymentDate": br(d + dt.timedelta(days=14))})
        prox = d + dt.timedelta(days=1)  # dia 1 do mês seguinte
        d = (prox.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
    (OUT / f"proventos_{tk[:4]}.json").write_text(json.dumps({"cashDividends": cash}), encoding="utf-8")

print("fixtures em", OUT)
