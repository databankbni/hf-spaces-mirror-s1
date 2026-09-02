import sys

def ejecutar(archivo):
    print("🚀 Iniciando Ricfine v1.0...")
    memoria = {}
    
    try:
        with open(archivo, 'r', encoding='utf-8') as f:
            lineas = f.readlines()
        
        for linea in lineas:
            linea = linea.strip().lower()
            if not linea or linea.startswith('#'): continue
            
            partes = linea.split(' ')
            orden = partes[0]
            
            if orden == 'di':
                texto = ' '.join(partes[1:])
                if texto in memoria:
                    print(memoria[texto])
                else:
                    print(texto)
                    
            elif orden == 'guarda' and 'como' in partes:
                idx = partes.index('como')
                nombre = partes[1]
                valor = ' '.join(partes[idx+1:])
                try: valor = int(valor)
                except: pass
                memoria[nombre] = valor
                
            elif orden == 'suma' and 'mas' in partes:
                idx = partes.index('mas')
                v1 = memoria.get(partes[1], partes[1])
                v2 = memoria.get(partes[idx+1], partes[idx+1])
                try:
                    res = int(v1) + int(v2)
                    memoria['resultado'] = res
                    print(f"🧮 Resultado: {res}")
                except: print("⚠️ Error matemático")

    except FileNotFoundError:
        print("❌ Archivo no encontrado.")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        ejecutar(sys.argv[1])