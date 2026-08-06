import gradio as gr
# ==============================================
# AI Skill Detection & Roadmap Generator
# ==============================================

class User:

    def __init__(self, name, goal, skills, confidence, consistency, adaptability, traits):
        self.name = name
        self.goal = goal
        self.skills = skills
        self.confidence = confidence
        self.consistency = consistency
        self.adaptability = adaptability
        self.traits = traits
# ==============================================
# Career Database
# ==============================================

career_database = {

    "AI Engineer": [
        "Python",
        "Machine Learning",
        "Deep Learning",
        "Data Structures",
        "SQL",
        "TensorFlow",
        "Git"
    ],

    "Data Analyst": [
        "Python",
        "SQL",
        "Excel",
        "Power BI",
        "Statistics",
        "Pandas"
    ],

    "Web Developer": [
        "HTML",
        "CSS",
        "JavaScript",
        "Python",
        "Flask",
        "SQL",
        "Git"
    ],

    "Software Developer": [
        "Python",
        "Java",
        "C++",
        "Data Structures",
        "Algorithms",
        "Git",
        "SQL"
    ],

    "UI/UX Designer": [
        "Figma",
        "Wireframing",
        "Prototyping",
        "User Research",
        "Design Systems",
        "Adobe XD"
    ],

    "Cloud Engineer": [
        "AWS",
        "Azure",
        "Linux",
        "Docker",
        "Kubernetes",
        "Networking",
        "Git"
    ],

    "Cybersecurity Analyst": [
        "Network Security",
        "Linux",
        "Ethical Hacking",
        "Cryptography",
        "SIEM",
        "Python",
        "Risk Assessment"
    ]
}


# ==============================================
# Free Course Database
# ==============================================

course_links = {

    "Python": {
        "platform": "freeCodeCamp",
        "link": "https://www.freecodecamp.org/learn/scientific-computing-with-python/",
        "time": "15 Hours",
        "project": "Build a Calculator"
    },

    "Machine Learning": {
        "platform": "Kaggle Learn",
        "link": "https://www.kaggle.com/learn/intro-to-machine-learning",
        "time": "10 Hours",
        "project": "House Price Prediction"
    },

    "Deep Learning": {
        "platform": "Kaggle Learn",
        "link": "https://www.kaggle.com/learn/intro-to-deep-learning",
        "time": "12 Hours",
        "project": "Image Classification"
    },

    "Data Structures": {
        "platform": "GeeksforGeeks",
        "link": "https://www.geeksforgeeks.org/data-structures/",
        "time": "20 Hours",
        "project": "Student Management System"
    },

    "SQL": {
        "platform": "Kaggle Learn",
        "link": "https://www.kaggle.com/learn/intro-to-sql",
        "time": "8 Hours",
        "project": "Library Database"
    },

    "TensorFlow": {
        "platform": "TensorFlow",
        "link": "https://www.tensorflow.org/tutorials",
        "time": "18 Hours",
        "project": "Digit Recognition"
    },

    "Git": {
        "platform": "GitHub Skills",
        "link": "https://skills.github.com/",
        "time": "5 Hours",
        "project": "Version Control Practice"
    },

    "HTML": {
        "platform": "freeCodeCamp",
        "link": "https://www.freecodecamp.org/learn/2022/responsive-web-design/",
        "time": "12 Hours",
        "project": "Portfolio Website"
    },

    "CSS": {
        "platform": "freeCodeCamp",
        "link": "https://www.freecodecamp.org/learn/2022/responsive-web-design/",
        "time": "12 Hours",
        "project": "Responsive Landing Page"
    },

    "JavaScript": {
        "platform": "freeCodeCamp",
        "link": "https://www.freecodecamp.org/learn/javascript-algorithms-and-data-structures/",
        "time": "25 Hours",
        "project": "Weather App"
    },

    "Flask": {
        "platform": "Flask Documentation",
        "link": "https://flask.palletsprojects.com/",
        "time": "15 Hours",
        "project": "REST API Project"
    },

    "Excel": {
        "platform": "Microsoft Learn",
        "link": "https://learn.microsoft.com/training/",
        "time": "6 Hours",
        "project": "Sales Dashboard"
    },

    "Power BI": {
        "platform": "Microsoft Learn",
        "link": "https://learn.microsoft.com/training/powerplatform/power-bi/",
        "time": "10 Hours",
        "project": "Business Dashboard"
    },

    "Statistics": {
        "platform": "Khan Academy",
        "link": "https://www.khanacademy.org/math/statistics-probability",
        "time": "15 Hours",
        "project": "Data Analysis Report"
    },

    "Pandas": {
        "platform": "Kaggle Learn",
        "link": "https://www.kaggle.com/learn/pandas",
        "time": "10 Hours",
        "project": "CSV Data Cleaning"
    },


    "Java": {
        "platform": "Oracle Java Tutorials",
        "link": "https://docs.oracle.com/javase/tutorial/",
        "time": "20 Hours",
        "project": "Library Management System"
    },

    "C++": {
        "platform": "LearnCpp",
        "link": "https://www.learncpp.com/",
        "time": "20 Hours",
        "project": "Bank Management System"
    },

    "Algorithms": {
        "platform": "GeeksforGeeks",
        "link": "https://www.geeksforgeeks.org/fundamentals-of-algorithms/",
        "time": "25 Hours",
        "project": "Path Finding Visualizer"
    },

    "Figma": {
        "platform": "Figma Learn",
        "link": "https://help.figma.com/",
        "time": "8 Hours",
        "project": "Mobile App Design"
    },

    "Wireframing": {
        "platform": "Coursera",
        "link": "https://www.coursera.org/",
        "time": "6 Hours",
        "project": "Website Wireframe"
    },

    "Prototyping": {
        "platform": "Figma Learn",
        "link": "https://help.figma.com/",
        "time": "8 Hours",
        "project": "Interactive Prototype"
    },

    "AWS": {
        "platform": "AWS Skill Builder",
        "link": "https://explore.skillbuilder.aws/",
        "time": "20 Hours",
        "project": "Deploy Web App"
    },

    "Azure": {
        "platform": "Microsoft Learn",
        "link": "https://learn.microsoft.com/training/azure/",
        "time": "18 Hours",
        "project": "Cloud Infrastructure Setup"
    },

    "Docker": {
        "platform": "Docker Docs",
        "link": "https://docs.docker.com/get-started/",
        "time": "10 Hours",
        "project": "Containerized Flask App"
    },

    "Kubernetes": {
        "platform": "Kubernetes Docs",
        "link": "https://kubernetes.io/docs/tutorials/",
        "time": "20 Hours",
        "project": "Microservices Deployment"
    },

    "Networking": {
        "platform": "Cisco Skills For All",
        "link": "https://skillsforall.com/",
        "time": "15 Hours",
        "project": "Network Design"
    },

    "Network Security": {
        "platform": "Cisco Skills For All",
        "link": "https://skillsforall.com/",
        "time": "12 Hours",
        "project": "Secure Network Setup"
    },

    "Ethical Hacking": {
        "platform": "EC-Council",
        "link": "https://www.eccouncil.org/",
        "time": "20 Hours",
        "project": "Penetration Testing Lab"
    },

    "Cryptography": {
        "platform": "Cryptography I",
        "link": "https://www.coursera.org/learn/crypto",
        "time": "15 Hours",
        "project": "Encryption Tool"
    },

    "SIEM": {
        "platform": "Splunk Education",
        "link": "https://www.splunk.com/en_us/training.html",
        "time": "10 Hours",
        "project": "Log Monitoring Dashboard"
    },

    "Risk Assessment": {
        "platform": "Microsoft Learn",
        "link": "https://learn.microsoft.com/",
        "time": "8 Hours",
        "project": "Security Audit Report"
    }


}
# ==============================================
# Skill Analysis
# ==============================================

def analyse_skills(user):

    required = career_database[user.goal]

    matched = []
    missing = []

    for skill in required:

        user_skill_names = [s.lower() for s in user.skills.keys()]

        if skill.lower() in user_skill_names:
            matched.append(skill)
        else:
            missing.append(skill)

    score = (len(matched) / len(required)) * 100

    return matched, missing, score


# ==============================================
# User Level
# ==============================================

def progress(score):

    if score >= 90:
        return "Expert"

    elif score >= 70:
        return "Advanced"

    elif score >= 50:
        return "Intermediate"

    else:
        return "Beginner"


# ==============================================
# Roadmap Generator
# ==============================================

def generate_roadmap(missing):

    roadmap = []

    week = 1

    for skill in missing:

        if skill in course_links:

            roadmap.append({

                "week": week,
                "skill": skill,
                "platform": course_links[skill]["platform"],
                "link": course_links[skill]["link"],
                "time": course_links[skill]["time"],
                "project": course_links[skill]["project"]

            })

        else:

            roadmap.append({

                "week": week,
                "skill": skill,
                "platform": "Search Online",
                "link": "https://www.google.com",
                "time": "Unknown",
                "project": "Practice"

            })

        week += 1

    return roadmap
# ==============================================
# MAIN FUNCTION (Gradio Backend)
# ==============================================

def predict(
    name,
    goal,
    skills_input,
    skill_levels,
    confidence,
    consistency,
    adaptability,
    traits
):

    # ------------------------------------------
    # Convert skills into dictionary
    # ------------------------------------------

    skills = {}

    skills_list = [skill.strip() for skill in skills_input.split(",")]

    levels_list = [level.strip() for level in skill_levels.split(",")]

    for i in range(min(len(skills_list), len(levels_list))):
        skills[skills_list[i]] = levels_list[i]

    # ------------------------------------------
    # Convert traits into list
    # ------------------------------------------

    traits = [trait.strip() for trait in traits.split(",")]

    # ------------------------------------------
    # Create User Object
    # ------------------------------------------

    user = User(
        name=name,
        goal=goal,
        skills=skills,
        confidence=confidence,
        consistency=consistency,
        adaptability=adaptability,
        traits=traits
    )

    # ------------------------------------------
    # Analyse Skills
    # ------------------------------------------

    matched, missing, score = analyse_skills(user)

    level = progress(score)

    roadmap = generate_roadmap(missing)

    # ------------------------------------------
    # Generate Report
    # ------------------------------------------

    report = ""

    report += "=" * 60 + "\n"
    report += "        AI SKILL REPORT\n"
    report += "=" * 60 + "\n\n"

    report += f"Name          : {user.name}\n"
    report += f"Career Goal   : {user.goal}\n"
    report += f"Skill Score   : {score:.2f}%\n"
    report += f"Current Level : {level}\n\n"

    report += "Potential Assessment\n"
    report += "-" * 30 + "\n"

    report += f"Confidence    : {user.confidence}\n"
    report += f"Consistency   : {user.consistency}\n"
    report += f"Adaptability  : {user.adaptability}\n\n"

    report += "Other Traits\n"

    for trait in user.traits:
        report += f"✔ {trait}\n"

    report += "\n"

    report += "Matched Skills\n"
    report += "-" * 30 + "\n"

    if len(matched) == 0:
        report += "No matched skills found.\n"
    else:
        for skill in matched:
            report += f"✔ {skill} - {user.skills.get(skill,'Not Rated')}\n"

    report += "\n"

    report += "Missing Skills\n"
    report += "-" * 30 + "\n"

    if len(missing) == 0:
        report += "No missing skills.\n"
    else:
        for skill in missing:
            report += f"✘ {skill}\n"

    report += "\n"

    report += "=" * 60 + "\n"
    report += "PERSONALIZED LEARNING ROADMAP\n"
    report += "=" * 60 + "\n"

    if len(roadmap) == 0:

        report += "\nExcellent! You already possess all required skills.\n"

    else:

        for item in roadmap:

            report += "\n"

            report += f"Week {item['week']}\n"

            report += "-" * 35 + "\n"

            report += f"Skill            : {item['skill']}\n"

            report += f"Platform         : {item['platform']}\n"

            report += f"Estimated Time   : {item['time']}\n"

            report += f"Mini Project     : {item['project']}\n"

            report += "Course Link      :\n"

            report += item["link"] + "\n"

    report += "\n"

    report += "=" * 60 + "\n"

    report += "Congratulations!\n"

    report += "Complete the roadmap and update your skills.\n"

    report += "=" * 60

    return report
# ==============================================
# GRADIO USER INTERFACE
# ==============================================

demo = gr.Interface(

    fn=predict,

    inputs=[

        gr.Textbox(
            label="👤 Enter Your Name",
            placeholder="Enter your full name"
        ),

        gr.Dropdown(

            choices=[

                "Software Developer",
                "Data Analyst",
                "AI Engineer",
                "UI/UX Designer",
                "Cloud Engineer",
                "Cybersecurity Analyst",
                "Web Developer"

            ],

            value="AI Engineer",

            label="🎯 Career Goal"

        ),

        gr.Textbox(

            label="💻 Skills (Comma Separated)",

            placeholder="Python, SQL, Git"

        ),

        gr.Textbox(

            label="📊 Skill Levels (Same Order)",

            placeholder="Advanced, Intermediate, Beginner"

        ),

        gr.Slider(

            minimum=1,

            maximum=5,

            value=3,

            step=1,

            label="⭐ Confidence"

        ),

        gr.Dropdown(

            choices=[
                "Daily",
                "Weekly",
                "Monthly",
                "Sometimes"
            ],

            value="Daily",

            label="📅 Consistency"

        ),

        gr.Slider(

            minimum=1,

            maximum=5,

            value=3,

            step=1,

            label="🔄 Adaptability"

        ),

        gr.Textbox(

            label="🤝 Other Traits",

            placeholder="Communication, Leadership, Teamwork"

        )

    ],

    outputs=gr.Textbox(

        label="📄 AI Skill Report",

        lines=35

    ),

    title="🚀 AI Skill Gap Detection & Career Development System",

    description="""
This AI system analyzes your existing skills,
detects missing skills for your desired career,
and generates a personalized learning roadmap
with free learning resources and mini projects.
""",

    theme="soft"

)

demo.launch()