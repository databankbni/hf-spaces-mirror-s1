import streamlit as st

st.set_page_config(page_title="Ricfine Studio", layout="wide")
st.title("🚀 Ricfine Studio")

# --- EDITOR ---
col1, col2 = st.columns([2, 1])

with col1:
    codigo = st.text_area("Escribe tu código .rf:", height=400, value="di Hola\n guarda x como 10")
    
    if st.button("▶️ EJECUTAR", type="primary"):
        lineas = codigo.split('\n')
        memoria = {} # Aquí es donde "se van" los datos
        salida = []
        
        for linea in lineas:
            l = linea.strip().lower()
            if not l: continue
            p = l.split(' ')
            
            if p[0] == 'di':
                val = memoria.get(p[1], ' '.join(p[1:]))
                salida.append(f"🤖 {val}")
            elif p[0] == 'guarda' and 'como' in p:
                idx = p.index('como')
                memoria[p[1]] = p[idx+1] # Aquí se guarda el dato
            elif p[0] == 'suma' and 'mas' in p:
                idx = p.index('mas')
                v1 = memoria.get(p[1], p[1])
                v2 = memoria.get(p[idx+1], p[idx+1])
                try:
                    res = int(v1) + int(v2)
                    memoria['resultado'] = res
                    salida.append(f"🧮 {res}")
                except: pass
                
        st.code("\n".join(salida), language="bash")
        st.session_state['ultima_memoria'] = memoria # Guardamos la memoria para mostrarla

with col2:
    st.subheader("💾 Memoria Activa")
    if 'ultima_memoria' in st.session_state:
        mem = st.session_state['ultima_memoria']
        if mem:
            for clave, valor in mem.items():
                st.write(f"**{clave}**: {valor}")
        else:
            st.write("La memoria está vacía.")
    else:
        st.write("Ejecuta un código para ver la memoria.")