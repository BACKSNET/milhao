#!/usr/bin/env python3
"""Gera milhao.html: o site com os dados embutidos, para abrir com dois cliques, sem servidor."""
import json, sys
from pathlib import Path
raiz = Path(__file__).resolve().parent.parent
dados_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else raiz / "data"
saida = Path(sys.argv[2]) if len(sys.argv) > 2 else raiz / "milhao.html"
dados = {"data/meta.json": json.loads((dados_dir / "meta.json").read_text("utf-8")),
         "data/ativos.json": json.loads((dados_dir / "ativos.json").read_text("utf-8"))}
for f in sorted((dados_dir / "ativo").glob("*.json")):
    dados[f"data/ativo/{f.name}"] = json.loads(f.read_text("utf-8"))
bloco = "<script>window.MILHAO_DADOS=" + json.dumps(dados, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/") + ";</script>\n"
html = (raiz / "index.html").read_text("utf-8").replace("<script>\n\"use strict\";", bloco + "<script>\n\"use strict\";", 1)
assert bloco in html, "não achei o ponto de inserção"
saida.write_text(html, "utf-8")
print(f"{saida} ({saida.stat().st_size / 1e6:.1f} MB, {len(dados) - 2} ativos)")
