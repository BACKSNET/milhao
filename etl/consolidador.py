"""Dados do Consolidador de carteira: renda fixa, Tesouro Direto, fundos e cripto.

Tudo vem de fontes públicas e gratuitas:
  - Banco Central (SGS): CDI diário, IPCA mensal e rentabilidade da poupança
  - Tesouro Transparente: preço e taxa diários dos títulos do Tesouro Direto
  - CVM (dados abertos): cota diária e cadastro dos fundos de investimento
  - CoinGecko (API pública sem chave) e Mercado Bitcoin: cotação das criptomoedas em reais

Cada parte é independente: se uma fonte falhar, as outras seguem e o site mostra o que tiver.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import re
import unicodedata
import zipfile
from pathlib import Path

SGS = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{serie}/dados?formato=json&dataInicial={ini}&dataFinal={fim}"
TESOURO_CKAN = "https://www.tesourotransparente.gov.br/ckan/api/3/action/package_show?id=df56aa42-484a-4a59-8184-7676580c81e3"
TESOURO_CSV = ("https://www.tesourotransparente.gov.br/ckan/dataset/df56aa42-484a-4a59-8184-7676580c81e3/"
               "resource/796d2059-14e9-44e3-80c9-2d9e30b405c1/download/PrecoTaxaTesouroDireto.csv")
CVM_DIARIO = "https://dados.cvm.gov.br/dados/FI/DOC/INF_DIARIO/DADOS/inf_diario_fi_{am}.zip"
CVM_DIARIO_HIST = "https://dados.cvm.gov.br/dados/FI/DOC/INF_DIARIO/DADOS/HIST/inf_diario_fi_{ano}.zip"
CVM_CAD = "https://dados.cvm.gov.br/dados/FI/CAD/DADOS/cad_fi.csv"
CVM_REGISTRO = "https://dados.cvm.gov.br/dados/FI/CAD/DADOS/registro_fundo_classe.zip"
COINGECKO = ("https://api.coingecko.com/api/v3/coins/markets?vs_currency=brl&order=market_cap_desc"
             "&per_page=150&page=1&price_change_percentage=24h")
MERCADO_BITCOIN = "https://api.mercadobitcoin.net/api/v4/tickers?symbols={pares}"

MESES_FUNDOS = 36          # histórico mensal de cotas guardado por fundo
COTISTAS_MIN, PL_MIN = 30, 5_000_000   # só fundos abertos ao público de verdade (tira exclusivos e vazios)


def _sem_acento(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower().strip()


def _num(s) -> float | None:
    if s is None:
        return None
    t = str(s).strip().replace("R$", "").replace(" ", "")
    if not t or t in ("-", "--"):
        return None
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def _data(s: str) -> str | None:
    s = (s or "").strip()
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", s)
    if m:
        return f"{m[3]}-{m[2]}-{m[1]}"
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    return m[0] if m else None


def _escrever(caminho: Path, obj) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


# --------------------------------------------------------------------------
# Banco Central: CDI diário, IPCA mensal, poupança
# --------------------------------------------------------------------------
def _serie(fonte, serie: int, anos: int, hoje: dt.date, nome: str) -> list[tuple[str, float]]:
    ini = hoje - dt.timedelta(days=365 * anos)
    url = SGS.format(serie=serie, ini=ini.strftime("%d/%m/%Y"), fim=hoje.strftime("%d/%m/%Y"))
    b = fonte.baixar(url, nome=nome, cache_dias=0.3, silencioso=True, timeout=180)
    if not b:
        return []
    try:
        dados = json.loads(b.decode("utf-8"))
    except Exception:  # noqa: BLE001
        return []
    out = []
    for it in dados if isinstance(dados, list) else []:
        d, v = _data(it.get("data", "")), _num(it.get("valor"))
        if d and v is not None:
            out.append((d, v))
    return out


def montar_renda_fixa(fonte, hoje: dt.date) -> dict | None:
    """CDI do dia (% ao dia) dos últimos 10 anos, IPCA do mês e poupança do mês: com isso o site
    corrige CDB, LCI, LCA, debêntures e poupança desde a data da aplicação."""
    # o SGS limita as séries diárias a 10 anos por consulta
    cdi = _serie(fonte, 12, 10, hoje, "sgs_12_10a.json")
    ipca = _serie(fonte, 433, 25, hoje, "sgs_433_25a.json")
    poup = _serie(fonte, 195, 10, hoje, "sgs_195_10a.json")
    if not cdi:
        return None
    # poupança (série 195): rentabilidade por data de aniversário; fica a do dia 1 de cada mês
    poup_mes: dict[str, float] = {}
    for d, v in poup:
        if d[8:10] == "01" or d[:7] not in poup_mes:
            poup_mes[d[:7]] = v
    return {
        "fonte": "Banco Central do Brasil (SGS)",
        "data": cdi[-1][0],
        "cdi": [[d, round(v, 8)] for d, v in cdi],                 # % ao dia, dias úteis
        "ipca": [[d[:7], v] for d, v in ipca],                     # % no mês
        "poupanca": [[m, round(v, 6)] for m, v in sorted(poup_mes.items())],   # % no mês
    }


# --------------------------------------------------------------------------
# Tesouro Direto: preço de compra e de resgate de cada título
# --------------------------------------------------------------------------
def _url_tesouro(fonte) -> str:
    b = fonte.baixar(TESOURO_CKAN, nome="tesouro_ckan.json", cache_dias=3, silencioso=True)
    try:
        for res in json.loads(b.decode("utf-8"))["result"]["resources"]:
            url = res.get("url") or ""
            if "precotaxa" in url.lower().replace("_", "") and url.lower().endswith(".csv"):
                return url
    except Exception:  # noqa: BLE001
        pass
    return TESOURO_CSV


def _slug(tipo: str, venc: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _sem_acento(tipo)).strip("-") + "-" + venc


def montar_tesouro(fonte, hoje: dt.date) -> tuple[dict, dict] | None:
    url = _url_tesouro(fonte)
    b = fonte.baixar(url, nome="PrecoTaxaTesouroDireto.csv", cache_dias=0.3, timeout=900, guardar=False)
    if not b:
        return None
    texto = b.decode("latin-1")
    leitor = csv.reader(io.StringIO(texto), delimiter=";")
    cab = [_sem_acento(c) for c in next(leitor, [])]

    def col(*partes):
        for i, c in enumerate(cab):
            if all(p in c for p in partes):
                return i
        return None
    i_tipo, i_venc, i_data = col("tipo"), col("vencimento"), col("data base")
    i_tc, i_tv = col("taxa compra"), col("taxa venda")
    i_pc, i_pv, i_pb = col("pu compra"), col("pu venda"), col("pu base")
    if None in (i_tipo, i_venc, i_data, i_pc):
        return None
    limite = (hoje - dt.timedelta(days=365 * 10)).isoformat()
    titulos: dict[str, dict] = {}
    for lin in leitor:
        if len(lin) <= max(i for i in (i_tipo, i_venc, i_data, i_pc) if i is not None):
            continue
        venc, data = _data(lin[i_venc]), _data(lin[i_data])
        if not venc or not data or venc < hoje.isoformat() or data < limite:
            continue
        tipo = lin[i_tipo].strip()
        t = titulos.setdefault(_slug(tipo, venc), {"tipo": tipo, "venc": venc, "dias": {}})
        pc = _num(lin[i_pc])
        pv = _num(lin[i_pv]) if i_pv is not None else None
        pb = _num(lin[i_pb]) if i_pb is not None else None
        t["dias"][data] = [pc or None, pv or pb or None,
                           _num(lin[i_tc]) if i_tc is not None else None, _num(lin[i_tv]) if i_tv is not None else None]
    if not titulos:
        return None
    lista, historicos = [], {}
    for slug, t in titulos.items():
        dias = sorted(t["dias"].items())
        ult_d, (pc, pv, tc, tv) = dias[-1]
        # semanal até 60 dias atrás, diário depois: o bastante para achar o preço do dia da compra
        corte = (dt.date.fromisoformat(ult_d) - dt.timedelta(days=60)).isoformat()
        semana: dict[str, list] = {}
        for d, v in dias:
            chave = d if d >= corte else dt.date.fromisoformat(d).strftime("%G-%V")
            semana[chave] = [d, v[0], v[1]]
        historicos[slug] = {"tipo": t["tipo"], "venc": t["venc"], "p": list(semana.values())}
        lista.append({"id": slug, "tipo": t["tipo"], "venc": t["venc"], "data": ult_d,
                      "pu_compra": pc, "pu_venda": pv, "taxa_compra": tc, "taxa_venda": tv})
    lista.sort(key=lambda x: (x["tipo"], x["venc"]))
    return {"fonte": "Tesouro Transparente", "data": max(x["data"] for x in lista), "titulos": lista}, historicos


# --------------------------------------------------------------------------
# Fundos de investimento (CVM)
# --------------------------------------------------------------------------
def _so_digitos(s: str) -> str:
    return re.sub(r"\D", "", s or "").zfill(14)[-14:]


def _ler_csv(conteudo: bytes) -> tuple[list[str], csv.reader]:
    texto = conteudo.decode("latin-1")
    leitor = csv.reader(io.StringIO(texto), delimiter=";")
    cab = [c.strip().upper() for c in next(leitor, [])]
    return cab, leitor


def _cotas_do_zip(conteudo: bytes) -> dict[str, dict[str, list]]:
    """{cnpj: {data: [cota, patrimonio, cotistas]}} de um informe diário (mensal ou do ano inteiro)."""
    out: dict[str, dict[str, list]] = {}
    with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
        for nome in z.namelist():
            if not nome.lower().endswith(".csv"):
                continue
            cab, leitor = _ler_csv(z.read(nome))
            idx = {c: i for i, c in enumerate(cab)}
            i_cnpj = idx.get("CNPJ_FUNDO_CLASSE", idx.get("CNPJ_FUNDO"))
            i_sub = idx.get("ID_SUBCLASSE")
            i_d, i_q, i_pl, i_ct = idx.get("DT_COMPTC"), idx.get("VL_QUOTA"), idx.get("VL_PATRIM_LIQ"), idx.get("NR_COTST")
            if None in (i_cnpj, i_d, i_q):
                continue
            for lin in leitor:
                if len(lin) <= max(i_cnpj, i_d, i_q):
                    continue
                if i_sub is not None and i_sub < len(lin) and lin[i_sub].strip():
                    continue   # subclasses têm cota própria; fica a da classe
                q = _num(lin[i_q])
                if not q:
                    continue
                d = _data(lin[i_d])
                out.setdefault(_so_digitos(lin[i_cnpj]), {})[d] = [
                    q, _num(lin[i_pl]) if i_pl is not None else None, _num(lin[i_ct]) if i_ct is not None else None]
    return out


def _nomes_fundos(fonte) -> dict[str, list]:
    """CNPJ -> [nome, classe] juntando o cadastro antigo e o novo (RCVM 175)."""
    nomes: dict[str, list] = {}

    def juntar(conteudo: bytes):
        cab, leitor = _ler_csv(conteudo)
        i_cnpj = next((i for i, c in enumerate(cab) if "CNPJ" in c), None)
        i_nome = next((i for i, c in enumerate(cab) if "DENOM" in c), None)
        i_cls = next((i for i, c in enumerate(cab) if c in ("CLASSE", "CLASSIFICACAO", "CLASSE_ANBIMA") or "CLASSIFICA" in c), None)
        i_sit = next((i for i, c in enumerate(cab) if c in ("SIT", "SITUACAO")), None)
        if i_cnpj is None or i_nome is None:
            return
        for lin in leitor:
            if len(lin) <= max(i_cnpj, i_nome):
                continue
            if i_sit is not None and i_sit < len(lin) and "CANCEL" in lin[i_sit].upper():
                continue
            k = _so_digitos(lin[i_cnpj])
            nome = lin[i_nome].strip()
            if nome:
                nomes[k] = [nome, (lin[i_cls].strip() if i_cls is not None and i_cls < len(lin) else "") or nomes.get(k, ["", ""])[1]]

    b = fonte.baixar(CVM_CAD, nome="cad_fi.csv", cache_dias=5, timeout=300, silencioso=True)
    if b:
        juntar(b)
    b = fonte.baixar(CVM_REGISTRO, nome="registro_fundo_classe.zip", cache_dias=5, timeout=300, silencioso=True)
    if b:
        try:
            with zipfile.ZipFile(io.BytesIO(b)) as z:
                for n in sorted(z.namelist()):          # registro_classe vem depois de registro_fundo e vale mais
                    if n.lower().endswith(".csv") and "subclasse" not in n.lower():
                        juntar(z.read(n))
        except zipfile.BadZipFile:
            pass
    return nomes


def _mes_derivado(fonte, am: str, cache: Path | None) -> dict[str, list] | None:
    """Última cota de cada fundo no mês AAAAMM. Meses fechados ficam guardados já resumidos."""
    arq = cache / f"fundos_mes_{am}.json" if cache else None
    if arq and arq.exists():
        try:
            return json.loads(arq.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    b = fonte.baixar(CVM_DIARIO.format(am=am), nome=f"inf_diario_fi_{am}.zip", cache_dias=0.3,
                     timeout=600, silencioso=True, guardar=False)
    meses: dict[str, dict] = {}
    if b:
        meses[am] = _cotas_do_zip(b)
    else:   # meses antigos ficam num zip por ano
        b = fonte.baixar(CVM_DIARIO_HIST.format(ano=am[:4]), nome=f"inf_diario_fi_{am[:4]}.zip",
                         cache_dias=30, timeout=900, silencioso=True, guardar=False)
        if not b:
            return None
        for cnpj, dias in _cotas_do_zip(b).items():
            for d, v in dias.items():
                meses.setdefault(d[:4] + d[5:7], {}).setdefault(cnpj, {})[d] = v
    resumo_ret = None
    for m, fundos in meses.items():
        resumo = {k: [max(dias), *dias[max(dias)]] for k, dias in fundos.items() if dias}
        if cache:
            (cache / f"fundos_mes_{m}.json").write_text(json.dumps(resumo, separators=(",", ":")), encoding="utf-8")
        if m == am:
            resumo_ret = resumo
    return resumo_ret


def montar_fundos(fonte, hoje: dt.date, saida: Path, aviso) -> int:
    cache = getattr(fonte, "cache", None)
    am_atual = hoje.strftime("%Y%m")
    # mês atual e anterior: cota diária; meses fechados: só a última cota
    recentes: dict[str, dict[str, list]] = {}
    for k in (1, 0):
        d = (hoje.replace(day=1) - dt.timedelta(days=1)) if k else hoje
        am = d.strftime("%Y%m")
        b = fonte.baixar(CVM_DIARIO.format(am=am), nome=f"inf_diario_fi_{am}.zip", cache_dias=0.3,
                         timeout=600, silencioso=True, guardar=False)
        if b:
            for cnpj, dias in _cotas_do_zip(b).items():
                recentes.setdefault(cnpj, {}).update(dias)
    if not recentes:
        aviso("informe diário de fundos da CVM indisponível")
        return 0
    mensal: dict[str, dict[str, float]] = {}
    ref = hoje.replace(day=1)
    for i in range(2, MESES_FUNDOS + 1):
        ref = (ref - dt.timedelta(days=1)).replace(day=1)
        am = ref.strftime("%Y%m")
        resumo = _mes_derivado(fonte, am, cache if isinstance(cache, Path) else None)
        for cnpj, (d, q, *_r) in (resumo or {}).items():
            mensal.setdefault(cnpj, {})[am[:4] + "-" + am[4:]] = q
    nomes = _nomes_fundos(fonte)
    busca, fatias = [], {}
    corte_diario = (hoje - dt.timedelta(days=45)).isoformat()
    for cnpj, dias in recentes.items():
        ult = max(dias)
        q, pl, cot = dias[ult]
        if (cot or 0) < COTISTAS_MIN or (pl or 0) < PL_MIN:
            continue
        nome, classe = nomes.get(cnpj, ["", ""])
        if not nome:
            continue
        hist = dict(mensal.get(cnpj, {}))
        for d, v in dias.items():                          # fim dos dois últimos meses
            m = d[:7]
            if m != am_atual[:4] + "-" + am_atual[4:] and (m not in hist or d >= max(x for x in dias if x[:7] == m)):
                hist[m] = v[0]
        fatias.setdefault(cnpj[:2], {})[cnpj] = {
            "n": nome, "t": classe, "pl": round(pl or 0), "c": int(cot or 0),
            "m": [[m, round(v, 8)] for m, v in sorted(hist.items())],
            "d": [[d, round(v[0], 8)] for d, v in sorted(dias.items()) if d >= corte_diario],
        }
        busca.append([cnpj, nome, classe, round(pl or 0)])
    busca.sort(key=lambda x: -x[3])
    pasta = saida / "fundo"
    for k, v in fatias.items():
        _escrever(pasta / f"{k}.json", v)
    _escrever(saida / "fundos_busca.json", {"fonte": "CVM (dados abertos)", "data": max(max(d) for d in recentes.values()),
                                            "fundos": busca})
    return len(busca)


# --------------------------------------------------------------------------
# Criptomoedas
# --------------------------------------------------------------------------
RESERVA_MB = {"BTC": ("bitcoin", "Bitcoin"), "ETH": ("ethereum", "Ethereum"), "SOL": ("solana", "Solana"),
              "XRP": ("ripple", "XRP"), "USDT": ("tether", "Tether"), "USDC": ("usd-coin", "USDC"),
              "ADA": ("cardano", "Cardano"), "DOGE": ("dogecoin", "Dogecoin"), "LTC": ("litecoin", "Litecoin"),
              "BNB": ("binancecoin", "BNB"), "LINK": ("chainlink", "Chainlink"), "DOT": ("polkadot", "Polkadot")}


def montar_cripto(fonte, hoje: dt.date) -> dict | None:
    b = fonte.baixar(COINGECKO, nome="coingecko_brl.json", cache_dias=0.2, tentativas=4, timeout=60, silencioso=True)
    moedas = []
    try:
        for c in json.loads(b.decode("utf-8")) if b else []:
            if c.get("current_price"):
                moedas.append([c["id"], (c.get("symbol") or "").upper(), c.get("name") or c["id"], c["current_price"],
                               round((c.get("price_change_percentage_24h") or 0) / 100, 5)])
    except Exception:  # noqa: BLE001
        moedas = []
    fonte_nome = "CoinGecko"
    if not moedas:   # reserva: Mercado Bitcoin, só as principais
        pares = ",".join(f"{s}-BRL" for s in RESERVA_MB)
        b = fonte.baixar(MERCADO_BITCOIN.format(pares=pares), nome="mercadobitcoin.json", cache_dias=0.2, silencioso=True)
        try:
            for t in json.loads(b.decode("utf-8")) if b else []:
                s = (t.get("pair") or "").split("-")[0]
                if s in RESERVA_MB and _num(t.get("last")):
                    ab, ul = _num(t.get("open")), _num(t.get("last"))
                    moedas.append([RESERVA_MB[s][0], s, RESERVA_MB[s][1], ul, round(ul / ab - 1, 5) if ab else 0])
            fonte_nome = "Mercado Bitcoin"
        except Exception:  # noqa: BLE001
            moedas = []
    if not moedas:
        return None
    return {"fonte": fonte_nome, "data": dt.datetime.now().isoformat(timespec="minutes"), "moedas": moedas}


# --------------------------------------------------------------------------
def gerar(fonte, saida: Path, hoje: dt.date, aviso) -> dict:
    """Gera os arquivos do Consolidador. Nunca derruba o robô: cada parte falha sozinha."""
    feito = {}
    try:
        rf = montar_renda_fixa(fonte, hoje)
        if rf:
            _escrever(saida / "renda_fixa.json", rf)
            feito["renda_fixa"] = len(rf["cdi"])
        else:
            aviso("CDI do Banco Central indisponível para o Consolidador")
    except Exception as e:  # noqa: BLE001
        aviso(f"renda fixa: {e}")
    try:
        td = montar_tesouro(fonte, hoje)
        if td:
            lista, historicos = td
            _escrever(saida / "tesouro.json", lista)
            for slug, h in historicos.items():
                _escrever(saida / "tesouro" / f"{slug}.json", h)
            feito["tesouro"] = len(lista["titulos"])
        else:
            aviso("preços do Tesouro Direto indisponíveis")
    except Exception as e:  # noqa: BLE001
        aviso(f"Tesouro Direto: {e}")
    try:
        feito["fundos"] = montar_fundos(fonte, hoje, saida, aviso)
    except Exception as e:  # noqa: BLE001
        aviso(f"fundos: {e}")
    try:
        cr = montar_cripto(fonte, hoje)
        if cr:
            _escrever(saida / "cripto.json", cr)
            feito["cripto"] = len(cr["moedas"])
        else:
            aviso("cotação de criptomoedas indisponível")
    except Exception as e:  # noqa: BLE001
        aviso(f"cripto: {e}")
    return feito
