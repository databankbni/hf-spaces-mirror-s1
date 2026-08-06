using Microsoft.AspNetCore.Mvc;
using Portfilio_Site.Models;
using System.Collections.Generic;

namespace Portfilio_Site.Controllers
{
    public class HomeController : Controller
    {
        public IActionResult Index()
        {
            var myProjects = new List<ProjectModel>
            {
                // 1. RepoMind AI (Has Live URL)
                new ProjectModel
                {
                    Id = 1,
                    Title = "RepoMind AI",
                    Description = "A FastAPI-based RAG system that ingests any GitHub repo, chunks code by function/class via AST parsing, and answers natural-language questions about the codebase using an LLM grounded strictly in retrieved code context.",
                    TechStack = "Python, FastAPI, RAG, AST, LLMs",
                    GithubLink = "https://github.com/Py-saqlain/RepoMind_AI",
                    LiveUrl = "https://py-saqlain-repomindai.hf.space"
                },

                // 2. LiveDineAI (Has Live URL)
                new ProjectModel
                {
                    Id = 2,
                    Title = "LiveDineAI",
                    Description = "Built a production-style multi-agent voice AI system handling real-time restaurant reservations and orders with automatic failover across 3 TTS providers; deployed backend + frontend live on LiveKit Cloud and Vercel.",
                    TechStack = "LiveKit, Groq, ElevenLabs, Vercel",
                    GithubLink = "https://github.com/Py-saqlain/livekit-restaurant-assistant",
                    LiveUrl = "https://restaurant-frontend-azure-gamma.vercel.app"
                },

                // 3. Customer Support Bot (Has Live URL)
                new ProjectModel
                {
                    Id = 3,
                    Title = "Customer Support Bot",
                    Description = "Built a production-ready customer support chatbot with multi-turn memory and intent-aware responses using LangChain and GroqAPI & Integrated FAISS vector store for FAQ retrieval. Deployed live on Streamlit.",
                    TechStack = "Python, LangChain, GroqAPI, Streamlit, FAISS",
                    GithubLink = "https://github.com/Py-saqlain/Customer-support-bot",
                    LiveUrl = "https://customer-churn-prediction-system-nqg2wr94tftck9v5rag7dc.streamlit.app"
                },

                // 4. Movie Recap App (GitHub Only)
                new ProjectModel
                {
                    Id = 4,
                    Title = "Movie Recap App",
                    Description = "Built end-to-end RAG pipeline automating scene detection and recap generation from raw video using semantic content analysis. Integrated FAISS vector storage for scene embedding retrieval.",
                    TechStack = "Python, Langchain, RAG, FAISS",
                    GithubLink = "https://github.com/Py-saqlain/Movie_Recap"
                },

                // 5. Trendora E-commerce App (GitHub Only)
                new ProjectModel
                {
                    Id = 5,
                    Title = "Trendora E-commerce App",
                    Description = "A fast and responsive e-commerce platform built for modern online Clothing shopping, implemented with MVC structure, HTML5, Bootstrap and SignalR for live notifications.",
                    TechStack = "C#, ASP.NET Core MVC, SignalR",
                    GithubLink = "https://github.com/Py-saqlain/Trendora-.NET-Project"
                },

                // 6. Personal Chat Bot (GitHub Only)
                new ProjectModel
                {
                    Id = 6,
                    Title = "Personal Chat Bot",
                    Description = "Developed multi-turn conversational agent with persistent long-term memory using LangChain memory modules and vector storage. Demonstrated 90%+ contextual accuracy across sessions in manual evaluation.",
                    TechStack = "Python, LangChain, GroqAPI",
                    GithubLink = "https://github.com/Py-saqlain/Personal-Chat-Assistant"
                },

                // 7. FoodFrenzy (GitHub Only)
                new ProjectModel
                {
                    Id = 7,
                    Title = "FoodFrenzy",
                    Description = "A fully functional Online Food Delivery Application developed with ASP.NET MVC 5, incorporating the Code-First approach. Implements MVC architecture to separate business logic from UI, featuring Entity Framework for data management.",
                    TechStack = "C#, ASP.NET MVC 5, Entity Framework",
                    GithubLink = "https://github.com/Py-saqlain/FoodFrenzy"
                },

                // 8. HAR Deep Learning Model (GitHub Only)
                new ProjectModel
                {
                    Id = 8,
                    Title = "AI Triage System",
                    Description = "An intelligent support agent built with Python and the Groq Llama 3.1 model. This system acts as a reasoning engine to route customer queries, retrieve policy information from a knowledge base, and prioritize support tickets using a weighted logic system.",
                    TechStack = "Python, RAG, GroqAPI, LangChain",
                    GithubLink = "https://github.com/Py-saqlain/ai-support-triage-assistant"
                }
            };

            // Certificates List (Strongly-Typed via Model)
            var myCertificates = new List<CertificationModel>
            {
                new CertificationModel { Id = 1, Title = "Docker Essentials : A developer's Introduction", IssuingOrganization = "IBM", CredentialUrl = "https://courses.cognitiveclass.ai/certificates/1eb62d6f87ae47bebef335600b1677b0" },
                new CertificationModel { Id = 2, Title = "Huggingface Agents Course", IssuingOrganization = "Huggingface", CredentialUrl = "https://cas-bridge.xethub.hf.co/xet-bridge-us/6800ea554845e4edbca48825/1f933943ef43544c9db68353326c86b4a68463a9564d2a32f851a5763fcbdf4e?Expires=1783780576&Policy=eyJTdGF0ZW1lbnQiOlt7IlJlc291cmNlIjoiaHR0cHM6Ly9jYXMtYnJpZGdlLnhldGh1Yi5oZi5jby94ZXQtYnJpZGdlLXVzLzY4MDBlYTU1NDg0NWU0ZWRiY2E0ODgyNS8xZjkzMzk0M2VmNDM1NDRjOWRiNjgzNTMzMjZjODZiNGE2ODQ2M2E5NTY0ZDJhMzJmODUxYTU3NjNmY2JkZjRlKiIsIkNvbmRpdGlvbiI6eyJEYXRlTGVzc1RoYW4iOnsiQVdTOkVwb2NoVGltZSI6MTc4Mzc4MDU3Nn19fV19&Signature=MEUCIQCAPp2LGhShvq73TOZ2PqrGtOvQQrytFByXhzjBj15r8gIgWj6g6L9tvZCyo-oGnTSPgOq-ErerVSRqCVkyvP8idLM_&Key-Pair-Id=K1LYXO563TGWFU&X-Xet-Cas-Uid=69c39badcb293e5c628c9ce1&response-content-type=image%2Fpng&response-content-disposition=inline%3B+filename*%3DUTF-8%27%272026-06-08.png%3B+filename%3D\"2026-06-08.png\"%3B&X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=cas%2F20260711%2Fus-east-1%2Fs3%2Faws4_request&X-Amz-Date=20260711T133616Z&X-Amz-Expires=3600&X-Amz-SignedHeaders=host&X-Amz-Signature=1c123286e26b02e88e730a26dde3dbdc52cbe5cff3c5708f607aee6530826fe0" },
                new CertificationModel { Id = 3, Title = "Prompt Engineering for Everyone", IssuingOrganization = "IBM", CredentialUrl = "https://courses.cognitiveclass.ai/certificates/73051fc2217c4d7495be98e64e0eecea" }
            };

            // Internships List (Strongly-Typed via InternshipModel)
            var myInternships = new List<InternshipModel>
            {
                new InternshipModel
                {
                    Role = "AI Engineer Intern",
                    Company = "Senarios",
                    Duration = "June 2025 - Present",
                    Description = "Building real-time voice AI agents at Senarios using LiveKit, Groq (Whisper STT, Llama 3.3 70B), and Cartesia TTS, with Silero VAD."
                },
                new InternshipModel
                {
                    Role = "AI Engineer Intern",
                    Company = "Decode Labs",
                    Duration = "May 2026 - June 2026",
                    Description = "Contributed to Python-based AI development projects, working across the full pipeline from data handling and model integration to building and testing intelligent application features."
                },
                new InternshipModel
                {
                    Role = "ML Engineer Intern",
                    Company = "Teyzix",
                    Duration = "Jan 2026 - March 2026",
                    Description = "Implemented Machine Learning Algorithms, Feature Engineering and Neural Networks to real world projects."
                }
            };

            // Package the strongly-typed objects into the ViewBag
            ViewBag.Certifications = myCertificates;
            ViewBag.Internships = myInternships;

            return View(myProjects);
        }

        public IActionResult About()
        {
            return View();
        }
    }
}