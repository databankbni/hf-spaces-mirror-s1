import os
import json
import gradio as gr
import groq
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
api_key = os.getenv("GROQ_API_KEY")
if not api_key:
    raise ValueError("GROQ_API_KEY not found in environment variables")

# Initialize Groq client
client = groq.Client(api_key=api_key)

# Model is configurable via env var; defaults to a current Groq production model.
MODEL_NAME = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")


def get_completion(prompt, model=MODEL_NAME, temperature=0):
    """Get a JSON chat completion from the Groq API."""
    chat_completion = client.chat.completions.create(
        messages=[{"role": "user", "content": prompt}],
        model=model,
        temperature=temperature,
        response_format={"type": "json_object"},  # Groq JSON mode
    )
    return chat_completion.choices[0].message.content


def validate_inputs(inputs):
    """Validate the input parameters."""
    if len(inputs) != 10:
        return False, "Please provide exactly 10 comma-separated values."

    try:
        # Validate numeric fields (everything except loan purpose at index 0)
        numeric_fields = inputs[1:6] + inputs[7:]
        [float(x) for x in numeric_fields]  # Test conversion
    except ValueError:
        return False, "Non-numeric values found in numeric fields."

    return True, None


def scheme(input_text):
    """Main function to process a loan scheme request. Returns a JSON object."""
    # Convert input string to a list and strip whitespace
    inputs = [x.strip() for x in input_text.split(",")]

    # Validate inputs
    is_valid, error_msg = validate_inputs(inputs)
    if not is_valid:
        return {"error": error_msg}

    # Unpack inputs
    (
        loan_purpose, age, income, cibil_score, experience,
        loan_amt, loan_tenure, assets, property_value, vehicle_cost
    ) = inputs

    prompt = f'''
    You are a loan advisor. Based on the applicant details below, choose the most
    suitable loan scheme and respond with a single JSON object only.

    Applicant details:
    - Loan purpose: {loan_purpose}
    - Age: {age} years
    - Annual income: {float(income):.2f}
    - CIBIL score: {cibil_score}
    - Employment experience: {experience} years
    - Requested loan amount: {float(loan_amt):.2f}
    - Loan tenure: {loan_tenure} years
    - Assets valuation: {float(assets):.2f}
    - Property value: {float(property_value):.2f}
    - Vehicle cost: {float(vehicle_cost):.2f}

    Choose exactly one scheme from these categories:
    Home Loans, Vehicle Loans, Marriage Loans, Education Loans, Personal Loans.

    Return a JSON object with EXACTLY these keys and nothing else:
    {{
      "scheme": "<selected scheme name>",
      "explanation": "<concise reason, 100 words maximum>",
      "loan_details": {{
        "loan_amount": <number: loan principal, no currency symbol or commas>,
        "loan_tenure": <number: tenure in years>,
        "interest_rate": "<approximate annual interest rate as a string, e.g. \\"10.5%\\">",
        "emi": <number: monthly EMI, no currency symbol or commas>,
        "total_interest": <number: total interest over the tenure>,
        "total_amount": <number: total amount payable>
      }}
    }}
    Do not include markdown, code fences, or any text outside the JSON object.
    '''

    try:
        raw = get_completion(prompt)
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"error": "The model did not return valid JSON. Please try again."}
    except Exception as e:
        return {"error": f"Error processing request: {str(e)}"}


# Gradio Interface
with gr.Blocks(title="Loan Scheme Advisor") as demo:
    gr.Markdown("""
    # Loan Eligibility and Scheme Suggestion
    Enter your loan details as 10 comma-separated values in this order:
    1. Loan Purpose, 2. Age, 3. Annual Income, 4. CIBIL Score, 5. Work Experience (years),
    6. Loan Amount, 7. Loan Tenure (years), 8. Assets Value, 9. Property Value, 10. Vehicle Cost
    """)

    with gr.Row():
        inputs = gr.Textbox(
            label="Loan Details",
            placeholder="Example: Home, 30, 800000, 750, 5, 500000, 20, 1000000, 7000000, 20000",
            max_lines=1
        )
        submit_btn = gr.Button("Submit")

    outputs = gr.JSON(label="Loan Scheme Recommendation")

    submit_btn.click(
        fn=scheme,
        inputs=inputs,
        outputs=outputs
    )

if __name__ == "__main__":
    demo.launch()
