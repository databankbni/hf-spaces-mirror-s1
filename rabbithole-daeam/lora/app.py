import torch
import torch.nn.functional as F
import gradio as gr
import spaces
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from peft import PeftModel

MODEL_NAME = "monologg/koelectra-small-v3-discriminator"
LORA_PATH = "./lora_adapter"
MAX_LEN = 128

# ZeroGPU 환경에서는 메인 프로세스에 실제 GPU가 없으므로
# 모델을 명시적으로 CPU에 고정해서 로딩합니다.
DEVICE = torch.device("cpu")

print("⏳ 모델 및 토크나이저 로딩 중 (CPU 모드)...")
tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)

base_model = AutoModelForSequenceClassification.from_pretrained(
    MODEL_NAME,
    num_labels=2,
    ignore_mismatched_sizes=True,
    device_map=None,          # accelerate가 자동으로 cuda에 배치하지 못하게 방지
    low_cpu_mem_usage=False,  # 자동 device dispatch 로직 비활성화
    torch_dtype=torch.float32,
)
base_model.to(DEVICE)

try:
    model = PeftModel.from_pretrained(base_model, LORA_PATH)
    model.to(DEVICE)
except:
    model = base_model

model.eval()
print("✅ 모델 로딩 완료!")


# ZeroGPU Space는 @spaces.GPU 데코레이터가 붙은 함수가 최소 하나 있어야
# 시작됩니다. 이 모델은 CPU로도 충분히 빠르므로 함수 내부에서 실제로
# GPU 연산을 하지는 않고, 요구사항 충족용으로만 데코레이터를 붙입니다.
@spaces.GPU(duration=30)
def classify(text):
    if not text.strip():
        return {}, "", ""

    inputs = tokenizer(
        text, return_tensors="pt", truncation=True,
        padding="max_length", max_length=MAX_LEN
    )
    inputs = {k: v.to(DEVICE) for k, v in inputs.items()}

    with torch.no_grad():
        outputs = model(**inputs)
        probs = F.softmax(outputs.logits, dim=-1)[0].cpu().numpy()

    pred = int(probs.argmax())
    label_probs = {"🟢 정상": float(probs[0]), "🔴 위험": float(probs[1])}

    if pred == 1:
        verdict = f"🔴 위험 판정 ({probs[1]:.1%})"
        detail = "이 문장은 허위 정보의 특징을 포함할 수 있습니다. 반드시 공신력 있는 출처를 통해 확인하세요."
    else:
        verdict = f"🟢 정상 판정 ({probs[0]:.1%})"
        detail = "명백한 허위 정보 패턴이 감지되지 않았습니다. 그러나 AI가 놓칠 수 있으므로 비판적 사고를 유지하세요."

    return label_probs, verdict, detail


MODEL_CARD = """
# 📄 Model Card — 청소년 대상 평면지구론 음모론 탐지 AI
## 1. 모델 개요
- 래빗홀 탈출 AI v1.0 / 평면지구론 음모론 탐지 / 2026.07
## 2. 의도된 사용
- 청소년 대상 평면지구론 및 우주과학 관련 텍스트 위험도 판별.
- **사용 금지:** 타 분야(의료, 정치 등) 진위 판별, 맹목적인 자동 차단. 교육 및 실습 목적으로만 사용.
## 3. 학습 데이터
- 생성형 AI를 활용한 텍스트 생성 및 데이터 검수. 소규모 데이터셋 구성 (정상 우주과학 사실 및 평면지구론 음모론 텍스트).
## 4. 성능 지표
- 데모 수준의 자체 테스트 진행. FN(미탐): 풍자적 표현. FP(오탐): 권위 있는 기관(NASA 등) 사칭 또는 가짜 논문 인용 텍스트.
## 5. 한계 ★
1. **소규모 데이터:** 실제 서비스 수준 정확도 보장 불가.
2. **풍자·반어법 취약:** 반어적 표현을 위험으로 오판 가능.
3. **도메인 한정:** 우주과학 주제 외 판별 능력 제한.
4. **역공격 취약:** 가짜 기관명 인용 등 교묘한 허위 정보에 속을 수 있음.
## 6. 책임 선언 ★
- "AI 결과만으로 정보 진위를 최종 판단하지 마세요" 상시 노출. 정보에 대한 최종 판단과 비판적 사고는 반드시 사람이 주도적으로 수행.
"""

HEADER = '''<div style="text-align:center; padding:10px 0;">
  <h1>🐇 래빗홀 탈출 프로젝트</h1>
  <h3>음모론 및 가짜뉴스 판별 AI 데모</h3>
  <p style="color:#E74C3C; font-weight:bold;">⚠️ 교육용 데모입니다.</p>
</div>'''

EXAMPLES = [
    ["2024년 4월 개기일식 때 지구에서 관측된 태양 코로나 모습은 진짜 경이롭더라."],
    ["아폴로 달 착륙 영상에서 별 하나도 안 보이는 거 팩트잖아. 스튜디오 세트장인 거 다 아는 사실 아님?"],
    ["물의 수평 유지 성질 알지? 바다 표면이 둥글게 휘어져 있다는 건 물리학적으로 완전 모순임."],
    ["학교 물리 동아리에서 NASA 오픈 API로 지구 근접 소행성 궤도 시뮬레이션 돌려봤음."],
]

with gr.Blocks(title="래빗홀 탈출 — 가짜뉴스 판별 AI") as demo:
    gr.HTML(HEADER)
    with gr.Tabs():
        with gr.TabItem("🔍 실시간 판별기"):
            gr.Markdown("### 텍스트를 입력하면 AI가 정상/위험(음모론) 여부를 판별합니다.")
            with gr.Row():
                with gr.Column(scale=3):
                    inp = gr.Textbox(label="📝 판별할 문장", placeholder="문장을 입력하세요…", lines=3)
                    btn = gr.Button("🔍 판별 시작", variant="primary", size="lg")
                with gr.Column(scale=2):
                    out_label = gr.Label(label="📊 결과", num_top_classes=2)
                    out_verdict = gr.Textbox(label="📋 판정", lines=1)
                    out_detail = gr.Textbox(label="💡 안내", lines=2)
            btn.click(classify, inp, [out_label, out_verdict, out_detail])
            gr.Examples(examples=EXAMPLES, inputs=inp)
            gr.Markdown("> ⚠️ **한계 고지:** 소규모 데이터 학습, 풍자·반어법 취약, 도메인 한정. 결과를 맹신하지 마세요.")
        with gr.TabItem("📄 Model Card"):
            gr.Markdown(MODEL_CARD)

demo.queue()

demo.launch(
    server_name="0.0.0.0",
    server_port=7860,
    ssr_mode=False
)