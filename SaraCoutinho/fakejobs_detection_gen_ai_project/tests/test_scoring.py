import unittest

from app.scoring import evaluate_job


class ScoringEngineTest(unittest.TestCase):
    def test_brazilian_payment_scam_gets_high_risk(self):
        result = evaluate_job(
            {
                "title": "Auxiliar Administrativo Home Based",
                "description": "Contratacao imediata. Envie PIX de taxa de cadastro hoje.",
                "company_profile": "",
                "salary_range": "18000",
                "required_education": "High School",
                "required_experience": "Entry level",
                "function": "Administrative",
                "canal_contato": "recrutador@gmail.com",
                "has_company_logo": False,
                "has_questions": False,
            }
        )

        codes = {flag["codigo"] for flag in result["red_flags"]}
        self.assertEqual(result["veredito"], "provavel_golpe")
        self.assertIn("COBRANCA_ANTECIPADA", codes)
        self.assertIn("CANAL_GENERICO", codes)

    def test_legitimate_complete_job_stays_low_risk(self):
        result = evaluate_job(
            {
                "title": "Backend Developer",
                "description": "We are hiring a backend developer to build APIs, improve observability, collaborate with product teams, and maintain reliable services across the platform.",
                "company_profile": "A software company with public website, engineering culture, and established product.",
                "salary_range": "7000-9500",
                "required_education": "Bachelor's",
                "required_experience": "Mid-Senior level",
                "function": "Engineering",
                "canal_contato": "jobs@empresa.com",
                "has_company_logo": True,
                "has_questions": True,
                "location": "Sao Paulo",
                "industry": "Technology",
                "benefits": "Health plan and remote work",
            }
        )

        self.assertEqual(result["veredito"], "provavel_legitima")
        self.assertLess(result["score_risco"], 30)

    def test_short_ambiguous_job_is_attention_not_fraud(self):
        result = evaluate_job(
            {
                "title": "Atendente",
                "description": "Vaga para atendimento ao cliente.",
                "company_profile": "",
                "salary_range": "1800",
                "has_company_logo": True,
                "has_questions": False,
            }
        )

        self.assertEqual(result["veredito"], "atencao")

    def test_reposted_known_scam_adds_specific_flag(self):
        job = {
            "title": "Assistente remoto",
            "description": "Contratação imediata para assistente remoto. Envie PIX para liberar o cadastro.",
            "company_profile": "",
            "has_company_logo": False,
            "has_questions": False,
        }
        history = [
            {
                "title": "Assistente remoto",
                "description": "Contratação imediata para assistente remoto. Envie PIX para liberar o cadastro.",
                "criado_em": "2026-07-15T12:00:00+00:00",
            }
        ]

        result = evaluate_job(job, historico_golpes=history)

        flags = {flag["codigo"]: flag for flag in result["red_flags"]}
        self.assertIn("REPOSTAGEM_DE_GOLPE_CONHECIDO", flags)
        self.assertIn("100% similar", flags["REPOSTAGEM_DE_GOLPE_CONHECIDO"]["trecho_evidencia"])


if __name__ == "__main__":
    unittest.main()
