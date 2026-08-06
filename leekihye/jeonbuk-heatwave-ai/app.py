import gradio as gr
import pandas as pd
import joblib

# =========================================================================
# 1. v4 통합 AI 모델 패키지 불러오기
# =========================================================================
try:
    package = joblib.load('heatwave_severe_model_v4.joblib')
    model = package['model']
    features = package['features']
    threshold = package.get('threshold', 0.25)
except Exception as e:
    model = None
    features = []
    threshold = 0.25

# =========================================================================
# 2. AI 예측 및 보정 함수
# =========================================================================
def predict(ta_best, tw, rh, h500, h200, wt, wd, ws):
    if model is None:
        return "❌ 모델 파일(heatwave_severe_model_v4.joblib)을 찾을 수 없습니다.", "", ""
    
    try:
        # [고기압 세력 과소모의 보정]
        avg_bias = 1.2
        if h500 >= 5910 or h200 >= 12500:
            ai_corrected_ta = ta_best + avg_bias
        else:
            ai_corrected_ta = ta_best + (avg_bias * 0.5)
            
        # 보정 체감온도 산출
        ai_corrected_perceived = -0.2442 + (0.55399 * tw) + (0.45535 * ai_corrected_ta) - (0.0022 * (tw**2)) + (0.00278 * tw * ai_corrected_ta) + 3.0
        
        # 모델 입력 데이터 구성 (지점번호 제외 9개 핵심 기상 인자)
        input_dict = {
            '일최고체감온도': ai_corrected_perceived,
            '일최고기온': ai_corrected_ta,
            '모델기온예보': ta_best,
            '수온(부안부이)': wt,
            '500지위고도(UM국지)': h500,
            '200지위고도(UM국지)': h200,
            '습구온도': tw,
            '상대습도': rh,
            '풍향1': wd,
            '풍속1': ws
        }
        
        # 실제 모델 학습 시 사용된 피처만 정렬하여 추출
        input_data = pd.DataFrame([input_dict])
        if features:
            # features에 존재하는 컬럼만 선택
            valid_features = [f for f in features if f in input_data.columns]
            input_data = input_data[valid_features]
        
        # 확률 예측
        prob_val = model.predict_proba(input_data)[0][1]
        prob_percent = prob_val * 100
        
        # 방재 판정
        if prob_val >= threshold:
            res = f"🚨 [위험] 폭염 중대경보 발령 대상 (확률: {prob_percent:.1f}%)"
        elif prob_val >= 0.10:
            res = f"⚠️ [주의] 잠재적 폭염 감시 필요 (확률: {prob_percent:.1f}%)"
        else:
            res = f"✅ [보통] 기상 인자 정상 범위 (확률: {prob_percent:.1f}%)"
            
        return res, f"{ai_corrected_ta:.1f} ℃", f"{ai_corrected_perceived:.1f} ℃"
        
    except Exception as e:
        return f"❌ 분석 중 에러 발생: {str(e)}", "", ""

# =========================================================================
# 3. Gradio 화면 구성 (지점번호 입력 없이 기상 수치 집중)
# =========================================================================
demo = gr.Interface(
    fn=predict,
    inputs=[
        gr.Number(label="모델기온예보 원본 (℃)", value=35.0),
        gr.Number(label="습구온도 (℃)", value=28.0),
        gr.Slider(0, 100, label="상대습도 (%)", value=60),
        gr.Number(label="500hPa 지위고도 (gpm)", value=5920),
        gr.Number(label="200hPa 지위고도 (gpm)", value=12550),
        gr.Number(label="수온(부안부이) (℃)", value=29.0),
        gr.Number(label="풍향 (0~360)", value=270),
        gr.Number(label="풍속 (m/s)", value=2.0)
    ],
    outputs=[
        gr.Textbox(label="🚨 AI 최종 방재 판정 (폭염중대경보)"), 
        gr.Textbox(label="📈 [AI 예측] 수치예보 한계 극복 보정 예상 기온"), 
        gr.Textbox(label="🌡️ [AI 예측] 최종 보정 체감온도")
    ],
    title="🌡️ 전북 폭염 중대경보 AI 예보 시스템 (v4.0)",
    description="전북 지역 통합 대기/해양 인자를 입력하여 폭염 중대경보 위험 가능성을 판정합니다."
)

if __name__ == "__main__":
    demo.launch()