import gradio as gr
from openai import OpenAI

client = OpenAI(
    api_key="s2_1845d4f94c334049be9ad8c273c5ad03",
    base_url="https://routellm.abacus.ai/v1"
)

SYSTEM_PROMPT = """
You are a Women's Postpartum Weight Management and Nutrition Coach.

Your goal is to create a personalized, practical, and safe postpartum wellness plan.

Collect and use the following information:
- Age
- Height (cm)
- Current Weight (kg)
- Target Weight (kg)
- Number of Deliveries
- Gap Between Deliveries
- Date of Last Delivery
- Delivery Type (Normal/C-Section)
- Breastfeeding Status
- Health Issues
- Profession
- Daily Working Hours
- Preferred Exercise
- Daily Exercise Time

Instructions:

1. Suggest a safe weight-loss target.
2. Estimate approximately how many months it may take to reach the target weight based on healthy weight-loss rates. Make it clear this is only an estimate.
3. Recommend ONLY homemade vegetarian meals.
4. Include protein-rich vegetarian foods.
5. Do NOT recommend supplements, protein powders, injections, or crash diets.
6. Suggest hydration and sleep recommendations.
7. Recommend exercises based on the user's selected activity.
8. Modify recommendations according to profession (working woman, homemaker, teacher, IT employee, etc.).
9. Give weekly exercise recommendations.
10. Suggest lifelong healthy habits for maintaining weight.
11. If there are significant health conditions or a recent delivery, advise consulting a doctor before beginning any new diet or exercise routine.
12. Keep the response encouraging and easy to follow.

Structure the response with headings.
"""

def generate_plan(
    age,
    height,
    current_weight,
    target_weight,
    deliveries,
    gap,
    delivery_date,
    delivery_type,
    breastfeeding,
    health,
    profession,
    work_hours,
    exercise,
    exercise_time,
):

    prompt = f"""
Age: {age}

Height: {height} cm

Current Weight: {current_weight} kg

Target Weight: {target_weight} kg

Number of Deliveries: {deliveries}

Gap Between Deliveries: {gap}

Date of Last Delivery: {delivery_date}

Delivery Type: {delivery_type}

Breastfeeding: {breastfeeding}

Health Issues: {health}

Profession: {profession}

Working Hours Per Day: {work_hours}

Preferred Exercise: {exercise}

Daily Exercise Time: {exercise_time} minutes
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role":"system","content":SYSTEM_PROMPT},
            {"role":"user","content":prompt}
        ],
        temperature=0.4
    )

    return response.choices[0].message.content


demo = gr.Interface(
    fn=generate_plan,
    inputs=[
        gr.Number(label="Age"),
        gr.Number(label="Height (cm)"),
        gr.Number(label="Current Weight (kg)"),
        gr.Number(label="Target Weight (kg)"),
        gr.Number(label="Number of Deliveries"),
        gr.Textbox(label="Gap Between Deliveries (Example: 3 Years)"),
        gr.Textbox(label="Date of Last Delivery"),
        gr.Dropdown(
            ["Normal Delivery","C-Section"],
            label="Delivery Type"
        ),
        gr.Radio(
            ["Yes","No"],
            label="Currently Breastfeeding?"
        ),
        gr.Textbox(
            label="Health Issues",
            placeholder="Example: Thyroid, PCOS, Diabetes, None"
        ),
        gr.Textbox(
            label="Profession",
            placeholder="Example: Software Engineer, Teacher, Homemaker"
        ),
        gr.Number(label="Working Hours Per Day"),
        gr.Dropdown(
            [
                "Walking",
                "Yoga",
                "Gym",
                "Swimming",
                "Cardio",
                "Weight Training",
                "Zumba"
            ],
            label="Preferred Exercise"
        ),
        gr.Slider(
            minimum=15,
            maximum=120,
            value=30,
            step=5,
            label="Exercise Time Per Day (Minutes)"
        )
    ],
    outputs=gr.Textbox(
        lines=30,
        label="Personalized Postpartum Wellness Plan"
    ),
    title="👩‍🍼 AI Postpartum Weight Management & Diet Planner",
    description="""
Get a personalized postpartum wellness plan based on your lifestyle.
This tool provides general wellness information and is not a substitute for professional medical advice.
"""
)

demo.launch()