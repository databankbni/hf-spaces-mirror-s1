from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, black, white
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, HRFlowable,
    KeepTogether, ListFlowable, ListItem
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus.tableofcontents import TableOfContents

# ── Page Setup ──────────────────────────────────────────────
output_file = "/home/cyber-force/AI/Research Agent/Danyal_Mudassar_CV.pdf"
doc = SimpleDocTemplate(
    output_file,
    pagesize=letter,
    topMargin=0.6*inch,
    bottomMargin=0.5*inch,
    leftMargin=0.75*inch,
    rightMargin=0.75*inch,
)

# ── Colour Palette ─────────────────────────────────────────
DARK_NAVY   = HexColor("#1B2A4A")
ACCENT_BLUE = HexColor("#2E5090")
MID_GRAY    = HexColor("#555555")
LIGHT_GRAY  = HexColor("#E0E0E0")
BULLET_CLR  = HexColor("#2E5090")

# ── Custom Styles ──────────────────────────────────────────
styles = getSampleStyleSheet()

styles.add(ParagraphStyle(
    name='NameHeader',
    fontName='Helvetica-Bold',
    fontSize=24,
    leading=28,
    textColor=DARK_NAVY,
    alignment=TA_CENTER,
    spaceAfter=2,
))

styles.add(ParagraphStyle(
    name='SubHeader',
    fontName='Helvetica',
    fontSize=12,
    leading=16,
    textColor=ACCENT_BLUE,
    alignment=TA_CENTER,
    spaceAfter=4,
))

styles.add(ParagraphStyle(
    name='ContactLine',
    fontName='Helvetica',
    fontSize=9.5,
    leading=14,
    textColor=MID_GRAY,
    alignment=TA_CENTER,
    spaceAfter=2,
))

styles.add(ParagraphStyle(
    name='SectionHead',
    fontName='Helvetica-Bold',
    fontSize=13,
    leading=18,
    textColor=DARK_NAVY,
    spaceBefore=14,
    spaceAfter=6,
))

styles.add(ParagraphStyle(
    name='SubSectionHead',
    fontName='Helvetica-BoldOblique',
    fontSize=10.5,
    leading=14,
    textColor=ACCENT_BLUE,
    spaceBefore=8,
    spaceAfter=4,
))

styles.add(ParagraphStyle(
    name='BodyText2',
    fontName='Helvetica',
    fontSize=10,
    leading=14,
    textColor=black,
    alignment=TA_LEFT,
    spaceAfter=4,
))

styles.add(ParagraphStyle(
    name='BulletStyle',
    fontName='Helvetica',
    fontSize=9.5,
    leading=13,
    leftIndent=18,
    bulletIndent=6,
    textColor=black,
    spaceAfter=3,
    bulletFontName='Helvetica-Bold',
    bulletFontSize=10,
    bulletColor=BULLET_CLR,
))

styles.add(ParagraphStyle(
    name='CertEntry',
    fontName='Helvetica',
    fontSize=9.5,
    leading=13,
    leftIndent=12,
    textColor=black,
    spaceAfter=3,
))

# ── Story Building ─────────────────────────────────────────
story = []

# ── HEADER ─────────────────────────────────────────────────
story.append(Paragraph("Danyal Mudassar", styles['NameHeader']))
story.append(Paragraph("Offensive Security &amp; AI Automation Enthusiast", styles['SubHeader']))
story.append(Paragraph(
    "Pakistan (Remote-Ready)  |  Email: [Your Email]  |  LinkedIn: [Your Link]  |  GitHub: [Your Link]",
    styles['ContactLine']
))
story.append(Spacer(1, 6))
story.append(HRFlowable(width="100%", thickness=2, color=ACCENT_BLUE, spaceAfter=6))

# ── PROFESSIONAL SUMMARY ───────────────────────────────────
story.append(Paragraph("PROFESSIONAL SUMMARY", styles['SectionHead']))
story.append(HRFlowable(width="100%", thickness=0.8, color=LIGHT_GRAY, spaceAfter=8))
story.append(Paragraph(
    "Highly motivated <b>BS IT student</b> with a strong and growing portfolio of "
    "<b>30+ industry-recognized certifications</b> in cybersecurity, ethical hacking, and AI. "
    "Actively exploring <b>autonomous AI agent systems</b> and agentic workflows "
    "using OpenAI and IBM frameworks. Passionate about the safe use of data and GenAI through "
    "automation and adversarial simulation.",
    styles['BodyText2']
))

# ── CORE TECHNICAL SKILLS ──────────────────────────────────
story.append(Paragraph("CORE TECHNICAL SKILLS", styles['SectionHead']))
story.append(HRFlowable(width="100%", thickness=0.8, color=LIGHT_GRAY, spaceAfter=8))

skills = [
    "<b>AI &amp; Machine Learning:</b> AI Agent Development, LLMOps, Generative AI for Automation, RAG, Model Context Protocol (MCP)",
    "<b>Data Security &amp; Privacy:</b> Google Cybersecurity Professional, ISC2 SSCP, Certified in Cybersecurity, Healthcare Security",
    "<b>Offensive Security:</b> Ethical Hacking, Web Hacking, Penetration Testing, Kali Linux, Vulnerability Assessment",
    "<b>Automation &amp; Cloud:</b> Python 3, Google IT Automation, Bash, PowerShell, TCP/IP, Network Protocols",
    "<b>Tools:</b> Metasploit, Nmap, Wireshark, Burp Suite, SQLMap, Cisco Networking Academy tools",
]
for s in skills:
    story.append(Paragraph(f"<bullet>&bull;</bullet>  {s}", styles['BulletStyle']))

# ── EDUCATION ──────────────────────────────────────────────
story.append(Paragraph("EDUCATION", styles['SectionHead']))
story.append(HRFlowable(width="100%", thickness=0.8, color=LIGHT_GRAY, spaceAfter=8))
story.append(Paragraph(
    "<b>BS in Information Technology</b> (In Progress)<br/>"
    "Virtual University of Pakistan",
    styles['BodyText2']
))

# ── KEY CERTIFICATIONS ─────────────────────────────────────
story.append(Paragraph("KEY CERTIFICATIONS", styles['SectionHead']))
story.append(HRFlowable(width="100%", thickness=0.8, color=LIGHT_GRAY, spaceAfter=8))

story.append(Paragraph("AI Agent Development &amp; GenAI Safety", styles['SubSectionHead']))
ai_certs = [
    "<b>AI Agent Developer Specialization</b> — Vanderbilt University",
    "<b>IBM RAG and Agentic AI</b> — IBM via Coursera",
    "<b>Building AI Agents with OpenAI</b> — Edureka via Coursera",
    "<b>Model Context Protocol (MCP) Mastery</b> — Fractal Analytics via Coursera",
    "<b>Large Language Model Operations (LLMOps)</b> — Duke University via Coursera",
]
for c in ai_certs:
    story.append(Paragraph(f"<bullet>&bull;</bullet>  {c}", styles['CertEntry']))

story.append(Paragraph("Cybersecurity &amp; Data Governance", styles['SubSectionHead']))
sec_certs = [
    "<b>Systems Security Certified Practitioner (SSCP)</b> — ISC2 via Coursera",
    "<b>Google Cybersecurity Professional Certificate</b> — Google via Coursera",
    "<b>Ethical Hacker</b> — Cisco Networking Academy",
    "<b>Computer Forensics</b> — InfoSec Institute via Coursera",
]
for c in sec_certs:
    story.append(Paragraph(f"<bullet>&bull;</bullet>  {c}", styles['CertEntry']))

# ── TECHNICAL PROJECTS & TRAINING ──────────────────────────
story.append(Paragraph("TECHNICAL PROJECTS &amp; TRAINING", styles['SectionHead']))
story.append(HRFlowable(width="100%", thickness=0.8, color=LIGHT_GRAY, spaceAfter=8))

projects = [
    "<b>Autonomous AI Agent Orchestration:</b> Built and managed agentic workflows using OpenAI and IBM frameworks to automate complex data tasks.",
    "<b>Adversarial Simulation:</b> Demonstrated ability to describe tactics, techniques, and procedures (TTPs) used by cybercriminals to bypass data controls.",
    "<b>Google IT Automation:</b> Leveraged Python to automate system administration and network security tasks.",
    "<b>Cyber Scouts Training:</b> Completed intensive 7-day training focused on cybersecurity awareness and defending network components.",
]
for p in projects:
    story.append(Paragraph(f"<bullet>&bull;</bullet>  {p}", styles['BulletStyle']))

# ── PROFESSIONAL MEMBERSHIPS & HONORS ──────────────────────
story.append(Paragraph("PROFESSIONAL MEMBERSHIPS &amp; HONORS", styles['SectionHead']))
story.append(HRFlowable(width="100%", thickness=0.8, color=LIGHT_GRAY, spaceAfter=8))

memberships = [
    "<b>Contributor:</b> Cyber Security of Pakistan Initiative",
    "<b>Alumnus:</b> Cisco Networking Academy",
    "<b>Recipient:</b> Multiple Coursera Specializations in Business AI and Startup Entrepreneurship",
]
for m in memberships:
    story.append(Paragraph(f"<bullet>&bull;</bullet>  {m}", styles['BulletStyle']))

# ── FOOTER LINE ────────────────────────────────────────────
story.append(Spacer(1, 14))
story.append(HRFlowable(width="100%", thickness=1.5, color=ACCENT_BLUE, spaceAfter=6))
story.append(Paragraph(
    "<i>References and portfolio available upon request.</i>",
    ParagraphStyle('Footer', fontName='Helvetica-Oblique', fontSize=8,
                   textColor=MID_GRAY, alignment=TA_CENTER)
))

# ── Build ──────────────────────────────────────────────────
doc.build(story)
print(f"PDF saved to: {output_file}")
