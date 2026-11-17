"""Desenha os ícones do Milhão (o "M." da marca) para a tela inicial do celular.

Gera, na pasta do site:
  icone-192.png, icone-512.png, icone-maskable-512.png  (Android / atalho do Chrome)
  apple-touch-icon.png (180 px, iPhone)
  favicon.svg e favicon-32.png (aba do navegador)
  manifest.webmanifest

O "M" é desenhado com polígonos (sem depender de fonte instalada).
Uso: python etl/icones.py --saida site
"""
import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw

FUNDO = "#13241C"      # tinta do site (fundo da tela de entrada)
LETRA = "#FFFFFF"
PONTO = "#2FCB8F"      # o ponto verde da marca

# "M." numa grade de 512; o conjunto fica centralizado
M = [(80, 380), (80, 132), (184, 132), (243, 262), (302, 132), (406, 132), (406, 380),
     (330, 380), (330, 244), (276, 356), (210, 356), (156, 244), (156, 380)]
PONTO_RET = (428, 312, 488, 380)   # x0, y0, x1, y1
DESLOCA = (512 - (488 - 80)) / 2 - 80   # centraliza na horizontal


def _pontos(escala, folga=0):
    """Polígono do M e retângulo do ponto, na escala pedida (folga encolhe para o ícone 'maskable')."""
    k = escala * (1 - folga)
    base = 512 * escala * folga / 2
    m = [(base + (x + DESLOCA) * k, base + y * k) for x, y in M]
    x0, y0, x1, y1 = PONTO_RET
    p = (base + (x0 + DESLOCA) * k, base + y0 * k, base + (x1 + DESLOCA) * k, base + y1 * k)
    return m, p


def desenhar(tam, raio=0.22, folga=0.0):
    """Desenha em 4x e reduz, para as bordas saírem lisas."""
    big = tam * 4
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if raio:
        d.rounded_rectangle((0, 0, big - 1, big - 1), radius=int(big * raio), fill=FUNDO)
    else:
        d.rectangle((0, 0, big, big), fill=FUNDO)
    m, p = _pontos(big / 512, folga)
    d.polygon(m, fill=LETRA)
    d.rounded_rectangle(p, radius=int(big * 0.014), fill=PONTO)
    return img.resize((tam, tam), Image.LANCZOS)


def svg():
    m, p = _pontos(1)
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in m)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">'
            f'<rect width="512" height="512" rx="112" fill="{FUNDO}"/>'
            f'<polygon points="{pts}" fill="{LETRA}"/>'
            f'<rect x="{p[0]:.1f}" y="{p[1]:.1f}" width="{p[2] - p[0]:.1f}" height="{p[3] - p[1]:.1f}" rx="7" fill="{PONTO}"/></svg>')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--saida", default="site")
    saida = Path(ap.parse_args().saida)
    saida.mkdir(parents=True, exist_ok=True)
    desenhar(192).save(saida / "icone-192.png")
    desenhar(512).save(saida / "icone-512.png")
    # o Android recorta o ícone em círculo ou gota: fundo cheio e a marca com folga
    desenhar(512, raio=0, folga=0.28).save(saida / "icone-maskable-512.png")
    # o iPhone arredonda sozinho: fundo cheio, sem transparência
    desenhar(180, raio=0).convert("RGB").save(saida / "apple-touch-icon.png")
    desenhar(32, raio=0.2).save(saida / "favicon-32.png")
    (saida / "favicon.svg").write_text(svg(), encoding="utf-8")
    manifesto = {
        "name": "Milhão",
        "short_name": "Milhão",
        "description": "Sua carteira de ações e FIIs da B3.",
        "lang": "pt-BR",
        "start_url": "./",
        "scope": "./",
        "display": "standalone",
        "background_color": FUNDO,
        "theme_color": FUNDO,
        "icons": [
            {"src": "icone-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "icone-512.png", "sizes": "512x512", "type": "image/png"},
            {"src": "icone-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
    }
    (saida / "manifest.webmanifest").write_text(json.dumps(manifesto, ensure_ascii=False, indent=1), encoding="utf-8")
    print("ícones gerados em", saida)


if __name__ == "__main__":
    main()
