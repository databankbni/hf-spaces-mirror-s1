const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun,
  AlignmentType, BorderStyle, HeadingLevel, LevelFormat,
  PageBreak, PageOrientation, TabStopType, TabStopPosition,
  TabStopLeader, ShadingType, WidthType,
} = require("docx");

const DXA_PER_INCH = 1440;

// ── Colours ──
const DARK_NAVY  = "1B2A4A";
const ACCENT_BLUE = "2E5090";
const MID_GRAY   = "555555";
const LIGHT_GRAY = "E0E0E0";

// ── Helpers ──
function hr(color, size = 6, space = 40) {
  return new Paragraph({
    border: { bottom: { style: BorderStyle.SINGLE, size, color, space } },
    spacing: { after: space },
  });
}

function sectionHeading(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1,
    children: [new TextRun({ text: text, color: DARK_NAVY, size: 30, bold: true })],
    spacing: { before: 260, after: 80 },
  });
}

function subHeading(text) {
  return new Paragraph({
    children: [new TextRun({ text, bold: true, italics: true, color: ACCENT_BLUE, size: 22 })],
    spacing: { before: 160, after: 60 },
  });
}

function body(text) {
  return new Paragraph({
    children: [new TextRun({ text, size: 20, color: "000000" })],
    spacing: { after: 60 },
  });
}

function bullet(text) {
  return new Paragraph({
    numbering: { reference: "bullets", level: 0 },
    children: [new TextRun({ text, size: 19, color: "000000" })],
    spacing: { after: 30 },
  });
}

function certItem(parts) {
  // parts = [{ text, bold? }, ...]
  const runs = parts.map((p) =>
    new TextRun({
      text: p.text,
      size: 19,
      color: "000000",
      bold: p.bold || false,
    })
  );
  return new Paragraph({
    children: runs,
    spacing: { after: 30 },
    indent: { left: 360 },
  });
}

function contactLine(text) {
  return new Paragraph({
    children: [new TextRun({ text, size: 19, color: MID_GRAY })],
    alignment: AlignmentType.CENTER,
    spacing: { after: 40 },
  });
}

// ── Document ──
const doc = new Document({
  styles: {
    default: {
      document: { run: { font: "Calibri", size: 22 } },
      paragraphStyles: [
        {
          id: "Heading1",
          name: "Heading 1",
          basedOn: "Normal",
          next: "Normal",
          quickFormat: true,
          run: { font: "Calibri", size: 26, bold: true, color: DARK_NAVY },
          paragraph: { spacing: { before: 260, after: 80 } },
        },
      ],
    },
  },
  numbering: {
    config: [
      {
        reference: "bullets",
        levels: [
          {
            level: 0,
            format: LevelFormat.BULLET,
            text: "\u2022",
            alignment: AlignmentType.LEFT,
            style: {
              paragraph: { indent: { left: 720, hanging: 360 } },
            },
          },
        ],
      },
    ],
  },
  sections: [
    {
      properties: {
        page: {
          size: {
            width: 12240,
            height: 15840,
          },
          margin: { top: 1.0 * DXA_PER_INCH, right: 1.0 * DXA_PER_INCH, bottom: 0.8 * DXA_PER_INCH, left: 1.0 * DXA_PER_INCH },
        },
      },
      children: [
        // ── Name Header ──
        new Paragraph({
          children: [new TextRun({ text: "Danyal Mudassar", size: 40, bold: true, color: DARK_NAVY })],
          alignment: AlignmentType.CENTER,
          spacing: { after: 40 },
        }),
        new Paragraph({
          children: [new TextRun({ text: "Offensive Security & AI Automation Enthusiast", size: 24, color: ACCENT_BLUE })],
          alignment: AlignmentType.CENTER,
          spacing: { after: 60 },
        }),
        contactLine("Pakistan (Remote-Ready)  |  Email: [Your Email]  |  LinkedIn: [Your Link]  |  GitHub: [Your Link]"),
        hr(ACCENT_BLUE, 10, 80),

        // ── Professional Summary ──
        sectionHeading("PROFESSIONAL SUMMARY"),
        hr(LIGHT_GRAY, 2, 60),
        body(
          "Highly motivated BS IT student with a strong and growing portfolio of " +
          "30+ industry-recognized certifications in cybersecurity, ethical hacking, and AI. " +
          "Actively exploring autonomous AI agent systems and agentic workflows " +
          "using OpenAI and IBM frameworks. Passionate about the safe use of data and GenAI through " +
          "automation and adversarial simulation."
        ),

        // ── Core Technical Skills ──
        sectionHeading("CORE TECHNICAL SKILLS"),
        hr(LIGHT_GRAY, 2, 60),
        bullet(
          "AI & Machine Learning: AI Agent Development, LLMOps, Generative AI for Automation, RAG, Model Context Protocol (MCP)"
        ),
        bullet(
          "Data Security & Privacy: Google Cybersecurity Professional, ISC2 SSCP, Certified in Cybersecurity, Healthcare Security"
        ),
        bullet(
          "Offensive Security: Ethical Hacking, Web Hacking, Penetration Testing, Kali Linux, Vulnerability Assessment"
        ),
        bullet(
          "Automation & Cloud: Python 3, Google IT Automation, Bash, PowerShell, TCP/IP, Network Protocols"
        ),
        bullet(
          "Tools: Metasploit, Nmap, Wireshark, Burp Suite, SQLMap, Cisco Networking Academy tools"
        ),

        // ── Education ──
        sectionHeading("EDUCATION"),
        hr(LIGHT_GRAY, 2, 60),
        new Paragraph({
          children: [
            new TextRun({ text: "BS in Information Technology (In Progress)", size: 20, bold: true }),
          ],
          spacing: { after: 40 },
        }),
        new Paragraph({
          children: [new TextRun({ text: "Virtual University of Pakistan", size: 20, color: "000000" })],
          spacing: { after: 60 },
        }),

        // ── Key Certifications ──
        sectionHeading("KEY CERTIFICATIONS"),
        hr(LIGHT_GRAY, 2, 60),

        subHeading("AI Agent Development & GenAI Safety"),
        certItem([{ text: "AI Agent Developer Specialization", bold: true }, { text: " \u2014 Vanderbilt University" }]),
        certItem([{ text: "IBM RAG and Agentic AI", bold: true }, { text: " \u2014 IBM via Coursera" }]),
        certItem([{ text: "Building AI Agents with OpenAI", bold: true }, { text: " \u2014 Edureka via Coursera" }]),
        certItem([{ text: "Model Context Protocol (MCP) Mastery", bold: true }, { text: " \u2014 Fractal Analytics via Coursera" }]),
        certItem([{ text: "Large Language Model Operations (LLMOps)", bold: true }, { text: " \u2014 Duke University via Coursera" }]),

        subHeading("Cybersecurity & Data Governance"),
        certItem([{ text: "Systems Security Certified Practitioner (SSCP)", bold: true }, { text: " \u2014 ISC2 via Coursera" }]),
        certItem([{ text: "Google Cybersecurity Professional Certificate", bold: true }, { text: " \u2014 Google via Coursera" }]),
        certItem([{ text: "Ethical Hacker", bold: true }, { text: " \u2014 Cisco Networking Academy" }]),
        certItem([{ text: "Computer Forensics", bold: true }, { text: " \u2014 InfoSec Institute via Coursera" }]),

        // ── Technical Projects & Training ──
        sectionHeading("TECHNICAL PROJECTS & TRAINING"),
        hr(LIGHT_GRAY, 2, 60),
        bullet(
          "Autonomous AI Agent Orchestration: Built and managed agentic workflows using OpenAI and IBM frameworks to automate complex data tasks."
        ),
        bullet(
          "Adversarial Simulation: Demonstrated ability to describe tactics, techniques, and procedures (TTPs) used by cybercriminals to bypass data controls."
        ),
        bullet(
          "Google IT Automation: Leveraged Python to automate system administration and network security tasks."
        ),
        bullet(
          "Cyber Scouts Training: Completed intensive 7-day training focused on cybersecurity awareness and defending network components."
        ),

        // ── Professional Memberships & Honors ──
        sectionHeading("PROFESSIONAL MEMBERSHIPS & HONORS"),
        hr(LIGHT_GRAY, 2, 60),
        bullet("Contributor: Cyber Security of Pakistan Initiative"),
        bullet("Alumnus: Cisco Networking Academy"),
        bullet("Recipient: Multiple Coursera Specializations in Business AI and Startup Entrepreneurship"),

        // ── Footer ──
        new Paragraph({
          spacing: { before: 200 },
          border: { top: { style: BorderStyle.SINGLE, size: 10, color: ACCENT_BLUE, space: 60 } },
        }),
        new Paragraph({
          children: [new TextRun({ text: "References and portfolio available upon request.", italics: true, size: 16, color: MID_GRAY })],
          alignment: AlignmentType.CENTER,
          spacing: { before: 60 },
        }),
      ],
    },
  ],
});

const outputPath = "/home/cyber-force/AI/Research Agent/Danyal_Mudassar_CV.docx";
Packer.toBuffer(doc).then((buffer) => {
  fs.writeFileSync(outputPath, buffer);
  console.log(`DOCX saved to: ${outputPath}`);
});
