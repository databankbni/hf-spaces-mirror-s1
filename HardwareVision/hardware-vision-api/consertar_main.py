#!/usr/bin/env python3
# ══════════════════════════════════════════════════════════════════════════════
# CONSERTA O main.py — remove restos do /raiox e insere o /map na indentação certa
#
# COMO USAR (no terminal, dentro da pasta do Space):
#   1. Coloque este arquivo e o endpoint_map.py na MESMA pasta do main.py
#   2. Rode:   python consertar_main.py
#   3. Ele mostra o que fez e salva um backup main.py.bak antes de mexer
#   4. Se der "OK", faça git add/commit/push
#
# O script é seguro: se algo não bater, ele avisa e NÃO grava nada.
# ══════════════════════════════════════════════════════════════════════════════

import ast
import re
import shutil
import sys
from pathlib import Path

MAIN = Path("main.py")
MAPF = Path("endpoint_map.py")


def erro(msg):
    print(f"\n❌ {msg}")
    print("   Nada foi alterado. O main.py continua como estava.")
    sys.exit(1)


def main():
    if not MAIN.exists():
        erro("main.py não encontrado nesta pasta.")
    if not MAPF.exists():
        erro("endpoint_map.py não encontrado nesta pasta.")

    src = MAIN.read_text(encoding="utf-8")
    linhas = src.split("\n")

    print("🔎 Analisando o main.py...")
    print(f"   {len(linhas)} linhas")

    # ── 1. Tabs misturados? ───────────────────────────────────────────────
    linhas_tab = [i + 1 for i, l in enumerate(linhas) if "\t" in l]
    if linhas_tab:
        print(f"   ⚠️  TAB encontrado nas linhas: {linhas_tab[:10]}")
        print("      (Python não aceita misturar TAB e espaço — vou converter)")
        linhas = [l.expandtabs(4) for l in linhas]

    # ── 2. Acha TODOS os blocos de rota (@app.<verbo>) ────────────────────
    # Cada rota começa num @app. e termina onde começa a próxima linha de
    # coluna zero que não faz parte do bloco.
    inicios = [
        i for i, l in enumerate(linhas)
        if re.match(r"^@app\.(get|post|put|delete)\(", l)
    ]
    if not inicios:
        erro("Nenhuma rota @app.* encontrada — o arquivo parece errado.")

    def fim_do_bloco(ini):
        """Onde termina a rota que começa em `ini` (índice exclusivo).

        Cuidado: a assinatura da função pode ocupar VÁRIAS linhas
        (parâmetros um por linha, fechando com '):' sozinho). Por isso
        procuramos o fim da assinatura de verdade, não só a linha do 'def'.
        """
        j = ini + 1
        # 1. pula até a linha do def/async def
        while j < len(linhas) and not re.match(r"^(async\s+)?def\s", linhas[j]):
            j += 1
        if j >= len(linhas):
            return len(linhas)

        # 2. anda até FECHAR os parênteses da assinatura
        saldo = 0
        vistos = False
        while j < len(linhas):
            saldo += linhas[j].count("(") - linhas[j].count(")")
            if "(" in linhas[j]:
                vistos = True
            j += 1
            if vistos and saldo <= 0:
                break

        # 3. o corpo é tudo indentado (ou em branco) a partir daqui
        ultimo_conteudo = j
        while j < len(linhas):
            l = linhas[j]
            if l.strip() == "":
                j += 1
                continue
            if l[0] in (" ", "\t"):
                j += 1
                ultimo_conteudo = j
                continue
            break
        return ultimo_conteudo

    def inicio_com_comentario(ini):
        """Recua o início para incluir o comentário-cabeçalho da rota.

        As rotas do main.py são precedidas por uma linha tipo
        '# ── /raiox ────────────...'. Se ela não for removida junto,
        sobra um comentário órfão apontando para uma rota que não existe mais.
        """
        k = ini - 1
        while k >= 0 and linhas[k].strip() == "":
            k -= 1
        if k >= 0 and linhas[k].lstrip().startswith("#"):
            return k
        return ini

    # ── 3. Localiza o /raiox e o /map (se já existir) ─────────────────────
    idx_raiox = None
    idx_map = None
    for i in inicios:
        if '"/raiox"' in linhas[i] or "'/raiox'" in linhas[i]:
            idx_raiox = i
        if '"/map"' in linhas[i] or "'/map'" in linhas[i]:
            idx_map = i

    # ── 4. Remove os blocos velhos, do fim para o começo ──────────────────
    remover = []
    if idx_raiox is not None:
        fim = fim_do_bloco(idx_raiox)
        ini = inicio_com_comentario(idx_raiox)
        remover.append((ini, fim, "/raiox"))
        print(f"   ✂️  /raiox encontrado nas linhas {ini+1}-{fim}")
    if idx_map is not None:
        fim = fim_do_bloco(idx_map)
        ini = inicio_com_comentario(idx_map)
        remover.append((ini, fim, "/map (versão anterior)"))
        print(f"   ✂️  /map já existia nas linhas {ini+1}-{fim}")

    if not remover:
        print("   ℹ️  Nem /raiox nem /map encontrados — o /map será só ADICIONADO")

    for ini, fim, nome in sorted(remover, reverse=True):
        del linhas[ini:fim]
        print(f"   ✓ Removido: {nome}")

    # ── 5. Monta o novo conteúdo ──────────────────────────────────────────
    bloco_map = MAPF.read_text(encoding="utf-8").rstrip("\n").split("\n")
    bloco_map = [l.expandtabs(4) for l in bloco_map]

    # Insere logo ANTES da rota /doutor (posição do /raiox antigo).
    # Se não achar, coloca antes da última rota do arquivo.
    pos = None
    for i, l in enumerate(linhas):
        if re.match(r"^@app\.post\(", l) and ('"/doutor"' in l or "'/doutor'" in l):
            pos = i
            break
    if pos is None:
        alvos = [i for i, l in enumerate(linhas)
                 if re.match(r"^@app\.(get|post)\(", l)]
        pos = alvos[-1] if alvos else len(linhas)

    novo = linhas[:pos] + bloco_map + ["", ""] + linhas[pos:]
    resultado = "\n".join(novo)

    # ── 6. VALIDA antes de gravar ─────────────────────────────────────────
    print("\n🧪 Validando a sintaxe do resultado...")
    try:
        ast.parse(resultado)
    except SyntaxError as e:
        print(f"\n❌ O resultado teria erro de sintaxe:")
        print(f"   linha {e.lineno}: {e.msg}")
        ctx = resultado.split("\n")
        ini = max(0, (e.lineno or 1) - 4)
        for n in range(ini, min(len(ctx), (e.lineno or 1) + 3)):
            marca = ">>" if n + 1 == e.lineno else "  "
            print(f"   {marca} {n+1}: {ctx[n]}")
        erro("Não gravei nada. Me mande o main.py que eu corrijo à mão.")

    print("   ✅ Sintaxe válida!")

    # ── 7. Backup e gravação ──────────────────────────────────────────────
    shutil.copy(MAIN, "main.py.bak")
    MAIN.write_text(resultado, encoding="utf-8")

    print("\n✅ PRONTO!")
    print("   • Backup salvo em: main.py.bak")
    print(f"   • main.py agora tem {len(novo)} linhas")
    print("\n   Próximo passo:")
    print("     git add .")
    print('     git commit -m "MAP: endpoint /map"')
    print("     git push")


if __name__ == "__main__":
    main()
