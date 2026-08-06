import math
import gradio as gr

# ====================================
# Definition
# ====================================

def square_section(D, t):
    """Square CFST section properties. D = side length, t = thickness"""
    As = D**2 - (D - t*2)**2
    Ac = (D - t*2)**2
    Is = (D**4 - (D - t*2)**4) / 12
    Ic = (D - t*2)**4 / 12
    return As, Ac, Is, Ic


def circular_section(D, t):
    """Circular CFST section properties. D = diameter, t = thickness"""
    As = math.pi * (D**2 - (D - t*2)**2) / 4
    Ac = math.pi * (D - t*2)**2 / 4
    Is = math.pi * (D**4 - (D - t*2)**4) / 64
    Ic = math.pi * (D - t*2)**4 / 64
    return As, Ac, Is, Ic


def section_capacity(As, Ac, fy, fc):
    N = (As * fy + Ac * fc) / 1000
    return N


def euler_buckling_load(Es, Ec, Is, Ic, L, K):
    """Ncr = π² * (Es*Is + 0.6*Ec*Ic) / (L*K)²"""
    EI_eff = (Es * Is) + (0.6 * Ec * Ic)
    L_eff = L * K
    return (math.pi**2 * EI_eff) / (L_eff**2) / 1000


def relative_slenderness(Ncr, N):
    if Ncr <= 0:
        raise ValueError("Ncr must be greater than 0.")
    if N <= 0:
        raise ValueError("N must be greater than 0. Check fc and fy.")
    return math.sqrt(N / Ncr)


# ====================================
#GRADIO
# ====================================

def calculate_slenderness(shape, D_val, t_val, fy_val, fc_val, Es_val, Ec_val, L_val, K_val):
  
    inputs = [D_val, t_val, fy_val, fc_val, Es_val, Ec_val, L_val, K_val]
    if any(v is None for v in inputs):
        raise gr.Error("Please enter valid numbers in all fields.")

    if D_val <= 0 or t_val <= 0 or L_val <= 0 or K_val <= 0:
        raise gr.Error("Input error: (D, t, L, K) must be greater than 0.")
        
    if t_val >= D_val / 2:
        raise gr.Error("Input error: Steel tube thickness (t) is too thick.")

    try:
        # 1: Area and inertial Mô-men 
        if shape == "Square":
            As, Ac, Is, Ic = square_section(D_val, t_val)
        elif shape == "Circular":
            As, Ac, Is, Ic = circular_section(D_val, t_val)
        else:
            raise gr.Error("Please select a valid shape.")

        # 2:  N (Section Capacity)
        N_val = section_capacity(As, Ac, fy_val, fc_val)

        # 3:  Euler Ncr
        Ncr_val = euler_buckling_load(Es_val, Ec_val, Is, Ic, L_val, K_val)

        # 4: λ = sqrt(N/Ncr)
        lam_rel = relative_slenderness(Ncr_val, N_val)

        # 
        return f"{N_val:.2f} kN", f"{Ncr_val:.2f} kN", f"{lam_rel:.3f}"

    except ValueError as e:
        raise gr.Error(str(e))


# ====================================

# ====================================

with gr.Blocks(theme=gr.themes.Soft()) as demo:
    gr.Markdown("# Relative Slenderness for Slender Column")
    
    with gr.Row():
        # Cột bên trái: Nhập dữ liệu thông số cột CFST
        with gr.Column():
            gr.Markdown("### Input Parameters")
            shape_box = gr.Dropdown(
                choices=["Square", "Circular"],
                value="Square",
                label="Cross-section Shape"
            )
            entry_D = gr.Number(label="Dimension/Diameter (D)", minimum=0)
            entry_t = gr.Number(label="Thickness of steel tube (t)", minimum=0)
            entry_fy = gr.Number(label="Yield strength of steel (fy)", minimum=0)
            entry_fc = gr.Number(label="Compressive strength of concrete (fc)", minimum=0)
            entry_Es = gr.Number(label="Elastic modulus of steel (Es)", minimum=0)
            entry_Ec = gr.Number(label="Elastic modulus of concrete (Ec)", minimum=0)
            entry_L = gr.Number(label="Column length (L)", minimum=0)
            entry_K = gr.Number(label="Effective length factor (K)", minimum=0)
            
            predict_btn = gr.Button("Calculate", variant="primary")
            

        with gr.Column():
            gr.Markdown("### Calculation Results")
            lbl_res_N = gr.Textbox(label="Section Capacity (N)", placeholder="---", interactive=False)
            lbl_res_Ncr = gr.Textbox(label="Euler Load (Ncr)", placeholder="---", interactive=False)
            lbl_res_lam = gr.Textbox(label="Relative Slenderness (λ)", placeholder="---", interactive=False)
            
          
            gr.Examples(
                examples=[
                    ["Square", 200, 6, 350, 40, 200000, 30000, 3000, 0.7],
                    ["Circular", 200, 6, 350, 40, 200000, 30000, 3000, 0.7]
                ],
                inputs=[shape_box, entry_D, entry_t, entry_fy, entry_fc, entry_Es, entry_Ec, entry_L, entry_K],
                outputs=[lbl_res_N, lbl_res_Ncr, lbl_res_lam],
                fn=calculate_slenderness,
                run_on_click=True
            )
            
    gr.Markdown("### *This GUI is developed by Nhung Vu - Department of Infrastructure Engineering - UniMelb*")
    
   
    predict_btn.click(
        fn=calculate_slenderness,
        inputs=[shape_box, entry_D, entry_t, entry_fy, entry_fc, entry_Es, entry_Ec, entry_L, entry_K],
        outputs=[lbl_res_N, lbl_res_Ncr, lbl_res_lam]
    )

if __name__ == "__main__":
    demo.launch()